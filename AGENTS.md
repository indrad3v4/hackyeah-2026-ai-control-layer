# AGENTS.md — frozen decisions for this repository

Prelint enforces these on every pull request. A PR that contradicts a decision below must
either change the decision here first, or be reworked. Decisions are numbered so a review
comment can cite them.

## Scope

- **D1 — This repository is the Goldman Sachs Partner Task `AI Control Layer`.**
  `main` carries the deliverable. Anything that is not part of that deliverable does not
  belong on `main`.
- **D2 — Prelint integration lives on the `prelint` branch only.** Tooling for code review
  must never become a runtime dependency of the control layer itself.

## Architecture

- **D3 — One control catalog is the single source of truth.** Controls, sensitivity
  thresholds (block vs redact vs adherence %), the list of permitted models, and
  resource/financial budgets all live in one config source. No control may be hardcoded
  anywhere else; if a rule cannot be expressed in the catalog, the catalog is wrong.
- **D4 — Hybrid enforcement order is fixed: deterministic first, semantic second.**
  Pattern checks (PII, secrets, authentication, permitted-model checks) run before any
  model call. The semantic layer (a local model) is invoked only on what the deterministic
  layer passed, so a cheap filter is never paid for with a model call.
- **D5 — Enforcement happens before execution, never after.** The decision
  (allow / deny / redact / human / revoked — the full receipt vocabulary) is produced before the intercepted call runs.
  A denial is itself a recordable event.
- **D6 — Everything on the enforcement path runs on local models.** No paid API is available
  or permitted on the critical path: the layer that classifies the action, scopes the actor,
  holds warrant state, applies policy and reaches the decision never depends on it. Pattern
  checks run before any model call, and the semantic layer targets a locally served model
  (Ollama). A cloud model may never be a requirement for the kernel to function.
  *Amended 2026-10-03 — see Amendment 1. The agentic assistance surface, which holds no
  authority, may call a paid provider; the enforcement path may not.*

## Governance

- **D7 — Budgets are a control, not a report.** Token, cost and compute-time limits are
  enforced at request time, per agent and per model; exceeding a limit blocks the call and
  the block is recorded. A budget that is only displayed is not implemented.
- **D8 — Historical attack signatures arrive from outside the codebase.** Signatures for
  known exploits (malicious code execution, unsafe deserialization, supply-chain attacks on
  model repositories) are consumed from an externally managed feed so the layer can be
  updated without a redeploy.
- **D9 — Config changes take effect in real time.** An operator may edit the catalog while
  the layer is running and the next request must already respect the change; no restart is
  required to see new rules, removed controls or changed thresholds.

## Evidence

- **D10 — The test suite is a deliverable, not an afterthought.** It ships runnable and
  contains both positive (allowed) and negative (blocked or redacted) cases, including
  budget limits and exploit mitigation. A control without both a positive and a negative
  test is incomplete.
- **D11 — Every decision is exportable.** Audit records for security teams and metrics for
  management are produced in an exportable form, not only rendered in a UI.
- **D12 — Nothing is claimed as working that was not executed.** The README separates what
  runs today from what is designed, and the split is maintained as the code grows.

- **D13 — The contract is frozen, but not immutable.** A frozen interface changes only by
  an explicit, recorded unfreeze: the reason, the exact field added or removed, and the
  matching update in every consumer. The unfreeze is a commit of its own. A control that
  cannot be expressed in the receipt vocabulary means the vocabulary is incomplete — fix
  the vocabulary first, then add the control.

## Amendments — recorded unfreezes (D13)

- **Amendment 1 — D6, 2026-10-03. Reason:** the operator brief for the AI Control Layer task
  requires a real model call on the agentic surface (orchestrator + governance / kernel /
  control-plane specialists), and no locally served model is reachable from the deployment
  target. **Exact change:** D6's scope narrowed from "everything" to "the enforcement path" —
  the decision path keeps the local-only constraint, the assistance surface is explicitly
  permitted a paid provider (DeepSeek, `https://api.deepseek.com`). **Consumers updated in
  this commit or the ones that follow it:** `AGENTS.md`, `control_room/agents.py` (provider
  seam), `control_room/provider.py` (new), `requirements-control-room.txt`, `README.md`,
  `docs/tenet-live-contract.md`, `ci.yml` (must assert the enforcement path imports no paid
  provider). **Unchanged by this amendment:** no model output is ever an authorization
  decision; the kernel's verdict is the only execution boundary; a missing key degrades the
  assistance surface to DEMO and never the enforcement path.
