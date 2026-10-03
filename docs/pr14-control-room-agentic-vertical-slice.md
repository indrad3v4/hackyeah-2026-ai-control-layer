# PR-14 — agentic control-room vertical slice

## Architecture

The runtime is intentionally three specialists plus one user-facing orchestrator, not one agent per PR.

USER → Hermes Control Orchestrator → Governance Agent / Kernel Agent / Control-Plane Agent → evidence → USER + Reflex UI

WARRNT remains the authority. The agents only inspect, explain and prepare control-plane work. A model output is never an authorization decision.

## API/UI boundary

Reflex is the Python control-room surface. It consumes the same control-plane state as the agents; it is not an authorization layer. The current repository exposes the existing state endpoint, so the first vertical slice uses that endpoint as the compatibility/debug source while the explicit Action/Event API is introduced later.

Reflex state and event handlers execute on the server side, keeping API access out of browser code. The UI displays the orchestrator response together with evidence references and a run correlation identifier.

## Agent runtime boundary

OpenAI Agents SDK is optional at import time and becomes active when its package and an API key are configured. The orchestrator uses agents-as-tools so one user-facing agent retains conversation control. This matches the SDK orchestration model.

The WARRNT kernel does not import the SDK. MCP remains the transport/protocol seam; WARRNT remains the enforcement seam.

## Honest scope

This commit does not claim that the full Action/Event API, live event stream, human approval endpoint, or revoke command path is complete. Those require live kernel/API integration and must be implemented against the actual WARRNT runtime rather than simulated in the frontend.

## Verification target

1. Open Reflex Control Room.
2. Ask a question.
3. With the SDK configured, the orchestrator invokes the three specialists as tools.
4. Specialist tools read the existing WARRNT state endpoint as evidence.
5. The response carries evidence and a run identifier.
6. No model output is treated as a WARRNT decision.
