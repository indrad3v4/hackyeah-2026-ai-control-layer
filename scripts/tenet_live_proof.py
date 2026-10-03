#!/usr/bin/env python
"""Live proof of the TENET T2 control-plane contract - one process, one chain, one JSON line.

What it does, in order, against a *real* server process (not a test client):

  1. boots ``control_plane.app`` on a free port in a subprocess with a throwaway state dir;
  2. drives the whole receipt vocabulary through the real kernel - ``allow``, ``redact``,
     ``deny``, ``human`` (hold) - and then releases the hold by a named person (``approve``);
  3. halts an agent whose action is pending, proving a hold expires (a *state*, not a decision);
  4. asks the real 4-agent DeepSeek orchestrator over ``/api/ask`` and checks the answer is
     grounded in the ids the kernel actually recorded;
  5. prints exactly one JSON line and exits non-zero on any failed check.

Nothing here decides anything: every verdict comes from the kernel, and the script only reads
what the control plane reports. Run it with the provider key exported:

    set -a; . ./.env; set +a
    python scripts/tenet_live_proof.py
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


def _mcp(base: str, agent: str, token: str, tool: str, args: dict,
         run_id: str = "") -> dict[str, Any]:
    """Call the control plane's ``/mcp`` intercept exactly as an agent would."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": args}}
    req = urllib.request.Request(f"{base}/mcp", data=json.dumps(payload).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-warrnt-agent", agent)
    req.add_header("x-warrnt-token", token)
    if run_id:
        req.add_header("x-warrnt-run", run_id)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


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

    r = _mcp(base, "report-bot", tokens["report-bot"], "crm.bulk_export",
             {"table": "customers", "rows": 25}, run_id="proof-hold-2")
    out["hold2_id"] = (r.get("error", {}).get("data") or {}).get("action_id")
    st, revoked = _call(f"{base}/api/agents/report-bot/revoke", method="POST", token=ADMIN_TOKEN)
    check("revoke halts the agent", st == 200 and revoked.get("state") == "halted",
          revoked.get("state"))
    st, exp_row = _call(f"{base}/api/actions/{out['hold2_id']}")
    check("hold expired (a state, not a decision)",
          exp_row.get("state") == "expired" and exp_row.get("upstream_contacted") is False,
          {"state": exp_row.get("state"), "upstream": exp_row.get("upstream_contacted")})
    return out


def _check_correlation(base: str, hold_id: str) -> None:
    """Step 4: one correlation, two traces - the run_id rides both the receipt and the action."""
    st, feed = _call(f"{base}/api/activity?limit=50")
    events = feed.get("events", [])
    check("activity carries the run_id on receipt and action events",
          any(e.get("run_id") == "proof-hold-1" for e in events),
          sorted({e.get("run_id") for e in events if e.get("run_id")}))
    check("activity carries action_id", any(e.get("action_id") == hold_id for e in events),
          [e.get("action_id") for e in events if e.get("action_id")][:5])
    st, overview = _call(f"{base}/api/overview")
    check("overview counts match the record",
          overview["counts"]["actions"] >= 5 and overview["counts"]["pending"] == 0,
          overview.get("counts"))
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

    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
           "TENET_STATE_DIR": str(state_dir), "WARRNT_ADMIN_TOKEN": ADMIN_TOKEN,
           "TENET_MODE": "live", "WARRNT_DEV": "1"}
    server = subprocess.Popen(
        [sys.executable, "-m", "control_plane"], cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not _wait_ready(base, server):
            tail = ""
            if server.stdout is not None:
                try:
                    server.terminate()
                    tail = (server.stdout.read() or "")[-1500:]
                except Exception:  # noqa: BLE001
                    pass
            print(json.dumps({"ok": False, "error": "server did not become ready",
                              "server_output_tail": tail}))
            return 1

        st, health = _call(f"{base}/health")
        check("health 200", st == 200, st)
        check("health LIVE", health.get("status") == "LIVE", health.get("status"))
        check("provider key PRESENT (name only)", health.get("provider_key") == "PRESENT",
              health.get("provider_key"))
        check("health names deepseek", health.get("model_provider") == "deepseek",
              health.get("model_provider"))

        chain = _drive_kernel(base)
        _check_correlation(base, chain["hold_id"])
        answer, elapsed, text = _check_ask(base, chain["deny_id"])

        ok = all(c["ok"] for c in CHECKS)
        print(json.dumps({
            "ok": ok,
            "proved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": base,
            "mode": health.get("mode"), "status": health.get("status"),
            "provider": {"name": health.get("provider"), "model": health.get("model"),
                         "key": health.get("provider_key")},
            "chain": {"allow": chain["allow_id"], "redact": chain["redact_id"],
                      "deny": chain["deny_id"], "human_approved": chain["hold_id"],
                      "human_expired": chain["hold2_id"]},
            "ask": {"run_id": answer.get("run_id"), "seconds": elapsed,
                    "specialists": answer.get("specialists"), "answer_head": text[:280]},
            "checks": CHECKS, "failed": [c["check"] for c in CHECKS if not c["ok"]],
        }, ensure_ascii=False))
        return 0 if ok else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:  # noqa: BLE001
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
