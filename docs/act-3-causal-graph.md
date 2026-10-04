# ACT-3 · The causal graph, and why it is not an authority chain

The chain is evidence. The decision is authority. They are joined by correlation, never by identity.
Collapsing them - one id doing every job - reads as "the model proposed it, so the kernel executed
it". That is the one thing this system cannot say.

## What the ids mean, and what each one is allowed to prove

| id | answers | may prove | may NOT prove |
|---|---|---|---|
| `run_id` | which agent run this belongs to | correlation across one run | authority, execution |
| `model_trace_id` (`x-ds-trace-id`) | that THIS request reached the model | the provider really answered | that anything was authorised |
| `proposal_id` (`P-...`) | what the model proposed | intent, and its untrusted origin | that an action exists |
| `action_id` (`A-...`) | which action TENET examined | the unit of enforcement | that execution happened |
| `decision_id` (`D-...`) | what the kernel decided, and on what | authority: allow/deny/redact/human/revoked | that upstream answered |
| `upstream_call_id` (`U-...`) | which real contact left the boundary | that the boundary was crossed, once per attempt | that it was permitted |
| `receipt_id` (`R-...`) | the recorded outcome | what the record says happened | authority (it is a record, not a permission) |

    run_id
      |- model_trace_id
      |- proposal_id
      |    \- action_id
      |         \- decision_id          <- authority lives here, and only here
      |              |- upstream_call_id (0..n - one action may try more than once)
      |              \- receipt_id

**`authority = kernel.decision`** - never `authority = trace`. A proposal is untrusted input; a
receipt is a record. Neither grants anything.

## Rules that follow, and the code must hold them

1. **Do not use `action_id` as `upstream_call_id`.** One action may produce zero, one, or several
   attempts (retry after a timeout is the normal case). The upstream call is minted at the moment
   the request leaves the boundary and is stamped into what the upstream itself logs.
2. **Do not let the model's output become an action.** The proposal is stored as a proposal; the
   kernel mints the action when it takes the proposal under enforcement.
3. **`decision_id` is minted by the kernel per decision**, and it is the id a jury should be pointed
   at when asked "who allowed this". The kernel's answer must be the same with or without a model
   in the loop.
4. **Absence is a result.** A denial with `boundary_attempts = 0` and no `upstream_call_id` is the
   proof of non-contact - not a missing field.
5. **A partial chain is `INCOMPLETE`, with the missing node named.** Never rounded up to PASS.

## What the current tree does, and what has to change

- `/api/proof/{run_id}` today returns a flat record: it filters actions by `run_id` and reports the
  decision and the crossing. It must become the graph above: `proposal_id` and `decision_id` are
  missing nodes, and `upstream_call_id` does not exist at all.
- The kernel stamps no `decision_id`. A decision is currently identified only by its action.
- The upstream call carries no id of its own: `call_id` arrives empty and the mirror does not mint
  one. Stamping `action_id` there is wrong by rule 1 and must not be merged.
- The Control Room tells the story to a person in four moves: **what the agent wanted to do** ·
  **why TENET allowed or stopped it** (actor, action class, warrant, policy, decision) · **what
  actually happened** (upstream, call, HTTP, data) · **what proves it** (model trace, action,
  decision, upstream call, receipt). One sentence under it: *The model proposed. TENET decided. The
  upstream executed.*

## The gate

PASS only when the frozen commit contains a reproducible artifact proving, for one real run:
real model request -> proposal -> action -> kernel decision -> upstream contact or non-contact ->
receipt, with the barrier intact. Live success is not the gate; the frozen commit is.
