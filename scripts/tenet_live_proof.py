#!/usr/bin/env python
"""Live proof of the TENET T2 control-plane contract - one process, one chain, one JSON line.

What it does, in order, against a *real* server process (not a test client):

  1. boots ``control_plane.app`` on a free port in a subprocess with a throwaway state dir;
  2. drives the whole receipt vocabulary through the real kernel - ``allow``, ``redact``,
     ``deny`` by policy, ``deny`` by the operator, ``human`` (hold) then ``approve``
     (executed), ``human`` (hold) then ``revoke`` (the hold expires as a *state*), and a
     reused/named-person guard on the approve route;
  3. refuses a bad agent token at the intercept and a wrong operator token (401) - the
     authentication check runs before any model call, per D4;
  4. re-proves a held action across a process restart on the same state dir (hold -> restart
     -> approve), so persistence, not just an in-memory queue, is what is claimed;
  5. asks the real 4-agent orchestrator over ``/api/ask``, or - with no key present - records
     the DEMO degradation instead of pretending a model answered;
  6. prints exactly one JSON line and exits non-zero on any failed check.

Nothing here decides anything: every verdict comes from the kernel, and the script only reads
what the control plane reports. Run it with the provider key exported:

    set -a; . ./.env; set +a
    python scripts/tenet_live_proof.py

Set ``TENET_PROOF_NO_KEY=1`` to prove the no-key degradation path (the assistance surface
falls back to DEMO; the enforcement path is untouched).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "live-proof-admin-token"
CHECKS: list[dict[str, Any]] = []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _call(url: str, *, method: str = "GET", body: dict | None = None,
          token: str = "", timeout: float = 120.0) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("x-warrnt-admin", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def check(name: str, ok: bool, detail: Any = None) -> bool:
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def _wait_ready(base: str, proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            status, _ = _call(f"{base}/health", timeout=2.0)
            if status == 200:
                return True
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(0.3)
    return False


def _spawn(base: str, state_dir: Path, *, no_key: bool = False) -> subprocess.Popen:
    """Boot one real server process on the given port and state dir."""
    env = {**os.environ, "PORT": base.rsplit(":", 1)[1], "HOST": "127.0.0.1",
           "TENET_STATE_DIR": str(state_dir), "WARRNT_ADMIN_TOKEN": ADMIN_TOKEN,
           "TENET_MODE": "live", "WARRNT_DEV": "1"}
    if no_key:
        env.pop("DEEPSEEK_API_KEY", None)
    return subprocess.Popen(
        [sys.executable, "-m", "control_plane"], cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _stop(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        out = proc.stdout.read() if proc.stdout is not None else ""
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        proc.kill()
        out = proc.stdout.read() if proc.stdout is not None else ""
    return out or ""


def _boot(base: str, state_dir: Path, *, no_key: bool = False) -> subprocess.Popen:
    proc = _spawn(base, state_dir, no_key=no_key)
    if not _wait_ready(base, proc):
        tail = _stop(proc)[-1500:]
        raise RuntimeError(json.dumps({"error": "server did not become ready",
                                       "server_output_tail": tail}))
    return proc


def _mcp_raw(base: str, agent: str, token: str, tool: str, args: dict,
             run_id: str = "") -> tuple[int, dict[str, Any]]:
    """Call ``/mcp`` and return the HTTP status even when the intercept denies (403)."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": args}}
    req = urllib.request.Request(f"{base}/mcp", data=json.dumps(payload).encode(),
                                method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-warrnt-agent", agent)
    req.add_header("x-warrnt-token", token)
    if run_id:
        req.add_header("x-warrnt-run", run_id)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def _mcp(base: str, agent: str, token: str, tool: str, args: dict,
         run_id: str = "") -> dict[str, Any]:
    """Call the control plane's ``/mcp`` intercept exactly as an agent would."""
    return _mcp_raw(base, agent, token, tool, args, run_id=run_id)[1]


def _drive_kernel(base: str) -> dict[str, Any]:
    """Step 2-3: drive the receipt vocabulary over HTTP, through the ONE process.

    Every call goes to ``/mcp`` on the same server the console and the answer read, so the
    proof exercises the deployment exactly as it ships - no in-process shortcut, no second
    instance. Tokens come from ``/api/agents`` with ``WARRNT_DEV=1`` set for the proof only.
    """
    st, agents = _call(f"{base}/api/agents")
    tokens = {a["id"]: a.get("token", "") for a in agents if a.get("token")}
    out: dict[str, Any] = {}

    r = _mcp(base, "fin-reconcile", tokens["fin-reconcile"], "payments.read",
             {"table": "payments", "limit": 5}, run_id="proof-allow-1")
    res = r.get("result", {})
    out["allow_id"] = res.get("action_id")
    check("allow: executed upstream",
          res.get("decision") == "allow" and res.get("executed") is True,
          {"decision": res.get("decision"), "executed": res.get("executed"),
           "action": out["allow_id"]})

    r = _mcp(base, "support-copilot", tokens["support-copilot"], "crm.read",
             {"fields": ["subject", "email", "pesel"]}, run_id="proof-redact-1")
    res = r.get("result", {})
    out["redact_id"] = res.get("action_id")
    check("redact: PII stripped before the reader saw it",
          res.get("decision") == "redact" and "email" in (res.get("redacted") or []),
          {"decision": res.get("decision"), "redacted": res.get("redacted")})

    r = _mcp(base, "support-copilot", tokens["support-copilot"], "crm.bulk_export",
             {"table": "customers", "rows": 9000}, run_id="proof-deny-1")
    err = r.get("error", {})
    out["deny_id"] = (err.get("data") or {}).get("action_id")
    check("deny: upstream untouched",
          (err.get("data") or {}).get("decision") == "deny"
          and (err.get("data") or {}).get("executed") is False,
          {"decision": (err.get("data") or {}).get("decision"), "action": out["deny_id"]})
    st, detail = _call(f"{base}/api/actions/{out['deny_id']}")
    check("deny action records upstream_contacted=false",
          st == 200 and detail.get("upstream_contacted") is False,
          detail.get("upstream_contacted"))

    r = _mcp(base, "report-bot", tokens["report-bot"], "crm.bulk_export",
             {"table": "customers", "rows": 500}, run_id="proof-hold-1")
    err = r.get("error", {})
    out["hold_id"] = (err.get("data") or {}).get("action_id")
    check("human: held, not executed",
          (err.get("data") or {}).get("decision") == "human"
          and (err.get("data") or {}).get("executed") is False,
          {"decision": (err.get("data") or {}).get("decision"), "action": out["hold_id"]})
    st, pending = _call(f"{base}/api/actions/pending")
    check("hold is pending",
          any(a.get("action_id") == out["hold_id"] for a in pending.get("pending", [])),
          pending.get("count"))

    st, approved = _call(f"{base}/api/actions/{out['hold_id']}/approve", method="POST",
                         body={"by": "anna.kowalska"}, token=ADMIN_TOKEN)
    check("named person approved -> executed",
          st == 200 and approved.get("executed") is True and approved.get("state") == "approved",
          {"state": approved.get("state"), "by": approved.get("decided_by"),
           "receipt": approved.get("receipt_id")})
    st, held_row = _call(f"{base}/api/actions/{out['hold_id']}")
    check("approved action contacted upstream",
          held_row.get("upstream_contacted") is True, held_row.get("upstream_contacted"))

    st, _refused = _call(f"{base}/api/actions/{out['hold_id']}/approve", method="POST",
                         body={"by": "mallory"}, token="wrong-token")
    check("wrong operator token refused", st == 401, st)
    st, _refused2 = _call(f"{base}/api/actions/{out['hold_id']}/approve", method="POST",
                          body={"by": ""}, token=ADMIN_TOKEN)
    check("approve without a named person refused (422)",
          st == 422, {"status": st, "body": _refused2})

    # --- deny by the operator: a held action denied by a named person still never executes ---
    r = _mcp(base, "report-bot", tokens["report-bot"], "crm.bulk_export",
             {"table": "customers", "rows": 30}, run_id="proof-deny-2")
    err = r.get("error", {})
    out["deny_pending_id"] = (err.get("data") or {}).get("action_id")
    check("operator-deny: the action was held first",
          (err.get("data") or {}).get("decision") == "human" and bool(out["deny_pending_id"]),
          {"decision": (err.get("data") or {}).get("decision"), "action": out["deny_pending_id"]})
    st, denied = _call(f"{base}/api/actions/{out['deny_pending_id']}/deny", method="POST",
                       body={"by": "piotr.nowak", "reason": "out of scope for this run"},
                       token=ADMIN_TOKEN)
    check("operator denied a held action -> not executed",
          st == 200 and denied.get("executed") is False
          and denied.get("state") in ("denied", "revoked"),
          {"state": denied.get("state"), "by": denied.get("decided_by"),
           "executed": denied.get("executed")})
    st, denied_row = _call(f"{base}/api/actions/{out['deny_pending_id']}")
    check("operator-denied action never contacted upstream",
          denied_row.get("upstream_contacted") is False, denied_row.get("upstream_contacted"))

    # --- bad agent token: authentication runs before any model call (D4) ---
    status, r = _mcp_raw(base, "fin-reconcile", "not-a-real-token", "payments.read",
                         {"table": "payments", "limit": 5}, run_id="proof-badauth-1")
    out["badauth_status"] = status
    code = r.get("error", {}).get("code")
    check("bad agent token refused at the intercept (unknown identity)",
          code in (-32001, -32002, -32003, 401) and "unknown agent" in str(
              r.get("error", {}).get("message", "")).lower(),
          {"http": status, "code": code, "message": r.get("error", {}).get("message")})

    r = _mcp(base, "report-bot", tokens["report-bot"], "crm.bulk_export",
             {"table": "customers", "rows": 15}, run_id="proof-restart-1")
    out["restart_hold_id"] = (r.get("error", {}).get("data") or {}).get("action_id")
    check("restart: held before shutdown",
          (r.get("error", {}).get("data") or {}).get("decision") == "human"
          and bool(out["restart_hold_id"]),
          {"action": out["restart_hold_id"],
           "decision": (r.get("error", {}).get("data") or {}).get("decision")})
    st, before = _call(f"{base}/api/actions/{out['restart_hold_id']}")
    check("restart: pending, never executed, before shutdown",
          before.get("state") == "pending" and before.get("upstream_contacted") is False,
          {"state": before.get("state"), "upstream": before.get("upstream_contacted")})
    return out


def _check_revoke_expiry(base: str, tokens: dict[str, str]) -> str:
    """Step 3b: revoking an agent halts it and expires the hold it was waiting on.

    A hold that times out is a *state* change, never a decision: the ``human`` verdict stands
    and the upstream is never contacted. This runs last, because revoking halts ``report-bot``
    for the remainder of the process.
    """
    r = _mcp(base, "report-bot", tokens["report-bot"], "crm.bulk_export",
             {"table": "customers", "rows": 25}, run_id="proof-hold-2")
    hold2_id = (r.get("error", {}).get("data") or {}).get("action_id")
    st, revoked = _call(f"{base}/api/agents/report-bot/revoke", method="POST", token=ADMIN_TOKEN)
    check("revoke halts the agent", st == 200 and revoked.get("state") == "halted",
          revoked.get("state"))
    st, exp_row = _call(f"{base}/api/actions/{hold2_id}")
    check("hold expired (a state, not a decision)",
          exp_row.get("state") == "expired" and exp_row.get("upstream_contacted") is False,
          {"state": exp_row.get("state"), "upstream": exp_row.get("upstream_contacted")})
    return hold2_id


def _check_proof_projection(base: str) -> dict[str, Any]:
    """TASK D: the PROOF panel reads kernel projections only - chain + run/action/receipt."""
    st, proof = _call(f"{base}/api/proof?limit=50")
    check("/api/proof served from the kernel projection",
          st == 200 and isinstance(proof.get("chain"), dict)
          and isinstance(proof.get("correlation"), list),
          {"status": st, "keys": sorted(proof.keys())})
    check("proof chain verifies over the live ledger",
          bool(proof.get("chain", {}).get("ok")), proof.get("chain"))
    corr = proof.get("correlation", [])
    check("every proof correlation row is receipt-correlated",
          bool(corr) and all(lnk.get("receipt_in_chain") for lnk in corr),
          {"rows": len(corr),
           "not_in_chain": [lnk.get("receipt") for lnk in corr
                            if not lnk.get("receipt_in_chain")][:5]})
    check("proof correlates run_id <-> action_id <-> receipt",
          any(lnk.get("run_id") and lnk.get("action_id") and lnk.get("receipt")
              for lnk in corr),
          [{"run": lnk.get("run_id"), "action": lnk.get("action_id"),
            "receipt": lnk.get("receipt")} for lnk in corr[:3]])
    st, state = _call(f"{base}/api/state")
    check("/api/state carries chain + proof (the panel's single read)",
          st == 200 and "chain" in state and "proof" in state,
          {"keys": sorted(state.keys())})
    return proof


def _check_restart_persistence(base: str, hold_id: str) -> dict[str, Any]:
    """TASK E: hold was created pre-restart; here we only read it back by id."""
    st, before = _call(f"{base}/api/actions/{hold_id}")
    check("restart: pending, never executed, before shutdown",
          before.get("state") == "pending" and before.get("upstream_contacted") is False,
          {"state": before.get("state"), "upstream": before.get("upstream_contacted")})
    return {"hold_id": hold_id, "pending_before": before.get("state")}


def _check_denials_recorded(base: str, allowed_id: str, deny_id: str) -> None:
    """A denial is itself a recordable event (D5): it appears in the ledger, not just in a log."""
    st, actions = _call(f"{base}/api/actions?limit=200")
    rows = {a.get("action_id") or a.get("id"): a for a in actions.get("actions", [])}
    check("deny is a recorded action, not a lost request",
          st == 200 and deny_id in rows, {"status": st, "in_ledger": deny_id in rows})
    denied_row = rows.get(deny_id, {})
    check("recorded denial carries decision=deny and a receipt",
          denied_row.get("decision") == "deny" and bool(denied_row.get("receipt")
                                                        or denied_row.get("receipt_id")),
          {"decision": denied_row.get("decision"),
           "receipt": denied_row.get("receipt") or denied_row.get("receipt_id")})
    check("recorded denial never contacted upstream",
          denied_row.get("upstream_contacted") is False,
          denied_row.get("upstream_contacted"))


def _check_console_page(html: Any) -> None:
    """TASK C: the console page is served, and it carries no enforcement secret."""
    page = html if isinstance(html, str) else json.dumps(html)
    check("console Control Room page served", "<html" in page.lower(), len(page))
    check("console page leaks no operator secret",
          ADMIN_TOKEN not in page and "warrnt-signing-key" not in page,
          [s for s in (ADMIN_TOKEN, "warrnt-signing-key") if s in page])


def _check_correlation(base: str, action_id: str) -> None:
    """Step 4a: one correlation, two traces - run_id rides both the receipt and the action."""
    st, row = _call(f"{base}/api/actions/{action_id}")
    check("action read back by id",
          st == 200 and (row.get("action_id") or row.get("id")) == action_id,
          {"status": st, "action": action_id})
    check("held-then-approved action carries a receipt",
          bool(row.get("receipt") or row.get("receipt_id")),
          row.get("receipt") or row.get("receipt_id"))
    check("approved hold was executed exactly once",
          row.get("state") == "approved" and row.get("upstream_contacted") is True,
          {"state": row.get("state"), "upstream": row.get("upstream_contacted")})
    st, feed = _call(f"{base}/api/activity?limit=50")
    events = feed.get("events", [])
    check("activity carries the run_id on receipt and action events",
          any(e.get("run_id") == "proof-hold-1" for e in events),
          sorted({e.get("run_id") for e in events if e.get("run_id")}))
    check("activity carries action_id", any(e.get("action_id") == action_id for e in events),
          [e.get("action_id") for e in events if e.get("action_id")][:5])
    st, overview = _call(f"{base}/api/overview")
    st, ledger = _call(f"{base}/api/actions?limit=200")
    rows = ledger if isinstance(ledger, list) else ledger.get("actions", [])
    counts = overview.get("counts", {})
    check("overview counts match the record",
          counts.get("actions") == len(rows) and counts.get("actions") >= 5
          and counts.get("pending") == sum(1 for a in rows if a.get("state") == "pending")
          and counts.get("pending") >= 1,
          {"overview": counts, "ledger_rows": len(rows),
           "pending_in_ledger": sum(1 for a in rows if a.get("state") == "pending")})
    check("chain verified", bool(overview.get("chain", {}).get("ok")), overview.get("chain"))


def _check_ask(base: str, deny_id: str) -> tuple[dict[str, Any], float, str]:
    """Step 4b: the real 4-agent DeepSeek orchestrator, grounded in the recorded ids."""
    t0 = time.time()
    st, answer = _call(f"{base}/api/ask", method="POST", body={
        "q": "Which actions were blocked from reaching an upstream, and is any action "
             "still waiting for a person?"}, timeout=180.0)
    elapsed = round(time.time() - t0, 1)
    check("ask answered 200", st == 200, st)
    text = str(answer.get("answer", ""))
    check("ask used all three specialists as tools",
          set(answer.get("specialists", [])) ==
          {"governance_agent", "kernel_agent", "control_plane_agent"},
          answer.get("specialists"))
    check("answer is grounded in a real action id", deny_id in text, deny_id)
    check("evidence carries a real action_id",
          any(e.get("action_id") for e in answer.get("evidence", [])),
          [e.get("action_id") for e in answer.get("evidence", [])][:5])
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    check("no provider key value leaked into the answer",
          not any(s in text or s in json.dumps(answer) for s in (["sk-"] + ([key] if key else []))),
          len(text))
    return answer, elapsed, text


def main() -> int:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    state_dir = Path(os.environ.get("TENET_PROOF_STATE_DIR", "/tmp/tenet-live-proof"))
    shutil.rmtree(state_dir, ignore_errors=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    no_key = os.environ.get("TENET_PROOF_NO_KEY") == "1"
    restarts = 0
    server = None
    try:
        server = _boot(base, state_dir, no_key=no_key)

        st, health = _call(f"{base}/health")
        check("health 200", st == 200, st)
        check("health LIVE", health.get("status") == "LIVE", health.get("status"))
        check("provider key REPORTED as name, never value",
              health.get("provider_key") in ("PRESENT", "MISSING"), health.get("provider_key"))
        if no_key:
            check("no-key mode: assistance surface degrades to DEMO",
                  health.get("status") == "DEMO", health.get("status"))
        else:
            check("health names deepseek", health.get("model_provider") == "deepseek",
                  health.get("model_provider"))

        chain = _drive_kernel(base)
        _check_correlation(base, chain["hold_id"])
        proof = _check_proof_projection(base)

        # TASK E: a hold created before shutdown survives a process restart and still runs.
        restart = _check_restart_persistence(base, chain["restart_hold_id"])
        _check_denials_recorded(base, chain["allow_id"], chain["deny_id"])
        st, page = _call(f"{base}/")
        _check_console_page(page)
        _stop(server)
        server = None
        restarts += 1
        server = _boot(base, state_dir, no_key=no_key)
        st, after = _call(f"{base}/api/actions/{restart['hold_id']}")
        check("restart: hold survived the process restart",
              st == 200 and after.get("state") == "pending" and after.get("executed") is not True,
              {"state": after.get("state"), "executed": after.get("executed")})
        st, approved = _call(f"{base}/api/actions/{restart['hold_id']}/approve", method="POST",
                            body={"by": "anna.kowalska"}, token=ADMIN_TOKEN)
        check("restart: approved after restart -> executed",
              st == 200 and approved.get("executed") is True,
              {"state": approved.get("state"), "executed": approved.get("executed"),
               "receipt": approved.get("receipt_id")})
        st, after_row = _call(f"{base}/api/actions/{restart['hold_id']}")
        check("restart: executed row contacted upstream after restart",
              after_row.get("upstream_contacted") is True, after_row.get("upstream_contacted"))

        answer, elapsed, text = _check_ask(base, chain["deny_id"])

        # TASK A/B tail: revoking halts the agent and drops the hold it was waiting on. Run
        # last: the halt is for the remainder of this process (the hold is a state, not a
        # decision - the human verdict and the untouched upstream both stand).
        st, agents2 = _call(f"{base}/api/agents")
        tokens2 = {a["id"]: a.get("token", "") for a in agents2 if a.get("token")}
        hold2_id = _check_revoke_expiry(base, tokens2)
        st, proof2 = _call(f"{base}/api/proof?limit=50")
        check("proof still verifies after the revoke",
              st == 200 and proof2.get("chain", {}).get("ok") is True,
              proof2.get("chain", {}).get("ok"))

        ok = all(c["ok"] for c in CHECKS)
        print(json.dumps({
            "ok": ok,
            "proved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": base,
            "mode": health.get("mode"), "status": health.get("status"),
            "provider": {"name": health.get("provider"), "model": health.get("model"),
                         "key": health.get("provider_key"), "no_key_forced": no_key},
            "process_restarts": restarts,
            "chain": {"allow": chain["allow_id"], "redact": chain["redact_id"],
                      "deny": chain["deny_id"], "operator_deny": chain["deny_pending_id"],
                      "human_approved": chain["hold_id"], "human_expired": hold2_id,
                      "bad_token_http": chain["badauth_status"],
                      "restart_hold": chain["restart_hold_id"]},
            "proof": {"chain_ok": proof.get("chain", {}).get("ok"),
                      "links": len(proof.get("correlation", []))},
            "ask": {"run_id": answer.get("run_id"), "seconds": elapsed,
                    "specialists": answer.get("specialists"),
                    "grounded": answer.get("grounded"), "answer_head": text[:280]},
            "checks": CHECKS, "failed": [c["check"] for c in CHECKS if not c["ok"]],
        }, ensure_ascii=False))
        return 0 if ok else 1
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    finally:
        if server is not None:
            _stop(server)


if __name__ == "__main__":
    raise SystemExit(main())
