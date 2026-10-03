#!/usr/bin/env python
"""T1 proof: the upstream behind the gate is REAL, and ``upstream_contacted`` is read from it.

The fixture MCP server answered with synthetic rows, so "did this call reach upstream" was
answered by the node's own counter - a claim about itself. This proof replaces that with the
Frankfurter upstream (``upstream/frankfurter_server.py``) and reads the answer from the
*upstream's own access log*:

  1. starts the real MCP upstream (real HTTPS to ``api.frankfurter.dev``) with its own log;
  2. starts the control plane with ``WARRNT_UPSTREAM`` pointed at it;
  3. drives three calls through the one process, all carrying an explicit ``call_id``:
       ALLOW  ``fx-trader``       ``fx.rate``  -> executes, real rate returned;
       DENY   ``support-copilot`` ``fx.rate`` -> refused BEFORE execution;
       HUMAN  ``fx-auditor``      ``fx.rate`` -> held, a person decides;
  4. reads the upstream's log and asserts the ALLOW ``call_id`` is present and the DENY and
     HUMAN ``call_id`` are absent. The upstream is the witness, not the layer.

Exits non-zero on any failed check, and prints one JSON line plus a PASS/FAIL table.

    python scripts/t1_upstream_proof.py [--evidence docs/t1-upstream-evidence.json]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "t1-proof-admin-token"
PY = os.environ.get("TENET_PY", sys.executable)
CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: Any = None) -> bool:
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _call(url: str, *, method: str = "GET", body: dict | None = None,
          headers: dict[str, str] | None = None, timeout: float = 60.0) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
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


def _wait_port(host: str, port: int, timeout: float = 40.0) -> None:
    """Wait for a TCP listener - the MCP streamable endpoint answers with an endless SSE
    stream, so an HTTP GET would hang; a socket connect is the honest readiness probe."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"nothing listening on {host}:{port} after {timeout}s")


def _wait_health(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    r.read(64)
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f"nothing healthy at {url} after {timeout}s")


def _upstream_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _call_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {str(r.get("call_id", "")) for r in rows if r.get("call_id")}


def _crossing_sha(rows: list[dict[str, Any]], call_id: str) -> str:
    """The digest the upstream itself recorded for one call, or ``''`` if it never arrived."""
    for row in rows:
        if row.get("call_id") == call_id:
            return str((row.get("crossing") or {}).get("response_sha256") or "")
    return ""


