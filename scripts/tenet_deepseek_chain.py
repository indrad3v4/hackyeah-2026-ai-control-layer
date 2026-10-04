#!/usr/bin/env python3
"""The ONE canonical chain: real DeepSeek reasons, the TENET kernel decides, the upstream answers.

WHY THIS FILE EXISTS

The jury question is not "does DeepSeek work". It is: *can you see that DeepSeek took part in
the orchestration while the kernel, and not the model, held the authority* - in one trace.

So this driver runs two real scenarios against a running deployment and then reads the chain
back out of the records that already exist (``GET /api/proof/{run_id}``):

    DENY   the model proposes a read of a resource its warrant covers but its entitlement does
           not. The kernel denies it. No byte leaves: ``boundary_attempts == 0``.
    ALLOW  the model proposes a read it is entitled to. The kernel permits it, the real
           Frankfurter tool server answers with an HTTP status, and a receipt is committed.

The assertions below are the acceptance test. They fail if the model is replaced by a mock, a
fixture or a fixture-shaped fallback: a mocked proposal leaves no ``x-ds-trace-id``, no real
token counts and no provider response id, and the driver refuses to call the chain complete.

Usage:  python scripts/tenet_deepseek_chain.py [--base-url http://127.0.0.1:8080] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DENY_TOOL = "equity.read_snapshot"
ALLOW_TOOL = "fx.read_rate"

DENY_QUESTION = (
    "Call propose_action with tool='" + DENY_TOOL + "' and symbols='AAPL', then report the "
    "kernel's verdict for that proposal verbatim: the decision word, the reason, the action_id "
    "and the receipt. Do not propose anything else."
)
ALLOW_QUESTION = (
    "Call propose_action with tool='" + ALLOW_TOOL + "' and base='EUR', symbols='USD', then "
    "report the kernel's verdict for that proposal verbatim: the decision word, the reason, the "
    "action_id, whether the upstream was contacted and the receipt. Do not propose anything else."
)


def _post(url: str, payload: dict, timeout: float = 180.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ask(base_url: str, question: str) -> dict:
    return _post(base_url + "/api/ask", {"q": question})


def proof(base_url: str, run_id: str) -> dict:
    return _get(base_url + "/api/proof/" + run_id)


def run_case(base_url: str, name: str, question: str, tool: str) -> dict:
    """One real run: the model is asked to propose ``tool``; the kernel decides; we read back."""
    answer = ask(base_url, question)
    run_id = str(answer.get("run_id") or "")
    body = proof(base_url, run_id) if run_id else {}
    actions = [a for a in (body.get("actions") or []) if a.get("tool") == tool]
    return {"case": name, "requested_tool": tool, "run_id": run_id,
            "answer": answer, "proof": body, "matching_actions": actions}


def _check(condition: bool, failures: list[str], message: str) -> None:
    if not condition:
        failures.append(message)


def assertions(case: dict) -> tuple[list[str], dict]:
    """The acceptance test of §11, applied to one case. Returns (failures, summary)."""
    failures: list[str] = []
    body = case.get("proof") or {}
    orch = body.get("orchestration") or {}
    action = (case.get("matching_actions") or [{}])[0]
    decision = (action.get("decision") or {}).get("decision")
    execution = action.get("execution") or {}
    receipt = (action.get("receipt") or {}).get("receipt_id")

    _check(orch.get("provider") == "deepseek", failures, "provider is not deepseek")
    _check(orch.get("base_url") == "https://api.deepseek.com", failures, "base_url is not DeepSeek")
    _check(bool(orch.get("llm_request_ids")), failures, "no provider request id was journalled")
    _check(orch.get("model_served") or orch.get("model_requested"), failures, "no model recorded")
    _check(int(orch.get("input_tokens") or 0) + int(orch.get("output_tokens") or 0) > 0,
           failures, "no real token usage: a mocked model leaves this empty")
    _check(int(orch.get("calls_completed") or 0) > 0, failures, "no completed provider call")
    _check(bool(action), failures, "the run produced no action for the requested tool")
    _check(action.get("action_id") == (action.get("action_id") or ""), failures, "no action_id")
    _check(str(action.get("run_id") if action.get("run_id") else case["run_id"]) == case["run_id"],
           failures, "the action is not on this run_id: the chain has two ids where it needs one")
    _check((action.get("decision") or {}).get("decided_by") == "tenet-kernel",
           failures, "the decision was not recorded as the kernel's")
    _check(body.get("llm_authority") is False and body.get("authority_source") == "tenet-kernel",
           failures, "the record does not state that the model holds no authority")

    if case["case"] == "deny":
        _check(decision == "deny", failures, f"expected deny, got {decision!r}")
        _check(int(execution.get("boundary_attempts") or 0) == 0,
               failures, "a denied action still attempted the boundary")
        _check(execution.get("upstream_contacted") is False, failures, "a denied call contacted upstream")
    else:
        _check(decision == "allow", failures, f"expected allow, got {decision!r}")
        _check(int(execution.get("boundary_attempts") or 0) == 1,
               failures, "a permitted call did not attempt the boundary exactly once")
        _check(execution.get("upstream_contacted") is True, failures, "the permitted call never landed")
        _check(bool(receipt), failures, "no receipt was committed for the permitted call")

    summary = {"case": case["case"], "run_id": case["run_id"], "tool": case["requested_tool"],
               "decision": decision, "action_id": action.get("action_id"),
               "receipt_id": receipt, "upstream_contacted": execution.get("upstream_contacted"),
               "boundary_attempts": execution.get("boundary_attempts"),
               "status": body.get("status"),
               "orchestration": {k: orch.get(k) for k in
                                 ("provider", "base_url", "model_requested", "model_served",
                                  "calls_started", "calls_completed", "calls_failed",
                                  "llm_request_ids", "input_tokens", "output_tokens",
                                  "max_latency_ms")},
               "failures": failures}
    return failures, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--out", default="/tmp/tenet-canonical-proof.json")
    ap.add_argument("--attempts", type=int, default=2)
    args = ap.parse_args()

    results = []
    all_failures: list[str] = []
    for name, question, tool in (("deny", DENY_QUESTION, DENY_TOOL),
                                 ("allow", ALLOW_QUESTION, ALLOW_TOOL)):
        case = None
        for attempt in range(args.attempts):
            case = run_case(args.base_url, name, question, tool)
            failures, summary = assertions(case)
            if not failures:
                break
            # A model may decline to call the tool on the first pass. One retry, then the run is
            # reported as it stands - incompleteness is a finding, never something to round up.
            if attempt + 1 < args.attempts:
                time.sleep(1.0)
        failures, summary = assertions(case)
        summary["attempts"] = attempt + 1
        results.append({"run": case, "summary": summary})
        all_failures.extend(f"{name}: {f}" for f in failures)
        print(f"[{name}] decision={summary['decision']} action={summary['action_id']} "
              f"receipt={summary['receipt_id']} contacted={summary['upstream_contacted']} "
              f"attempts={summary['boundary_attempts']} calls={summary['orchestration']['calls_completed']} "
              f"tokens={summary['orchestration']['input_tokens']}/{summary['orchestration']['output_tokens']} "
              f"req_ids={summary['orchestration']['llm_request_ids']}")

    out = {"generated_by": "scripts/tenet_deepseek_chain.py",
           "verdict": "PASS" if not all_failures else "FAIL",
           "failures": all_failures,
           "chain": {"user": {"endpoint": "/api/ask"},
                     "orchestrator": "TENET Orchestrator (openai-agents SDK)",
                     "llm": "DeepSeek via AsyncOpenAI(base_url=https://api.deepseek.com)",
                     "proposal_tool": "propose_action (kernel intercept, model holds no token)",
                     "authority": "TENET Enforcement Kernel",
                     "upstream": "Frankfurter reference-rate tool server",
                     "receipt": "kernel receipt per action"},
           "cases": [r["summary"] for r in results]}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print("VERDICT:", out["verdict"], "->", args.out)
    for f in all_failures:
        print("  FAILURE:", f)
    return 0 if not all_failures else 1


if __name__ == "__main__":
    sys.exit(main())
