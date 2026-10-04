"""The agentic assistance surface: TENET Orchestrator + three specialists.

Exactly four agents (contract TASK.4): the orchestrator plus Governance, Kernel and
Control-Plane specialists used as tools. Every specialist answer is grounded in a kernel
call - a tool result - never in model invention. The orchestrator only routes and phrases;
it never authorizes.

This module holds no authority (AGENTS.md D6, Amendment 1). It may call the paid provider;
the enforcement path may not. A missing key degrades the whole surface to DEGRADED and never
touches the kernel's decision path.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

from .models import ControlAnswer, Evidence
from .provider import (bind_sdk, build_provider, current_run_id, key_present, provider_status,
                        read_events, set_run_id, summarize_events)

try:  # the SDK is required for the live path but must not break import in a bare checkout
    from agents import Agent, Runner, function_tool
except Exception:  # noqa: BLE001
    Agent = Runner = function_tool = None

# Where the specialist tools read kernel state from. Defaults to the control plane itself:
# in the app the tools run in-process against the same kernel; in the proof script the app is
# already serving on this URL. Either way the facts come from the kernel, not from the model.
CONTROL_PLANE_URL = os.environ.get("TENET_CONTROL_PLANE_URL", "http://127.0.0.1:8080").rstrip("/")

SPECIALISTS = ["governance_agent", "kernel_agent", "control_plane_agent"]

# The action a run itself created, by run id. A run that proposed a call is about THAT call,
# and the record sent to the caller must name it - not the state the run read before proposing.
_RUN_ACTIONS: dict[str, str] = {}


def action_for_run(run_id: str) -> str:
    """The action id this run itself created, or "" when the run created none."""
    return _RUN_ACTIONS.get(str(run_id or ""), "")

# The agent whose live warrant carries the orchestrator's proposals. It is read from the
# kernel's own registry inside this process - the token the kernel issued for it is used here
# and never becomes part of a tool argument, a tool result or the model's context. A caller may
# point the proposal at another enforced agent by name; there is no default that bypasses the
# registry.
PROPOSAL_AGENT_ENV = "TENET_PROPOSAL_AGENT"

# Set by the control plane at startup (``control_plane.app``): the very kernel this process
# serves. When present, the specialist tools and the evidence floor read it **in-process** - no
# HTTP hop, no second decision path, no chance of reading another instance's state. The URL
# above is only the fallback for a process that has no kernel of its own (the proof script).
_KERNEL: Any = None


def bind_kernel(kernel: Any) -> None:
    """Bind the in-process kernel the tools should read. Called once by the control plane."""
    global _KERNEL
    _KERNEL = kernel


def _read(path: str) -> Any:
    """Read the kernel-backed state behind ``path``; honestly report a failure, never invent it.

    In-process first (the app binds its own kernel), HTTP second (a detached caller such as the
    live-proof script). Both routes read the SAME mirrored kernel - the reads are not decisions.
    """
    if _KERNEL is not None:
        try:
            return _KERNEL.read(path)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}", "path": path, "via": "kernel"}
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{CONTROL_PLANE_URL}{path}")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001 - an empty result is the honest answer
        return {"error": f"{type(exc).__name__}: {exc}", "path": path, "via": "http"}


def _ev(source: str, claim: str, value: Any) -> Evidence:
    if isinstance(value, (str, bool, int, float)) or value is None:
        v: Any = value
    else:
        v = json.dumps(value, default=str)[:1200]
    return Evidence(source=source, claim=claim, value=v)


def _tool(fn):
    """Wrap a function as an SDK tool, or return ``None`` when the SDK is unavailable."""
    return function_tool(fn) if function_tool else None


def _governance_inspect(system: str = "overview") -> str:
    """Governance: the authority picture - warrants, agents, action classes, chain."""
    data = _read("/api/overview")
    return json.dumps({"system": system, "authority": data.get("authority", {}),
                       "counts": data.get("counts", {}), "chain": data.get("chain", {})},
                      default=str)


def _kernel_inspect(action_id: str = "") -> str:
    """Kernel: the decision record itself - one action, or the newest decisions."""
    if action_id:
        data = _read(f"/api/actions/{action_id}")
    else:
        data = _read("/api/actions?limit=5")
    return json.dumps({"action_id": action_id, "record": data}, default=str)


def _control_plane_inspect(question: str = "") -> str:
    """Control-Plane: what is happening now - pending holds, activity, agents."""
    return json.dumps({"question": question, "pending": _read("/api/actions/pending"),
                       "activity": _read("/api/activity?limit=10")}, default=str)


def _propose_action(tool: str, base: str = "EUR", symbols: str = "USD",
                    rationale: str = "") -> str:
    """Submit a proposal to the kernel. The model chooses what to ask for; the kernel decides.

    This is the orchestrator's ONE write-shaped tool and it writes nothing itself: it calls the
    kernel's own :meth:`Kernel.intercept` - the same entry point ``/mcp`` and ``/api/demo/run``
    use - with the run id this answer is serving, and returns the verdict with the ids the
    kernel produced. A denial is a result, not an error: the caller is told what the kernel
    said, in the kernel's own words.

    The agent token comes from the kernel's registry in this process. It is not an argument,
    so the model can neither choose it nor read it back.
    """
    if _KERNEL is None:
        return json.dumps({"submitted": False, "authority": "tenet-kernel",
                           "error": "no kernel is bound in this process; the proposal was not "
                                    "submitted and nothing was decided here"})
    agent_id = os.environ.get(PROPOSAL_AGENT_ENV, "").strip() or "fx-trader"
    try:
        tokens = {str(x.get("id")): str(x.get("token") or "") for x in _KERNEL.agents(dev=True)}
    except Exception as exc:  # noqa: BLE001 - a read failure is reported, never papered over
        return json.dumps({"submitted": False, "authority": "tenet-kernel",
                           "error": f"{type(exc).__name__}: {exc}"})
    token = tokens.get(agent_id, "")
    if not token:
        return json.dumps({"submitted": False, "agent": agent_id, "authority": "tenet-kernel",
                           "error": "no live warrant for this agent in this deployment"})
    run_id = current_run_id() or ""
    try:
        decision, reason, detail, receipt, executed = _KERNEL.intercept(
            agent_id, token, tool, {"base": base, "symbols": symbols}, run_id=run_id)
    except Exception as exc:  # noqa: BLE001 - the kernel's refusal is the answer, not a crash
        return json.dumps({"submitted": True, "agent": agent_id, "tool": tool, "run_id": run_id,
                           "authority": "tenet-kernel", "decision": "deny",
                           "error": f"{type(exc).__name__}: {exc}"})
    word = decision.value if hasattr(decision, "value") else str(decision)
    detail = detail if isinstance(detail, dict) else {}
    action_id = str(detail.get("action_id") or (detail.get("action") or {}).get("id") or "")
    if run_id and action_id:
        _RUN_ACTIONS[run_id] = action_id
    record = _KERNEL.action(action_id) if action_id else None
    record = record if isinstance(record, dict) else {}
    crossing = record.get("execution_result") or {}
    # "Contacted" means the upstream answered with a status. A permitted call whose transport
    # failed leaves none, and claiming a crossing anyway is the one thing this product forbids.
    contacted = bool(crossing.get("http_status")) and word in ("allow", "redact")
    # The proven consequence travels with the verdict. An allowed call that reached the far
    # side must be able to answer the user's own question - "what is the rate" ends in a number,
    # not in "the kernel approved the read". Only fields the record itself carries are copied:
    # nothing is derived, completed by hand or invented when the record is silent.
    proven = ({k: crossing[k] for k in ("outcome", "http_status", "value", "value_symbol",
                                        "rates_returned", "rows", "endpoint",
                                        "latency_ms", "response_sha256") if k in crossing}
              if contacted else {})
    return json.dumps({"submitted": True, "proposed_by": "deepseek", "authority": "tenet-kernel",
                       "llm_authority": False, "agent": agent_id, "tool": tool,
                       "resource": str(detail.get("resource") or ""), "run_id": run_id,
                       "action_id": action_id, "decision": word, "reason": reason,
                       "executed": bool(executed), "upstream_contacted": contacted,
                       "receipt": record.get("receipt") or (receipt or {}).get("id"),
                       "rationale": rationale, "result": proven}, default=str)


def build_specialists(model: Any = None) -> tuple[Any, Any, Any]:
    """The three specialists, each grounded in its own kernel-backed tool."""
    if not Agent:
        return None, None, None
    governance = Agent(
        name="Governance Agent",
        instructions=("Explain authority, warrants, action classes and chain integrity strictly "
                      "from the governance_inspect tool result. Never invent authority, never "
                      "grant it: the TENET Enforcement Kernel is the only authority."),
        tools=[t for t in (_tool(_governance_inspect),) if t],
        model=model,
    )
    kernel = Agent(
        name="Kernel Agent",
        instructions=("Explain actor, action class, warrant, policy, decision, execution and "
                      "receipt strictly from the kernel_inspect tool result. Quote only ids the "
                      "tool returned; if it returned none, say the record holds none."),
        tools=[t for t in (_tool(_kernel_inspect),) if t],
        model=model,
    )
    control = Agent(
        name="Control-Plane Agent",
        instructions=("Explain what is happening now - pending human holds, recent activity, "
                      "agent state - strictly from the control_plane_inspect tool result. "
                      "Operator commands still pass the kernel; you never authorize."),
        tools=[t for t in (_tool(_control_plane_inspect),) if t],
        model=model,
    )
    return governance, kernel, control


def build_orchestrator(specialists: tuple[Any, Any, Any], model: Any = None) -> Any:
    """TENET Orchestrator: routes to the three specialists (used as tools). It decides nothing."""
    if not Agent:
        return None
    governance, kernel, control = specialists
    tools = []
    # The proposal tool is the orchestrator's, not a specialist's: routing stays read-only, and
    # the one path that asks the kernel for a decision is the one the model drives directly -
    # with the kernel, never the model, producing the verdict.
    proposal = _tool(_propose_action)
    if proposal:
        tools.append(proposal)
    if governance:
        tools.append(governance.as_tool(
            tool_name="governance_agent",
            tool_description="Inspect authority: warrants, action classes, chain integrity."))
    if kernel:
        tools.append(kernel.as_tool(
            tool_name="kernel_agent",
            tool_description="Inspect a decision: action id, decision, receipt, upstream contact."))
    if control:
        tools.append(control.as_tool(
            tool_name="control_plane_agent",
            tool_description="Inspect current state: pending holds, recent activity, agent state."))
    return Agent(
        name="TENET Orchestrator",
        instructions=("Answer the operator only from what the specialist tools returned. Cite "
                      "the real ids in the evidence; never invent an action, decision, receipt "
                      "or upstream contact. You never authorize and you cannot allow anything - "
                      "the TENET Enforcement Kernel decides. To ask for a read you may call "
                      "propose_action with a tool id from the live set (fx.read_rate, "
                      "equity.read_snapshot) and report the kernel's verdict verbatim, "
                      "including a denial; never describe an action as allowed, denied or "
                      "executed unless that tool result says so. When the verdict is allow and "
                      "the tool result carries a 'result' block, ANSWER THE OPERATOR'S OWN "
                      "QUESTION with the value recorded there (for a rate read: the rate and "
                      "the receipt that proves it) - an answer that refuses while the value "
                      "sits in the result is a failed answer. Never state a value the 'result' "
                      "Every question gets a mapping, never a lecture. When the operator asks "
                      "something that is not itself a rate or a snapshot read, take this order: "
                      "(1) name the measurable part of their question in one line; (2) propose the "
                      "closest registered action for it - to convert an amount of money that is "
                      "fx.read_rate - and report the kernel's verdict; (3) if their question also "
                      "needs an action class that is not registered (a plan, a stream, a budget), "
                      "name that missing class in one line as a fact about the registry; (4) never "
                      "answer with a statement about how narrow your world is. A refusal that only "
                      "explains your own limits is a failed answer; a mapping is the answer."),
        tools=tools,
        model=model,
    )


def provider_state() -> dict[str, Any]:
    return {**provider_status(), "available": build_provider() is not None}



def _ai_usage(result: Any = None, run_id: str = "") -> dict[str, Any]:
    """Return run-scoped model evidence, preferring Agents SDK runtime usage."""
    sdk_usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    sdk_requests = getattr(sdk_usage, "requests", None)
    sdk_input = getattr(sdk_usage, "input_tokens", None)
    sdk_output = getattr(sdk_usage, "output_tokens", None)
    sdk_total = getattr(sdk_usage, "total_tokens", None)
    try:
        events = read_events(run_id)
    except Exception:
        events = []
    persisted = summarize_events(events)
    model_calls = int(sdk_requests) if sdk_requests is not None else int(persisted["model_calls"])
    model_called = model_calls > 0 or bool(persisted["model_called"])
    model_completed = bool(persisted["model_completed"]) or (result is not None and model_calls > 0)
    if model_calls == 0:
        input_tokens = output_tokens = total_tokens = 0
        token_status = "not_applicable"
    elif sdk_input is not None and sdk_output is not None and sdk_total is not None:
        input_tokens, output_tokens, total_tokens = int(sdk_input), int(sdk_output), int(sdk_total)
        token_status = "reported"
    elif persisted["token_status"] == "reported":
        input_tokens, output_tokens, total_tokens = persisted["input_tokens"], persisted["output_tokens"], persisted["total_tokens"]
        token_status = "reported"
    else:
        input_tokens = output_tokens = total_tokens = None
        token_status = "not_reported"
    trace_id = persisted.get("trace_id")
    if not trace_id and result is not None:
        for response in reversed(getattr(result, "raw_responses", []) or []):
            trace_id = getattr(response, "request_id", None) or trace_id
            if trace_id:
                break
    return {
        "model_called": model_called,
        "model_completed": model_completed,
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "token_status": token_status,
        "model_requested": provider_status().get("model", "deepseek"),
        "model_served": persisted.get("model_served"),
        "trace_id": trace_id,
    }

def _evidence_from_records() -> list[Evidence]:
    """Kernel facts with real ids, read straight from the control plane's own kernel reads.

    This is the evidence floor for every answer: even if the orchestrator phrases nothing,
    the caller still gets the records the answer is about - with real action/warrant/receipt
    ids, or an explicit admission that the record is empty.
    """
    evidence: list[Evidence] = []
    overview = _read("/api/overview")
    if isinstance(overview, dict) and "error" not in overview:
        evidence.append(_ev("/api/overview", "counts", overview.get("counts", {})))
    actions = _read("/api/actions?limit=5")
    rows = actions.get("actions", []) if isinstance(actions, dict) else []
    if not rows:
        evidence.append(Evidence(source="/api/actions", claim="record",
                                 value="no action in the record", action_id=None))
    for a in rows[:5]:
        e = _ev("/api/actions", "decision", {
            "action_id": a.get("action_id"), "agent": a.get("agent"), "tool": a.get("tool"),
            "decision": a.get("decision"), "receipt": a.get("receipt"),
            "upstream_contacted": a.get("upstream_contacted")})
        e.action_id = a.get("action_id")
        evidence.append(e)
    return evidence


async def answer(user_text: str, *, run_id: str | None = None) -> ControlAnswer:
    """Run the real orchestrator, or degrade to a refusal that still grounds in the record.

    The provider is built explicitly here (DeepSeek, base_url https://api.deepseek.com). When
    it is unavailable the answer is a refusal carrying the kernel evidence - never an invented
    answer and never an allow.
    """
    run_id = run_id or str(uuid.uuid4())
    # Stamp the run BEFORE the client is built: the client's transport is wired to the run id
    # at construction, and every event it journals must carry this answer's run.
    set_run_id(run_id)
    evidence = _evidence_from_records()
    provider = build_provider()
    model = bind_sdk(provider) if provider else None
    specialists = build_specialists(model)
    orchestrator = build_orchestrator(specialists, model)
    if not Runner or not provider or not model or not orchestrator:
        reason = ("provider key ABSENT" if not key_present()
                  else "provider client unavailable")
        if not Runner:
            reason = "openai-agents SDK unavailable"
        return ControlAnswer(
            answer=(f"Refusal: the agentic surface is DEGRADED ({reason}). "
                    f"No model call was made. The kernel record is attached as evidence and "
                    f"remains the only authority - nothing was authorized by this answer."),
            evidence=evidence, specialists=[], run_id=run_id, next_action="retry when provider available",
            ai={**_ai_usage(None, run_id), "answer_origin": "refusal"})
    try:
        result = await Runner.run(orchestrator, user_text)
        text = str(result.final_output)
    except Exception as exc:  # noqa: BLE001 - a provider failure degrades, never crashes
        return ControlAnswer(
            answer=(f"Refusal: the provider call failed ({type(exc).__name__}). "
                    f"No answer was synthesized and nothing was authorized; the kernel record "
                    f"is attached as evidence."),
            evidence=evidence, specialists=[], run_id=run_id, next_action="retry when provider available",
            ai={**_ai_usage(None, run_id), "answer_origin": "provider_failure"})
    ai = _ai_usage(result, run_id)
    ai["answer_origin"] = "model" if ai["model_called"] and ai["model_completed"] else "provider_failure"
    return ControlAnswer(answer=text, evidence=evidence, specialists=list(SPECIALISTS),
                         run_id=run_id, ai=ai)