def _mcp(base: str, agent: str, token: str, tool: str, args: dict) -> dict:
    _st, out = _call(f"{base}/mcp", method="POST",
                     body={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}},
                     headers={"x-warrnt-agent": agent, "x-warrnt-token": token})
    return out if isinstance(out, dict) else {"raw": out}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", default="")
    args = parser.parse_args()

    state_dir = Path("/tmp/tenet-t1-proof-state")
    upstream_log = Path("/tmp/tenet-t1-proof-calls.jsonl")
    upstream_log.unlink(missing_ok=True)

    up_port, cp_port = _free_port(), _free_port()
    env_up = {**os.environ, "FRANKFURTER_LOG": str(upstream_log)}
    env_cp = {**os.environ, "TENET_STATE_DIR": str(state_dir), "WARRNT_ADMIN_TOKEN": ADMIN_TOKEN,
              "WARRNT_DEV": "1", "WARRNT_UPSTREAM": f"http://127.0.0.1:{up_port}/mcp"}

    upstream = subprocess.Popen(
        [PY, "-m", "upstream.frankfurter_server", "--port", str(up_port),
         "--log", str(upstream_log)], cwd=str(REPO_ROOT), env=env_up,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    plane = subprocess.Popen(
        [PY, "-m", "uvicorn", "control_plane.app:app", "--host", "127.0.0.1",
         "--port", str(cp_port)], cwd=str(REPO_ROOT), env=env_cp,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{cp_port}"

    try:
        _wait_port("127.0.0.1", up_port)
        _wait_health(f"{base}/health")
        _st, health = _call(f"{base}/health")
        check("control plane is up and healthy", _st == 200 and isinstance(health, dict),
              health if isinstance(health, dict) else str(health)[:80])

        _st, agents = _call(f"{base}/api/agents")
        tokens = {a["id"]: a.get("token", "") for a in agents} if isinstance(agents, list) else {}
        check("the live-upstream warrants are registered",
              {"fx-trader", "fx-auditor"} <= set(tokens), sorted(tokens))

        # ---- ALLOW: a real Frankfurter call, with our explicit call_id -------------------
        allow_id = "call-t1-allow-001"
        out = _mcp(base, "fx-trader", tokens.get("fx-trader", ""), "fx.read_rate",
                   {"call_id": allow_id, "base": "EUR", "symbols": "USD"})
        res = out.get("result", {})
        check("ALLOW: fx.rate executed",
              res.get("decision") == "allow" and res.get("executed") is True, res.get("reason"))
        check("ALLOW: the real Frankfurter rate came back",
              bool(res.get("rates"))
              and str(res.get("source", "")).startswith("https://api.frankfurter.dev"),
              {"rates": res.get("rates"), "date": res.get("date"), "source": res.get("source")})
        check("ALLOW: the action is on the record", bool(res.get("action_id")), res.get("action_id"))

        # ---- DENY: a warrant that does not cover fx.rate ---------------------------------
        deny_id = "call-t1-deny-001"
        out = _mcp(base, "support-copilot", tokens.get("support-copilot", ""), "fx.read_rate",
                   {"call_id": deny_id, "base": "EUR", "symbols": "USD"})
        err = out.get("error", {})
        check("DENY: support-copilot is refused before execution",
              err.get("code") == -32001 and err.get("data", {}).get("executed") is False,
              err.get("message"))

        # ---- HUMAN: a person decides -----------------------------------------------------
        human_id = "call-t1-human-001"
        out = _mcp(base, "fx-auditor", tokens.get("fx-auditor", ""), "fx.read_rate",
                   {"call_id": human_id, "base": "EUR", "symbols": "USD"})
        err = out.get("error", {})
        check("HUMAN: fx-auditor is held, not executed",
              err.get("code") == -32002 and err.get("data", {}).get("held") is True,
              err.get("message"))
        hold_aid = err.get("data", {}).get("action_id", "")

        # ---- T3: nothing left the box, read from the BOUNDARY's own counter --------------
        _st_s, stats_before = _call(f"http://127.0.0.1:{up_port}/stats")
        check("T3: the boundary exposes its own egress counter",
              _st_s == 200 and isinstance(stats_before, dict) and "sent" in stats_before,
              stats_before)

        # A second refusal, after the counter has already moved once (the allowed call above).
        # A refusal that only looked clean while the counter sat at zero would prove nothing,
        # so the traffic is deliberately mixed.
        deny2_id = "call-t3-deny-after-allow"
        _mcp(base, "support-copilot", tokens.get("support-copilot", ""), "fx.read_rate",
             {"call_id": deny2_id, "base": "EUR", "symbols": "USD"})
        _st_s, stats_after = _call(f"http://127.0.0.1:{up_port}/stats")
        check("T3: sent_counter is unchanged across a denial (nothing left the box)",
              stats_after.get("sent") == stats_before.get("sent"),
              {"before": stats_before.get("sent"), "after": stats_after.get("sent")})
        check("T3: the allowed call is the one that moved sent_counter",
              stats_after.get("sent") == 1 and stats_after.get("completed") == 1,
              {"sent": stats_after.get("sent"), "completed": stats_after.get("completed")})
        check("T3: the denied call is absent from the upstream's own access log",
              deny2_id not in _call_ids(_upstream_log(upstream_log)),
              sorted(_call_ids(_upstream_log(upstream_log))))

        rows = _upstream_log(upstream_log)
        seen = _call_ids(rows)
        check("upstream log records the allowed call_id", allow_id in seen, sorted(seen))
        check("upstream log proves the denied call never arrived", deny_id not in seen, sorted(seen))
        check("upstream log proves the held call never arrived", human_id not in seen, sorted(seen))
        check("the upstream fetched a real rate (not a fixture)",
              any(r.get("rate_fetched") for r in rows),
              [{"call_id": r.get("call_id"), "rate_fetched": r.get("rate_fetched")} for r in rows])

        # ---- and the layer agrees with the upstream --------------------------------------
        _st_all, one = _call(f"{base}/api/actions")
        rows_a = one.get("actions", []) if isinstance(one, dict) else []
        allow_row = next((a for a in rows_a
                          if a.get("tool") == "fx.read_rate" and a.get("decision") == "allow"), {})
        check("the layer marks only the real call as upstream_contacted",
              allow_row.get("upstream_contacted") is True, allow_row.get("upstream_contacted"))
        denied_row = next((a for a in rows_a
                           if a.get("tool") == "fx.read_rate" and a.get("decision") == "deny"), {})
        check("the layer marks the denied call as NOT upstream_contacted",
              denied_row.get("upstream_contacted") is False, denied_row.get("upstream_contacted"))

        # ---- T2: the receipt of the crossing carries what actually crossed ---------------
        aid = res.get("action_id", "")
        _st_a, allow_action = _call(f"{base}/api/actions/{aid}")
        xr = (allow_action or {}).get("execution_result") or {}
        for field in ("endpoint", "http_status", "response_sha256", "value", "latency_ms"):
            check(f"T2: the action record carries {field}",
                  bool(xr.get(field)),
                  {k: xr.get(k) for k in
                   ("endpoint", "http_status", "response_sha256", "value", "latency_ms")})
        check("T2: the recorded endpoint is the real Frankfurter URL",
              str(xr.get("endpoint", "")).startswith("https://api.frankfurter.dev/v1/latest"),
              xr.get("endpoint"))
        check("T2: the recorded status is a real 200", xr.get("http_status") == 200,
              xr.get("http_status"))
        check("T2: the digest agrees with the upstream's own (re-hash agreement)",
              bool(xr.get("response_sha256")) and xr.get("response_sha256") == _crossing_sha(rows, allow_id),
              {"layer": xr.get("response_sha256"), "upstream": _crossing_sha(rows, allow_id)})

        # ---- T4: redaction happens BEFORE egress -----------------------------------------
        redact_id = "call-t4-redact-001"
        out = _mcp(base, "fx-trader", tokens.get("fx-trader", ""), "fx.audit_note",
                   {"call_id": redact_id, "desk": "rates", "fields": ["iban", "desk"]})
        check("T4: the redacted call still executed (redact ranks with allow)",
              (out.get("result") or {}).get("executed") is True, out.get("result"))
        redact_row = next((r for r in _upstream_log(upstream_log) if r.get("call_id") == redact_id),
                          {})
        got_fields = (redact_row.get("args") or {}).get("fields")
        check("T4: the upstream received the call with the personal field already removed",
              isinstance(got_fields, list) and "iban" not in got_fields,
              {"upstream_received_fields": got_fields})
        check("T4: only the personal field was dropped; the non-personal one survived",
              isinstance(got_fields, list) and "desk" in got_fields,
              {"upstream_received_fields": got_fields})

        # ---- T5: a human hold persists, and approval runs the call ------------------------
        check("T5: a live read was held for a person", bool(hold_aid), hold_aid)
        _st_h, hold_row = _call(f"{base}/api/actions/{hold_aid}")
        check("T5: the hold is pending and has not contacted the upstream",
              hold_row.get("state") == "pending"
              and hold_row.get("upstream_contacted") is False,
              {"state": hold_row.get("state"),
               "upstream_contacted": hold_row.get("upstream_contacted")})
        _st_p, approved = _call(f"{base}/api/actions/{hold_aid}/approve", method="POST",
                                body={"by": "anna.kowalska"},
                                headers={"x-warrnt-admin": ADMIN_TOKEN})
        check("T5: approving the hold executes it",
              _st_p == 200 and approved.get("executed") is True,
              {"status": _st_p, "state": approved.get("state"),
               "executed": approved.get("executed")})
        _st_h2, hold_row2 = _call(f"{base}/api/actions/{hold_aid}")
        check("T5: the approved read carries its crossing on the record",
              bool(((hold_row2.get("execution_result") or {}).get("response_sha256"))),
              hold_row2.get("execution_result"))
        check("T5: the approved read reached the upstream, exactly once",
              sum(1 for r in _upstream_log(upstream_log) if r.get("call_id") == human_id) == 1,
              [(r.get("call_id"), r.get("outcome")) for r in _upstream_log(upstream_log)])

        # ---- T6: revoke halts the actor; the next call is REFUSED, not allowed -----------
        _st_rv, revoked = _call(f"{base}/api/agents/fx-trader/revoke", method="POST",
                                body={"by": "operator"},
                                headers={"x-warrnt-admin": ADMIN_TOKEN})
        check("T6: revoking the trader halts it",
              _st_rv == 200 and revoked.get("state") == "halted",
              {"status": _st_rv, "body": revoked})
        out = _mcp(base, "fx-trader", tokens.get("fx-trader", ""), "fx.read_rate",
                   {"call_id": "call-t6-revoked-001", "base": "EUR", "symbols": "USD"})
        err = out.get("error", {})
        check("T6: a revoked actor is REFUSED before execution",
              err.get("code") == -32003
              and err.get("data", {}).get("decision") == "revoked"
              and err.get("data", {}).get("executed", False) is False,
              {"code": err.get("code"), "decision": err.get("data", {}).get("decision"),
               "message": err.get("message")})
        check("T6: the revoked call never reached the boundary",
              "call-t6-revoked-001" not in _call_ids(_upstream_log(upstream_log)),
              sorted(_call_ids(_upstream_log(upstream_log))))

        ok = all(c["ok"] for c in CHECKS)
        evidence = {
            "ok": ok,
            "proved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "upstream": {"url": "https://api.frankfurter.dev/v1/latest",
                         "service": "upstream.frankfurter_server", "log": str(upstream_log)},
            "call_ids": {"allowed": allow_id, "denied": deny_id, "held": human_id},
            "upstream_log": rows,
            "checks": CHECKS,
            "failed": [c["check"] for c in CHECKS if not c["ok"]],
        }
        print(json.dumps(evidence, ensure_ascii=False))
        for c in CHECKS:
            print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']}"
                  + (f"  [{c['detail']}]" if c["detail"] is not None else ""))
        if args.evidence:
            target = Path(args.evidence)
            if not target.is_absolute():
                target = REPO_ROOT / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
            print(f"\nevidence written: {target}")
        return 0 if ok else 1
    finally:
        for proc in (plane, upstream):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
