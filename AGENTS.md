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

- **Amendment 2 — D13, trace field `decided_by`, 2026-10-04. Reason:** the live-trace composer
  wrote `decided_by: "tenet-kernel"` as a literal for every action, so a hold that a named person
  resolved was reported in the evidence as decided by the kernel — a false attribution in the one
  field that exists to show who decided. Found live: after an operator approved a held action the
  API reported `decided_by: "indradev_"`, the composed trace said `"tenet-kernel"`, and the same
  trace reported the approved call as `contacted: false` because contact was proven from the
  decision label (`allow`/`redact`) rather than from the execution result. **Exact change:** the
  value of the existing field `decided_by` now carries the record's real resolver
  (`"<operator>"`) when the decision came from a human-resolved hold, and stays `"tenet-kernel"`
  where the kernel alone decided; `upstream.contacted` is proven from a recorded execution result
  (a real `http_status`), never from the decision label. No field added, removed or renamed;
  `authority_source` and `llm_authority` unchanged. **Consumers updated:** the code in `ccbcfdd`
  (composer) and the field descriptions in `docs/act-5-live-security-trace-contract.md`, recorded
  here as their own commit per D13. **Unchanged by this amendment:** no verdict, gate,
  entitlement, policy, warrant, SoD or API status-code change; a missing resolver is never
  replaced by an invented name.

- **Amendment 3 — D13, trace fields `state` and `executed`, 2026-10-04. Reason:** the composed
  trace proved the crossing and named the resolver, but carried neither the action's own resolved
  lifecycle state nor a proven execution fact, so the console could not tell "a person is still
  deciding" from "a person approved" or "a person denied". Measured live on `A-0004` (a
  human-approved action): `decision="human"`, `state=null`, `executed=null`,
  `upstream.contacted=true, http_status=200` — and the card printed "Nothing has been sent yet.
  This action is waiting for you." and "What actually happened: Not recorded." while its own
  technical row proved the far side answered. One system contradicting itself about one causal
  event. **Exact change:** two fields added to the composed trace — `state` (the action row's own
  lifecycle state, verbatim, `null` and named in `incomplete` when the row carries none) and
  `executed` (`true` only on a proven execution, `false` when the record proves it did not run,
  `null` and named in `incomplete` when the record does not say). **Consumers updated:** the code
  in `5d3a726` (`control_plane/kernel.py` composer) plus `index.html`
  (`renderActionCard`: the consequence and the outcome line follow the evidence —
  `upstream.contacted`, `state`, `executed` — never the decision label), `scripts/check_console.py`
  (the card check renders the approved and denied shapes), `tests/test_live_trace.py`, and the
  field list in `docs/act-5-live-security-trace-contract.md`; recorded here as their own commit
  per D13. **Unchanged by this amendment:** no verdict, gate, entitlement, policy, warrant, SoD,
  budget or API-shape change; nothing is claimed as executed that the record does not prove.


- **Amendment 4 — D13, `/api/ask` AI execution evidence, 2026-10-04. Reason:** the production Control Room could display a real-looking kernel result beside an ambiguous “no decision” message while the model/resource strip could show zero calls and zero tokens. That conflates three different facts: whether an LLM was invoked, whether the kernel decided an action, and whether the upstream was contacted. **Exact change:** extend the existing `/api/ask` response with one additive `ai` object carrying run-scoped model-call evidence: `answer_origin`, `model_called`, `model_completed`, `model_calls`, `input_tokens`, `output_tokens`, `total_tokens`, `token_status`, `model_requested`, `model_served`, and `trace_id`. Token values are zero only when no model call occurred; when a model call occurred but usage was not reported, token values are `null` and `token_status` is `not_reported`. The response also carries the authoritative `action_id` already present in the route, and the Control Room resolves the action from `/api/live-trace?action_id=...` rather than relying on a pre-run evidence list. **Consumers updated:** `control_room/models.py`, `control_room/agents.py`, `control_plane/app.py`, `index.html`, and tests. **Unchanged:** the kernel remains the only authority; model output never becomes a decision; upstream contact is still proven only by execution evidence.

- **Amendment 5 — D13, `execution_result` fields `value_symbol` and `rates_returned`, 2026-10-04.
  Reason:** the crossing filed `value` but, when the upstream's reply did not carry the symbol
  the caller asked for, the record went silent: diagnostics (endpoint, status, digest) present,
  the rate absent and no field saying why. Found live on `/api/ask`: asked for a rate in a
  currency it did not name, the console could only report "the result block carries no rate" —
  a true sentence that hid a fixable cause (a symbol mismatch), so the tool read as broken when
  it had answered honestly. **Exact change:** two fields added to the action's
  `execution_result` — `value_symbol` (the symbol the upstream's reply states it answered, verbatim)
  and `rates_returned` (the sorted symbols the reply's `rates` object carries). Both come from the
  upstream's own reply; nothing is derived, and a field the reply does not carry stays absent
  (never `null`-invented), so the record shows "the reply carried CHF, USD" instead of silence.
  No field removed or renamed; no verdict, gate, entitlement, policy, warrant, SoD, budget or
  API-shape change. **Consumers updated:** `control_plane/kernel.py` (`_record_crossing`),
  `control_room/agents.py` (the assistant's proven-field list), and
  `tests/test_missing_symbol_is_named.py` (positive and negative), recorded here as their own
  commit per D13. **Unchanged by this amendment:** the kernel remains the only authority; the
  assistant may still quote only what the record carries.

- **Amendment 6 — D13, `execution_result` field `rates`, 2026-10-04. Reason:** measured live on
  `A-0002` (a two-symbol read, `PLN` → `EUR,USD`): the record carried `rates_returned ["EUR","USD"]`
  and no `value`, because a multi-symbol reply has no single value field. So the numbers the
  upstream actually returned existed only inside the model's arithmetic — quotable, unauditable,
  and impossible to re-check from the receipt. The record summarised the table instead of keeping
  it. **Exact change:** one field added to the action's `execution_result` — `rates`, the upstream
  reply's own rates map, verbatim and unrounded, filed only when the reply carries a mapping (a
  reply without one stays silent, never `{}`-invented). No field removed or renamed; `value` and
  `value_symbol` keep their single-symbol meaning. **Consumers updated:** `control_plane/kernel.py`
  (`_record_crossing`), `control_room/agents.py` (the assistant's proven-field list), and
  `tests/test_missing_symbol_is_named.py`, recorded here as their own commit per D13. **Unchanged
  by this amendment:** no verdict, gate, entitlement, policy, warrant, SoD, budget or API-shape
  change; the kernel remains the only authority, and the assistant may still quote only what the
  record carries.
