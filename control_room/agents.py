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
from .provider import bind_sdk, build_provider, key_present, provider_status

try:  # the SDK is required for the live path but must not break import in a bare checkout
    from agents import Agent, Runner, function_tool
except Exception:  # noqa: BLE001
    Agent = Runner = function_tool = None

# Where the specialist tools read kernel state from. Defaults to the control plane itself:
# in the app the tools run in-process against the same kernel; in the proof script the app is
# already serving on this URL. Either way the facts come from the kernel, not from the model.
CONTROL_PLANE_URL = os.environ.get("TENET_CONTROL_PLANE_URL", "http://127.0.0.1:8080").rstrip("/")

SPECIALISTS = ["governance_agent", "kernel_agent", "control_plane_agent"]

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
                      "the TENET Enforcement Kernel decides."),
        tools=tools,
        model=model,
    )


def provider_state() -> dict[str, Any]:
    return {**provider_status(), "available": build_provider() is not None}


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
            evidence=evidence, specialists=[], run_id=run_id, next_action="retry when provider available")
    try:
        result = await Runner.run(orchestrator, user_text)
        text = str(result.final_output)
    except Exception as exc:  # noqa: BLE001 - a provider failure degrades, never crashes
        return ControlAnswer(
            answer=(f"Refusal: the provider call failed ({type(exc).__name__}). "
                    f"No answer was synthesized and nothing was authorized; the kernel record "
                    f"is attached as evidence."),
            evidence=evidence, specialists=[], run_id=run_id, next_action="retry when provider available")
    return ControlAnswer(answer=text, evidence=evidence, specialists=list(SPECIALISTS),
                         run_id=run_id)


