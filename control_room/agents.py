from __future__ import annotations
import json
import os
import uuid
from typing import Any
import httpx
from .models import ControlAnswer, Evidence

try:
    from agents import Agent, Runner, function_tool
except ImportError:
    Agent = Runner = function_tool = None

API_BASE = os.getenv("WARRNT_CONTROL_API", "http://127.0.0.1:8000").rstrip("/")

async def _state() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(f"{API_BASE}/api/state")
        response.raise_for_status()
        return response.json()

async def _grounded_snapshot() -> list[Evidence]:
    try:
        state = await _state()
    except Exception as exc:
        return [Evidence(source="control-plane", claim="live kernel state unavailable", value=str(exc))]
    evidence: list[Evidence] = []
    for key in ("agents", "warrants", "receipts", "actions"):
        value = state.get(key)
        if value is not None:
            evidence.append(Evidence(source="/api/state", claim=key, value=len(value) if isinstance(value, list) else json.dumps(value)[:1200]))
    return evidence

if function_tool:
    @function_tool
    async def governance_inspect() -> str:
        return json.dumps([e.model_dump() for e in await _grounded_snapshot()])
    @function_tool
    async def kernel_inspect() -> str:
        return json.dumps([e.model_dump() for e in await _grounded_snapshot()])
    @function_tool
    async def control_plane_inspect() -> str:
        return json.dumps([e.model_dump() for e in await _grounded_snapshot()])
else:
    governance_inspect = kernel_inspect = control_plane_inspect = None

def _agent(name: str, instructions: str, tool: Any):
    if not Agent:
        return None
    return Agent(name=name, instructions=instructions, tools=[tool] if tool else [])

def build_agents():
    return (
        _agent("Governance Agent", "Explain canonical contracts and terminology. Never invent authority.", governance_inspect),
        _agent("Kernel Agent", "Explain actor, action class, warrant, policy, decision, execution and receipt from evidence. The TENET kernel is authoritative.", kernel_inspect),
        _agent("Control-Plane Agent", "Explain current actions, activity, intervention, revoke and proof. Operator commands still pass the kernel.", control_plane_inspect),
    )

async def answer(user_text: str) -> ControlAnswer:
    run_id = str(uuid.uuid4())
    governance, kernel, control = build_agents()
    evidence = await _grounded_snapshot()
    if not Runner or not all((governance, kernel, control)) or not os.getenv("OPENAI_API_KEY"):
        return ControlAnswer(answer="Live agent runtime is not configured; this answer is limited to observed kernel evidence.", evidence=evidence, run_id=run_id)
    orchestrator = Agent(
        name="Hermes Control Orchestrator",
        instructions="Answer only from specialist evidence. Never claim authorization or execution. The TENET kernel is the authority.",
        tools=[
            governance.as_tool(tool_name="governance_agent", tool_description="Inspect governance contracts."),
            kernel.as_tool(tool_name="kernel_agent", tool_description="Inspect decisions, warrants and execution evidence."),
            control.as_tool(tool_name="control_plane_agent", tool_description="Inspect activity, intervention and proof."),
        ],
    )
    result = await Runner.run(orchestrator, user_text)
    return ControlAnswer(answer=str(result.final_output), evidence=evidence, specialists=["governance_agent", "kernel_agent", "control_plane_agent"], run_id=run_id)
