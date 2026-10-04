# PR-14 / Control Room v2 — execution brief for Hermes

## Mission

Turn the current WARRNT frontend from a static demo dashboard into an operator control room.

The current kernel is already stronger than the UI: identity/actor scope, six action classes, signed warrants, TTL/state, policy guards, redact, human decisions, revoke, break-glass, receipts/hash chain, and a real MCP upstream already exist.

Do NOT rewrite the kernel just to make the UI look better.

The target is:

> **Show the operator the decision, not the system internals.**

Core operator object:

`ACTION → WHY → WHO → AUTHORITY → POLICY → DECISION → EXECUTION → PROOF`

## Important repository state

- PR #12 is already merged.
- Current main contains the post-PR-12 mirror pin.
- PR #13 is already occupied by another architecture-documentation change. Do not modify or repurpose PR #13.
- This work therefore uses the next available PR number.
- Use the current Hermes project/agent name from the repository/runtime. Do not hard-code legacy naming.

## Required skill discipline

Before researching, designing, or changing anything, route every specialized term through the corresponding installed/repository skill where one exists.

At minimum, explicitly use the relevant skill for:

- MCP / Model Context Protocol
- OpenAI Agents SDK
- DeepSeek Harness / agent runtime
- microkernel / plugin architecture
- frontend / TypeScript / React
- UX / operator control-room design
- security / authorization / least privilege
- human approval / HITL
- event-driven architecture / SSE or WebSocket
- audit / receipts / cryptographic proof

If a named skill does not exist, say so in the PR comment and use the strongest available equivalent. Do not invent skill names or pretend a skill was executed.

For external technical facts, prefer primary documentation and official repositories.

## Research questions

Research before implementation:

1. How should an agent runtime (OpenAI Agents SDK, DeepSeek Harness, or custom runtime) hand an MCP tool call to an external authorization/enforcement kernel?
2. Which controls belong in the agent runtime and which must remain authoritative in WARRNT?
3. What is the cleanest MCP boundary: agent → MCP client → WARRNT gateway → upstream MCP server?
4. What events are required to make the control decision observable in real time?
5. What should an operator see before, during, and after an action?
6. How should human approval, denial, revoke, break-glass, and proof appear in the UX?
7. Which parts should remain canonical WARRNT contracts rather than becoming frontend-specific concepts?

## Architecture target

Do not make OpenAI Agents SDK or DeepSeek Harness a dependency of the WARRNT kernel.

Target separation:

AGENT RUNTIME
→ OpenAI Agents SDK / DeepSeek Harness / Hermes / custom agent
→ MCP client
→ WARRNT microkernel
→ real MCP upstream

WARRNT remains the enforcement point for:

- identity
- actor scope
- action classification
- warrant
- policy
- human decision
- final decision
- execution boundary
- revoke
- receipt/proof

The agent runtime may reason, plan, discover tools, maintain sessions, and request approval, but it must not be able to bypass WARRNT by calling the upstream directly.

Preserve the canonical decision vocabulary:

`allow | deny | redact | human | revoked`

Preserve warrant lifecycle:

`active | revoked | expired`

Preserve the six action classes:

`observe | read_personal | draft | write_reversible | irreversible | authorize`

Do not introduce a second permission taxonomy merely for UX.

## Control-plane API

Design first, then implement the smallest useful contract.

Prefer explicit resources over making `/api/state` carry everything:

- `GET /api/overview`
- `GET /api/activity`
- `GET /api/actions/pending`
- `GET /api/actions/{id}`
- `GET /api/agents`
- `GET /api/agents/{id}`
- `GET /api/warrants`
- `GET /api/warrants/{id}`
- `GET /api/policies`
- `GET /api/tools`
- `GET /api/breakglass`
- `POST /api/actions/{id}/approve`
- `POST /api/actions/{id}/deny`
- existing revoke semantics
- `GET /api/events` for live activity

Keep `/api/state` for compatibility/debugging unless research proves a better migration path.

The central object should be an Action/ToolCall record with enough information to explain:

- action id
- timestamp
- agent
- actor
- tool
- parameters or safe/redacted representation
- action class
- warrant
- warrant state
- policy result
- decision
- reason
- whether upstream was contacted
- execution result
- receipt/hash
- relevant human intervention state

Never leak personal data into the UI merely to make the demo look richer.

## Event model

A snapshot-only UI is insufficient.

Define a minimal event vocabulary such as:

