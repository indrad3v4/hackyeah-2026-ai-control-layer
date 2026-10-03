# User journey — ADNOT / WARRNT control layer

## Research question

What does a human actually experience from the moment an AI task is created until the action is executed, refused, redacted, escalated to a human, revoked, or audited — and where does MCP become visible in that journey?

The answer must preserve one invariant:

> **The human decides the authority boundary; the agent proposes actions; MCP carries the tool call; WARRNT decides whether the call may cross the boundary; the receipt proves what happened.**

## Journey map

| Stage | Human / operator | Agent | MCP boundary | WARRNT / policy | Frontend evidence |
|---|---|---|---|---|---|
| 1. Task | Defines the goal and acceptable authority | Receives the task | — | — | Agent + task context |
| 2. Identity | Registers / recognises the actor | Acts under scoped identity | Identity travels with the call | Actor register checks what this actor can never do | **Agents** tile |
| 3. Authority | Grants or approves a bounded warrant | Uses the warrant | — | Warrant has scope, TTL, signature | **Warrants** tile |
| 4. Tool request | Does not need to inspect every routine call | Proposes \`tools/call(name, arguments)\` | **MCP carries the request into the control boundary** | Interception starts before upstream execution | **MCP boundary indicator** + last action |
| 5. Classification | Has already defined the policy; may be asked for a human decision on sensitive classes | Declares intent through the tool call | Exposes tool name + parameters | Stage 4 classifies: \`observe / read_personal / draft / write_reversible / irreversible / authorize\` | **Six kinds of act** strip |
| 6. Decision | Only involved when policy requires \`human\` / \`authorize\` | Waits for the verdict | No upstream call yet | Evaluates actor scope, signed warrant, TTL and parameter policy | **PRE-EXEC / INTERCEPT** state |
| 7a. Allow | — | Receives result | Forwards permitted parameters | \`allow\` | Receipt: allowed |
| 7b. Redact | — | Receives result without protected fields | Forwards rewritten parameters | \`redact\` removes named fields before upstream | Receipt: redacted + fields |
| 7c. Deny | May inspect why | Receives refusal | **Stops at MCP boundary** | \`deny\`; upstream untouched | Receipt: denied |
| 7d. Human | Makes the requested approval decision | Pauses | **Stops at boundary** | \`human\` | Human/escalation state |
| 7e. Revoked | Can press \`/revoke\` | Halts | Subsequent calls are blocked | \`revoked\`; warrant pulled | **Kill switch** + halted agent |
| 7f. Expired | No action required | Cannot use the expired warrant | Call is refused | \`deny\` with \`warrant_state: expired\` | Warrant state: expired |
| 8. Execution | — | Continues only if permitted | Carries the approved call to the upstream MCP tool/server | Records what was actually executed | Last action + receipt |
| 9. Proof | Reviews evidence when needed | — | — | Append-only, hash-chained receipt + anchor | **Proof** tile |
| 10. Audit / intervention | Investigates, verifies chain, or revokes | Continues or remains halted | Boundary remains the control point | \`/verify\`, \`/receipts\`, \`/revoke\` | Footer KPIs + receipts |

## The human's complete loop

**Goal → Authority → Observe → Intercept → Decide → Execute/Refuse → Prove → Intervene**

The important UX distinction is that the human does **not** need to operate MCP directly. MCP is infrastructure. The frontend makes MCP visible only at the point where it matters:

1. **Before execution:** “this tool call is crossing the control boundary”.
2. **At the decision:** “this exact tool + parameter set was evaluated”.
3. **After execution/refusal:** “this is the resulting receipt”.
4. **During intervention:** “this agent can be stopped from the same control surface”.

## How MCP is represented on the frontend

MCP should be shown as a **boundary / transport seam**, not as another permission tile.

Visual model:

~~~text
AGENT
  │
  │ MCP tools/call
  │ tool + arguments
  ▼
┌───────────────────────────────┐
│ WARRNT CONTROL BOUNDARY       │
│ actor → action class →        │
│ warrant → policy → decision   │
└───────────────────────────────┘
  │
  ├── deny / human / revoked ──×  upstream never sees the call
  │
  └── allow / redact ──────────▶  upstream MCP tool/server
                                  │
                                  ▼
                              receipt
~~~

### Frontend mapping

- **Header:** explicit \`MCP /tools/call → WARRNT gate → upstream\` path. This answers “where is MCP?” without pretending that MCP itself is the policy engine.
- **Agents:** who is making the call.
- **Warrants:** what authority the call is carrying.
- **Six kinds of act:** what kind of action is being attempted and who decides.
- **Kill switch:** how a human intervenes in the running chain.
- **Proof:** what actually happened, including deny/redact/revoke outcomes and the hash.
- **Footer:** integrity and operational evidence.

### UX invariant

Never render an MCP call as “allowed because MCP allowed it”.

The correct mental model is:

**MCP transports the request → WARRNT controls the boundary → the upstream tool executes only after the verdict.**

## Demo journey

The deterministic 3:47 scenario should read as one continuous journey:

1. \`support-copilot\` starts with signed warrant \`W-4419\`.
2. It sends an MCP \`tools/call\` for \`crm.read\`.
3. WARRNT evaluates the parameters and records a permitted/redacted read.
4. The same agent requests \`crm.bulk_export\` with \`email\` + \`pesel\`.
5. WARRNT denies the call **before execution**.
6. The operator sees the denial and can inspect the receipt.
7. The operator presses \`/revoke\`.
8. \`W-4419\` becomes revoked and the agent becomes halted.
9. The proof chain records the intervention.

The frontend therefore tells a causal story rather than presenting disconnected dashboards:

**request → boundary → verdict → execution/refusal → proof → intervention.**

## Contract implications

The frontend depends on:

- \`GET /api/state\`
- \`POST /mcp\`
- \`POST /revoke\`
- \`GET /verify\`
- \`GET /receipts\`
- \`GET /actors\`
- \`GET /warrants\`

The \`/api/state.actions\` field is the source of truth for the Stage 4 taxonomy.

The decision vocabulary remains:

\`allow | deny | redact | human | revoked\`

\`expired\` is a warrant state, not a decision.

## Acceptance criteria

- A new viewer can identify the MCP boundary without reading the repository.
- A viewer can distinguish **transport (MCP)** from **control (WARRNT)**.
- Every visible decision can be traced to an agent, warrant, action class and receipt.
- A denied call is visibly pre-execution.
- A redacted call visibly communicates that the call executed with modified parameters.
- \`/revoke\` visibly changes both warrant and agent state.
- The journey is understandable as one causal loop, not five unrelated dashboard widgets.
