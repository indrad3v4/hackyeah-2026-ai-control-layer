# TENET — AI Control Layer

> **The agent proposes. TENET decides. Data moves only after authorization.**

TENET is an enforcement resource for agentic systems. It sits between an AI agent and the tools/data the agent can affect, evaluates identity, entitlement, delegation, warrant and policy **before execution**, and records evidence of the decision and downstream result.

**Live Control Room:** https://hackyeah-2026-ai-control-layer-production.up.railway.app/

## The happy path

Watch one real request move through the boundary:

```text
User: "Read the latest EUR/USD reference rate"
        ↓
AI agent proposes: fx.read_rate
        ↓
TENET: identity → entitlement → warrant → policy
        ↓
KERNEL: ALLOW
        ↓
real upstream request
        ↓
result + receipt
```

The Control Room should make five questions obvious:

**What did the agent ask? Why was it allowed? Did data leave? What happened? Where is the proof?**

The model is reasoning evidence, **not authority**. The browser is a control surface, **not authority**.

## Who uses TENET?

**Target end user: a Goldman Sachs-style Technology Risk / AI governance operator.**

TENET is not primarily a dashboard to inspect a kernel. It is a **security resource inside the AI workflow**:

- an agent runtime submits an action to TENET before touching a protected tool or data source;
- TENET applies the firm's policy and scoped authority;
- the operator gets an understandable decision and proof;
- the business function gets the authorized result without giving the model unrestricted power.

This maps directly to the current Goldman direction: its 2026 operating model describes AI adoption alongside stronger risk management, data lineage and auditability; Goldman also says institutional AI products need auditable grounding and outputs traceable to verified sources. Goldman’s Client Security Statement describes firmwide AI governance, least-privilege access and intentionally restricted external LLM use.  
Sources:  
- https://www.goldmansachs.com/investor-relations/financials/8k/2026/8k-01-15-26.pdf
- https://www.goldmansachs.com/insights/goldman-sachs-exchanges/building-ai-systems-for-capital-markets
- https://www.goldmansachs.com/disclosures/client-security-statement.pdf
- https://developer.gs.com/docs/services/transaction-banking/best-practices-api-connect/

**This is a target enterprise use case, not a claim that Goldman Sachs has deployed TENET.**

## Why now?

Agentic AI is moving from experiments into business workflows. Goldman Research says enterprise adoption is shifting toward implementation, while its own operating-model work highlights risk management, process automation, data lineage and auditability.

The security gap is specific:

> A human may be entitled to a resource while a particular agent should not be.

TENET makes that distinction enforceable at the action boundary.

## Security model

```text
User / system
     ↓
Agent proposal
     ↓
TENET Control Plane
     ↓
Enforcement Kernel
     ├─ identity
     ├─ entitlement
     ├─ on-behalf-of / delegation
     ├─ warrant
     └─ policy
     ↓
ALLOW / DENY / REDACT / HUMAN
     ↓
Upstream
     ↓
Receipt + evidence
```

**No entitlement, no data.**  
**No authority, no action.**  
**Denied means no upstream execution through the enforced path.**  
**Unknown stays unknown.**

The evidence chain remains distinct:

`run_id → model_trace_id → proposal_id → action_id → decision_id → upstream_call_id → receipt_id`

An `upstream_call_id` is never relabelled from an `action_id`.

## Why MCP is not enough

MCP provides a standardized transport and authorization framework, but its own specification says implementers must build robust consent and authorization flows and treat tool behavior with caution.

TENET adds the product-level enforcement boundary:

`Agent → proposed action → TENET decision → gated execution → proof`

This is consistent with current agent-authorization work: Google's AP2 explicitly describes tighter constraints for agents than ordinary human authorization and separates delegation from action authorization.

Sources:
- https://github.com/modelcontextprotocol/modelcontextprotocol
- https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/index.mdx
- https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/agent_authorization.md

## Architecture

**MCP = transport/protocol. TENET Enforcement Kernel = authority.**

The model may reason, plan and propose. It cannot authorize itself or bypass the kernel.

Internal `warrnt/*` names remain only where compatibility requires them. The product surface is **TENET**.

## Evidence discipline

- LLM output is never authorization.
- A receipt records evidence; it does not create authority.
- Process success is not proof of upstream contact.
- A denial is a security event.
- Secrets never enter the browser, README, video or public evidence.
- If evidence is missing, TENET says **unknown**.

## Demo

The canonical demo is intentionally one story:

**REQUEST → AGENT → TENET CHECK → ALLOW/DENY → REAL DATA / NO DATA → PROOF**

The final submission video should show the real happy path in ~60 seconds, without terminals, Railway logs, private chats, credentials or development noise.

## Repository

```text
control_plane/   API seam and kernel-backed projections
control_room/    orchestration and provider evidence
node/            pinned internal implementation mirror
index.html       TENET Control Room
tests/           security and contract tests
docs/            architecture and evidence contracts
```

**Project:** https://github.com/indrad3v4/hackyeah-2026-ai-control-layer  
**Enforcement dependency:** https://github.com/indrad3v4/warrnt

## Principles

1. The agent proposes; the kernel decides.
2. User entitlement does not automatically grant agent authority.
3. TENET decides before the upstream call.
4. Human approval is explicit where required.
5. Every decision should leave inspectable evidence.
6. Privacy and least privilege are part of the product, not an afterthought.
