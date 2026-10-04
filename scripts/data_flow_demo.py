#!/usr/bin/env python
"""data_flow_demo.py - the paired ALLOW / DENY data-flow scenario, against the REAL app (ACT-6 AC4).

One action, two agents, one tool, two verdicts. The script does not simulate anything and does
not read the page: it raises the real MCP upstream (``upstream.frankfurter_server``) and the real
control plane (``control_plane.app``) as two processes, exactly as ``scripts/t1_upstream_proof.py``
does, then drives the SAME request through ``POST /api/demo/run`` twice:

  * ``fx-trader``       -> holds ``market_data.fx.read`` -> ALLOW  -> ``upstream_contacted: true``;
  * ``support-copilot`` -> holds only ``crm.tickets.read`` -> DENY -> ``upstream_contacted: false``.

The far side proves the deny, not the page: the upstream's OWN access log is read before and after
each run, so ``sent`` may only move for the allow. The allow run performs one real HTTPS call to
``api.frankfurter.dev`` (the machine running this needs outbound network); the deny run performs
none by construction, and the script FAILS if that assumption is ever violated.

It prints the raw JSON the two runs returned - side by side, plus the upstream's own counters -
and exits non-zero if the pair is not a genuine allow-crossing / deny-non-contact pair.

    /root/.local/bin/python scripts/data_flow_demo.py
"""
from __future__ import annotations

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
ADMIN_TOKEN = "act6-data-flow-admin-token"
PY = os.environ.get("TENET_PY", sys.executable)
# The two halves of the pair. ``fx-trader`` is entitled to the FX market (ALLOW); ``support-copilot``
# holds only the CRM right, so the entitlement gate refuses it before execution (DENY).
ALLOW_AGENT = "fx-trader"
DENY_AGENT = "support-copilot"
TOOL = "fx.read_rate"


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
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"nothing listening on {host}:{port} after {timeout}s")


def _wait_health(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = _call(url, timeout=2.0)
        if status == 200:
            return
        time.sleep(0.25)
    raise RuntimeError(f"{url} never answered 200 after {timeout}s")


def _sent(up_port: int) -> int | None:
    """The upstream's OWN counter of calls it was asked to serve (the far side's witness)."""
    status, stats = _call(f"http://127.0.0.1:{up_port}/stats")
    if status == 200 and isinstance(stats, dict):
        return int(stats.get("sent", 0))
    return None


def main() -> int:
    state_dir = Path("/tmp/tenet-act6-data-flow-state")
    upstream_log = Path("/tmp/tenet-act6-data-flow-calls.jsonl")
    upstream_log.unlink(missing_ok=True)

    up_port, cp_port = _free_port(), _free_port()
    env_up = {**os.environ, "FRANKFURTER_LOG": str(upstream_log)}
    env_cp = {**os.environ, "TENET_STATE_DIR": str(state_dir), "WARRNT_ADMIN_TOKEN": ADMIN_TOKEN,
              "WARRNT_DEV": "1", "WARRNT_UPSTREAM": f"http://127.0.0.1:{up_port}/mcp",
              "WARRNT_UPSTREAM_LOG": str(upstream_log)}

    upstream = subprocess.Popen(
        [PY, "-m", "upstream.frankfurter_server", "--port", str(up_port), "--log", str(upstream_log)],
        cwd=str(REPO_ROOT), env=env_up, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    plane = subprocess.Popen(
        [PY, "-m", "uvicorn", "control_plane.app:app", "--host", "127.0.0.1", "--port", str(cp_port)],
        cwd=str(REPO_ROOT), env=env_cp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{cp_port}"

    try:
        try:
            _wait_port("127.0.0.1", up_port)
            _wait_health(f"{base}/health", timeout=90.0)
        except Exception:  # noqa: BLE001 - surface why the rig did not come up
            for name, proc in (("plane", plane), ("upstream", upstream)):
                if proc.poll() is not None:
                    print(f"{name} exited with code {proc.returncode}", file=sys.stderr)
            raise

        # AC7: the LIVE/SIMULATED label comes from this real deployment fact, and it is true here.
        _, overview = _call(f"{base}/api/overview")
        upstream_configured = (overview or {}).get("upstream_configured") \
            if isinstance(overview, dict) else None

        admin = {"x-warrnt-admin": ADMIN_TOKEN}
        sent_before = _sent(up_port)

        # ---- ALLOW: the same request, from the agent that holds the right -------------------
        st_allow, allow = _call(f"{base}/api/demo/run", method="POST",
                                body={"agent": ALLOW_AGENT, "base": "EUR", "symbols": "USD"},
                                headers=admin)
        sent_after_allow = _sent(up_port)

        # ---- DENY: the identical request, from the agent that holds only the CRM right ------
        st_deny, deny = _call(f"{base}/api/demo/run", method="POST",
                              body={"agent": DENY_AGENT, "base": "EUR", "symbols": "USD"},
                              headers=admin)
        sent_after_deny = _sent(up_port)

        _, log = _call(f"{base}/api/upstream/log", headers=admin)
        log_total = (log or {}).get("total") if isinstance(log, dict) else None

        evidence = {
            "scenario": TOOL,
            "upstream": {"url": f"http://127.0.0.1:{up_port}/mcp", "log": str(upstream_log)},
            "upstream_configured": upstream_configured,
            "sent": {"before_allow": sent_before, "after_allow": sent_after_allow,
                     "after_deny": sent_after_deny},
            "upstream_log_total": log_total,
            "allow": {**(allow if isinstance(allow, dict) else {"raw": allow}),
                      "http_status_of_demo_run": st_allow},
            "deny": {**(deny if isinstance(deny, dict) else {"raw": deny}),
                     "http_status_of_demo_run": st_deny},
        }

        allow_ok = (st_allow == 200 and isinstance(allow, dict)
                    and allow.get("decision") == "allow" and allow.get("executed") is True
                    and allow.get("upstream_contacted") is True
                    and bool(allow.get("execution_result", {}).get("http_status")))
        deny_ok = (st_deny == 200 and isinstance(deny, dict)
                   and deny.get("decision") == "deny" and deny.get("executed") is False
                   and deny.get("upstream_contacted") is False
                   and not deny.get("execution_result"))
        far_side_ok = (sent_before is not None and sent_after_allow == sent_before + 1
                       and sent_after_deny == sent_after_allow)
        evidence["ok"] = bool(allow_ok and deny_ok and far_side_ok)

        print(json.dumps(evidence, indent=2, ensure_ascii=False))
        print()
        print("PAIRED DATA-FLOW SCENARIO - " + ("PASS" if evidence["ok"] else "FAIL"))
        print(f"  ALLOW  {ALLOW_AGENT:<15} decision={evidence['allow'].get('decision')!r} "
              f"upstream_contacted={evidence['allow'].get('upstream_contacted')} "
              f"result={json.dumps(evidence['allow'].get('execution_result'))}")
        print(f"  DENY   {DENY_AGENT:<15} decision={evidence['deny'].get('decision')!r} "
              f"upstream_contacted={evidence['deny'].get('upstream_contacted')} "
              f"result={json.dumps(evidence['deny'].get('execution_result'))}")
        print(f"  upstream sent: {sent_before} -> {sent_after_allow} (allow, +1) -> "
              f"{sent_after_deny} (deny, +0)")
        if not far_side_ok:
            print("  the deny run must not move the upstream's own sent counter - this is a FAIL")
        return 0 if evidence["ok"] else 1
    finally:
        for proc in (plane, upstream):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
