#!/usr/bin/env python
"""The six questions of the merge gate, asked of the live node, with the record as the answer.

Starts the node from node/ (the mirror), replays the same seven decisions the evidence run
makes, then asks Hermes Control the gate's questions. Every answer is written down with the
fields it used; a question the record cannot answer is recorded as such, not guessed.

    python3 scripts/ask_evidence.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "node"))

import uvicorn                                    # noqa: E402
from warrnt.api import create_app                 # noqa: E402
from warrnt.config import Settings                # noqa: E402

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "ask-evidence"
HOME = pathlib.Path("/tmp/tenet-ask-evidence")

QUESTIONS = [
    "What is happening?",
    "Why was A-0003 denied?",
    "Which action is waiting for me?",
    "What happened to A-0004?",
    "Did A-0005 reach upstream?",
    "Show me the receipt.",
]


def http(path: str, method: str = "GET", body: dict | None = None, admin: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if admin:
        req.add_header("x-warrnt-admin", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def agent_call(agent: str, tool: str, args: dict, run: str) -> dict:
    token = next(a["token"] for a in http("/agents")[1] if a["id"] == agent)
    data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(BASE + "/mcp", data=data, method="POST")
    for k, v in (("Content-Type", "application/json"), ("x-warrnt-agent", agent),
                 ("x-warrnt-token", token), ("x-warrnt-run", run)):
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def start_node():
    HOME.mkdir(parents=True, exist_ok=True)
    for name in ("receipts.jsonl", "anchors.jsonl"):
        p = HOME / name
        if p.exists():
            p.unlink()
    settings = Settings(home=HOME, registry_path=HOME / "receipts.jsonl",
                        key_path=HOME / "issuer.key", anchor_path=HOME / "anchors.jsonl",
                        upstream_url="", host="127.0.0.1", port=PORT, dev=True, admin_token=TOKEN)
    server = uvicorn.Server(uvicorn.Config(create_app(settings=settings), host="127.0.0.1",
                                          port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            if http("/health")[0] == 200:
                return server
        except Exception:                                        # noqa: BLE001
            pass
        time.sleep(0.1)
    raise SystemExit("node did not come up")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    args = ap.parse_args()
    server = start_node()
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "questions": []}
    try:
        # the seven decisions the gate names (same shape as the evidence run)
        ids = {}
        ids["allow"] = (agent_call("fin-reconcile", "payments.read", {"table": "payments", "rows": 1240}, "run-fin-1")
                        .get("result", {}).get("structuredContent", {}) or {})
        ids["redact"] = agent_call("support-copilot", "crm.read", {"table": "tickets", "fields": ["subject", "email", "pesel"]}, "run-support-2")
        ids["deny"] = agent_call("support-copilot", "crm.bulk_export", {"table": "customers", "fields": ["email", "pesel"]}, "run-support-3")
        ids["hold"] = agent_call("deploy-agent", "infra.deploy", {"target": "prod"}, "run-deploy-4")
        for key in ("redact", "deny", "hold"):
            ids[key] = ((ids[key].get("error", {}).get("data") or {}) .get("action_id")
                        or (ids[key].get("result", {}).get("structuredContent") or {}).get("action_id"))
        a4 = ids["hold"]
        if a4:
            http(f"/api/actions/{a4}/approve", "POST", {"by": "Indra"}, admin=True)
        ids["deny2"] = ((agent_call("report-bot", "crm.bulk_export", {"table": "customers", "fields": ["email"]}, "run-report-5")
                         .get("error", {}).get("data") or {}).get("action_id"))
        if ids["deny2"]:
            http(f"/api/actions/{ids['deny2']}/deny", "POST", {"by": "Indra"}, admin=True)
        revoked = agent_call("deploy-agent", "infra.deploy", {"target": "prod"}, "run-deploy-6")
        ids["revoke"] = (revoked.get("error", {}).get("data") or {}).get("action_id")
        http("/revoke", "POST", {"agent": "deploy-agent"}, admin=True)

        for q in QUESTIONS:
            code, ans = http("/api/ask", "POST", {"q": q})
            out["questions"].append({"q": q, "http": code, "answer": ans.get("answer", ""),
                                     "grounded": ans.get("grounded"), "evidence": ans.get("evidence")})
            print(f"Q: {q}\n  A: {ans.get('answer','')}\n  grounded={ans.get('grounded')} ev={json.dumps(ans.get('evidence'))}\n")

        # correlation: one action_id across API, state and receipt
        if ids["hold"]:
            _, one = http(f"/api/actions/{ids['hold']}")
            _, st = http("/api/state")
            inlog = [a for a in st.get("action_log", []) if a["action_id"] == ids["hold"]]
            print("correlation", json.dumps({"action_id": one["action_id"], "decision": one["decision"],
                                             "state": one["state"], "upstream_contacted": one["upstream_contacted"],
                                             "receipt": one["receipt"], "in_state_log": bool(inlog),
                                             "same_in_deeper": bool(inlog and inlog[0]["receipt"] == one["receipt"])}))
            out["correlation"] = {"action_id": one["action_id"], "decision": one["decision"], "state": one["state"],
                                  "upstream_contacted": one["upstream_contacted"], "receipt": one["receipt"],
                                  "in_state_log": bool(inlog),
                                  "same_receipt_as_state": bool(inlog and inlog[0]["receipt"] == one["receipt"])}
        out["action_ids"] = ids
        _, health = http("/health")
        out["chain"] = health["chain"]
    finally:
        server.should_exit = True
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(out, indent=2))
        print("wrote", args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