- `tool_call.pending`
- `tool_call.classified`
- `decision`
- `execution.started`
- `execution.completed`
- `execution.refused`
- `receipt.committed`
- `warrant.revoked`
- `human.required`
- `breakglass.used`

Use SSE first unless research gives a concrete reason to require WebSocket.

The event stream must reflect actual kernel transitions, not simulated frontend state.

## Control Room v2 UX

Replace the current object-first layout:

Agents / Warrants / Kill Switch / Receipts / Six kinds of act

with an action-first operator model.

Primary navigation:

- Command
- Activity
- Authority
- Proof

### Command

If there is a pending decision, show it immediately:

- who
- what tool
- what the action attempts
- relevant data sensitivity
- warrant
- action class
- policy reason
- consequence
- whether upstream has been contacted
- available operator actions

Example mental model:

support-copilot
→ crm.bulk_export
→ 12,000 records
→ email + PESEL
→ W-4419
→ read_personal
→ policy violation
→ DENY
→ upstream never contacted

If nothing requires intervention, show a calm system state rather than a wall of controls:

NO ACTION REQUIRED
3 agents active
28 controlled actions
0 uncontrolled executions
chain integrity verified

### Action Inspector

Every action must be inspectable as:

ACTION
→ WHAT
→ WHO
→ AUTHORITY
→ CLASSIFICATION
→ POLICY
→ DECISION
→ EXECUTION
→ PROOF

### Timeline

Make the enforcement boundary visually obvious:

agent generated call
→ MCP /tools/call
→ WARRNT received it
→ actor identified
→ action classified
→ warrant verified
→ policy evaluated
→ decision
→ upstream contacted OR upstream never contacted
→ receipt committed

The key demonstration is:

> **decision happened before execution**

### Kill switch

Do not present revoke as a permanently dominant button.

Make intervention contextual:

- which agent
- which warrant
- what will stop
- time-to-stop
- current execution state
- resulting receipt

## Risk presentation

Do not change the canonical six-class taxonomy.

If useful, add presentation-only risk signals such as:

- personal data
- bulk operation
- external destination
- irreversible consequence
- unusual volume

These are operator signals, not a second authorization taxonomy.

## Implementation constraints

1. Preserve the WARRNT kernel boundary.
2. Do not import OpenAI Agents SDK or DeepSeek Harness into the kernel.
3. Prefer adapters:
   - `warrnt/adapters/openai_agents.py`
   - `warrnt/adapters/deepseek_harness.py`
   - `warrnt/adapters/generic_mcp.py`
   only if research confirms the abstractions are useful.
4. Keep MCP as transport/protocol boundary.
5. Keep WARRNT as enforcement boundary.
6. Make denied calls provably pre-execution.
7. Make redact visibly distinguishable from allow and deny.
8. Keep receipts append-only and hash chained.
9. Keep mirror consistency with `warrnt`.
10. Add tests before claiming the new flow works.
11. Do not silently change canonical contracts.
12. Do not add dependencies just for visual polish.

## Acceptance criteria

A reviewer should be able to answer all of these from the UI:

- What is happening now?
- Which agent initiated it?
- What tool is being called?
- What authority permits it?
- What action class is it?
- Why was it allowed/denied/redacted/human/revoked?
- Did the upstream actually receive the call?
- What proof was produced?
- What can I do as the human operator?
- Can I follow the complete action timeline?

The demo must visibly prove:

1. allowed call reaches upstream;
2. denied call does not reach upstream;
3. redacted call reaches upstream only after sensitive fields are stripped;
4. irreversible action reaches human decision state;
5. revoke halts the agent/warrant path;
6. receipt/proof follows each terminal outcome.

## Deliverables

Before implementation, add a short research/design note to the PR describing:

- findings from OpenAI Agents SDK
- findings from DeepSeek Harness
- MCP boundary recommendation
- microkernel/adapters decision
- event model
- control-room UX model
- risks / open questions

Then implement the smallest end-to-end vertical slice.

Do not build a large frontend rewrite before the backend action/event contract is proven.

## Final report required from Hermes

In the PR comment, report:

1. skills actually executed;
2. external sources consulted;
3. architecture decision;
4. files changed;
5. tests/checks run;
6. proof that deny happens before upstream execution;
7. proof that redact modifies parameters before upstream;
8. proof that revoke works;
9. remaining gaps;
10. commit SHA(s).

Do not claim a framework capability, security property, or test result unless it was actually verified.
