# Stage 4 — the taxonomy of action classes, step by step

Stage 4 of the method (*adapt the model to the task*) is a list of gaps, then the closure of
one gap per turn, then the plan. This document is the step-by-step record: what the gap was,
what was built, and how a reader verifies it without trusting this text.

## Step 4.1 — the list of gaps (closed before this document existed)

Counted from the partner brief and from what the layer could already do:

| # | Gap | Status after this stage |
|---|---|---|
| 1 | **The register of actors** — who is asking: which *kind* of actor, and what that kind may never do, whatever the user's rights are | **closed** — `warrnt/actors.py`, `GET /actors`, 4 classes, one gate between identity and the order. Merged in the node's `master`. |
| 2 | **The taxonomy of action classes** — what kind of *act* is this, and who decides it | **closed by this stage** — `warrnt/actions.py`, `GET /state → actions`, 6 classes. |
| 3 | **Break-glass with a term** — a time-boxed, recorded emergency route with a named human | **open** — next stage. Nothing in the node pretends it exists. |

## Step 4.2 — the adaptation: six classes, five rungs of authority

The warrant answers *was this call authorised*. The register answers *may this kind of actor
stand at the gate*. The taxonomy answers the question an auditor asks **before both**:
*what kind of act is this, and who is allowed to decide it.*

| Class | What it is | Who decides | Tools on this node |
|---|---|---|---|
| `observe` | read-only, nothing personal, nothing changed | the node decides | `infra.plan` |
| `read_personal` | reads personal data; the fields read are recorded | the node decides · fields on the record | `payments.read`, `crm.read`, `crm.bulk_export` |
| `draft` | produces an artifact that changes nothing outside the boundary | the node decides | — (reserved) |
| `write_reversible` | changes external state in a way that can be undone | the node decides under a signed order | `crm.update` |
| `irreversible` | cannot be undone: money moves, data is deleted, a document is filed | **a person decides — the machine prepares only** | `payments.transfer`, `infra.deploy` |
| `authorize` | changes the rules themselves: a warrant, a limit, a registration | **the operator-human only — no machine may** | `warrant.issue`, `warrant.revoke`, `policy.edit` |

Two rules turn the table into enforcement:

1. **An unclassified act is refused.** A layer that cannot say what kind of act it is looking
   at does not let it through. The refusal names the missing classification
   (`no action class for this tool · the layer refuses what it cannot classify`).
2. **A class can only raise a decision, never lower it.** The order, its guards and the register
   may all say `allow`; if the act is `irreversible`, the answer the node gives is `human` —
   `REQUIRE-HUMAN`: pause, do not execute. Whatever a warrant says, it does not talk an
   irreversible act back down to a machine decision. A denial stays a denial, a revocation stays
   a revocation: raising means moving up the ladder, never overwriting the reason.

### The consequence we did not hide

`payments.transfer` used to come back `allow` when it was inside the signed limit. It now comes
back **`human`**. The two tests that asserted the old answer were rewritten to assert the new
one — and the allow path of the demo moved to `payments.read`, which is what a finance agent
should be allowed to do unattended. A control layer whose honest answer is *a person decides
this* is worth more than one that lets a machine move 42 000 PLN because a signature was
attached to a limit.

### Where it sits in the chain

```
identity → actor class → action class → order → policy on parameters → brake → receipt
```

The receipt — the hash-chained record — carries the class in its reason
(`... · class irreversible · the machine prepares, a person decides`), so the classification is
auditable per call, not only visible in the console.

## Step 4.3 — the plan (next, in order)

1. **Break-glass with a term.** A named human, a reason, a clock: an emergency route that is
   allowed, time-boxed, and recorded as its own decision kind with an expiry. The frozen
   vocabulary is changed first if it cannot express it (rule D13).
2. **The intent plane.** Our node sees calls; the five-plane reference architecture
   (see `architecture-variants.md`, variant 5) adjudicates *intent* against a composite
   principal. That is the next layer, and it is not claimed as built.
3. **Aggregate view.** Naming the limit the per-call design cannot reach: locally compliant,
   collectively discriminatory (variant 6). A slide, not a subsystem, at this size.

## How to verify this document (no trust required)

```bash
git clone https://github.com/indrad3v4/warrnt && cd warrnt
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
make test                              # 75 passed
.venv/bin/python -m pytest tests/test_actions.py -q   # 15 passed
make console-check                             # 35 checks, non-zero on failure
.venv/bin/python scripts/upstream_check.py     # 18/18 in front of the real MCP server
```

- `warrnt/actions.py` — the taxonomy: classes, the decider ladder, the escalation rules.
- `tests/test_actions.py` — 15 tests, including the pinned one-page ladder and the proof that a
  class never lowers a decision.
- `tests/test_api.py::test_transfer_within_limit_still_needs_a_person` — the behaviour change,
  asserted with the upstream call counter as evidence that nothing ran.
- `tests/test_actors.py::test_a_valid_warrant_does_not_widen_an_actor_class` — the register's
  half: the same agent, the same signed warrant, the same parameters; only the actor class
  changes, and the answer flips.

This document describes the accept path rule D12 demands: everything above ran; nothing above
is designed-only except where it says so.


## Reconciliation with the locked form (a recorded unfreeze, in the D13 sense)

`docs/concept-form-and-name.md` (the locked concept) names the second load-bearing part as
"an action taxonomy — **destructive / irreversible / outbound / read**, each with a *type*, not a
flag". The enforcement taxonomy implemented here has six classes. That is a change to a locked
part, so it is recorded rather than presented as if the lock always said this:

```json
{
  "reason": "the locked four-type list cannot express two acts the fleet actually performs: "
            "changing the rules themselves (granting a warrant, editing policy) and acting "
            "without changing anything outside the perimeter (a draft). Nor can it separate "
            "reads that touch personal fields from reads that do not, which is where the "
            "receipt's 'redact' vocabulary has to live.",
  "exact change": "four types -> six classes (observe, read_personal, draft, write_reversible, "
                  "irreversible, authorize) + one cross-cutting field (boundary: does data leave "
                  "the perimeter), not a seventh class.",
  "consumers updated": "warrnt/actions.py (the classes), warrnt/proxy.py (the gate), README chain "
                       "line, /state['actions'], tests/test_actions.py, and the receipt reason "
                       "(the receipt now names the class next to the decision)."
}
```

Mapping, so nothing from the locked list is silently dropped:

| Locked type | Where it went | Why |
|---|---|---|
| `read` | `observe` + `read_personal` | the split is decided by *fields named in the call* (PESEL, email, balances), not by intent — the cheap deterministic half of D4 |
| `destructive` | the harmful subset of `irreversible` | "destructive" names the harm; "irreversible" names the property that decides who may act (cannot be undone). The class gate keys on the property |
| `irreversible` | `irreversible` | kept verbatim as a class name |
| `outbound` | a **field** on the call (`boundary`), not a class | crossing the boundary cuts across `draft`, `write_reversible` and `irreversible`. Recorded honestly: if outbound must gate independently of the class, it becomes a seventh class and this table is updated first |
| — | `draft` | the locked list had no slot for "produced something, changed nothing outside" |
| — | `authorize` | the locked list had no slot for "changed the rules themselves"; the machine is refused outright here |

## Recorded gaps found by Prelint (2026-10-03) — the contract, not hidden

Prelint's review of this PR caught two places where the documents and the shipped node disagree
about the **frozen decision vocabulary**. Both are real; both are recorded here instead of being
edited away, because D13 says a control that cannot be expressed in the vocabulary means the
vocabulary is incomplete.

1. **`redact` was in the contract and not in the code.** README's `/api/state` contract lists
   receipt decisions as `allow|deny|redact|human|revoked`, and the README records that the freeze
   was lifted exactly once to add `redact`. The shipped `Decision` enum
   (`warrnt/models.py`) had `allow, deny, human, revoked, expired` — **no `redact`**.
2. **`expired` was a decision in the code and a warrant state in the contract.** The code returned
   `Decision.expired` when a TTL had elapsed; the contract names `expired` only in
   `warrants[].state` (`active|revoked|expired`).

### Closed, in one commit of its own (D13: an unfreeze is its own change)

Both are fixed in `warrnt` on `feat/action-classes`, commit **`8df6658`** *"contract: implement
redact, keep expired out of the decision space (D13 unfreeze)"* — the contract wins over the code,
because the contract is what a consumer was told:

* **`redact` is implemented, not merely declared.** `Rule.redact` names the params that carry
  field lists; personal fields found there are **stripped from the payload before the upstream is
  called** (`policy.strip_pii`), the call still runs, and the receipt records `decision: redact`
  plus the names removed. `inspect_pii` refuses the act; `redact` lets the act happen without the
  data. Proof, end to end: `tests/test_api.py::test_a_read_naming_a_personal_field_is_stripped_and_still_runs`
  asserts the upstream payload is `fields: ["subject"]` while the caller asked for
  `["subject", "email"]`, and that the executor counter still moved.
* **`expired` left the decision space.** An elapsed TTL is refused as `deny` (`-32001`) whose
  detail carries `warrant_state: expired`; the code no longer has a sixth decision, and
  `tests/test_policy.py::test_an_expired_order_is_refused_as_a_deny_carrying_the_state` asserts
  `"expired" not in {d.value for d in Decision}`.

The frozen five-value space is now literally true of the node. The suite that says so, on this
commit: **80 pytest**, `console_check` **35/35**, `upstream_check` **18/18**,
`security_boundaries` **29/29** (its boundary check was updated to the class truth: exactly at the
limit the guard holds *and* the class lifts the call to `require-human`), `verify_live` **20/20**.

Consequence, stated plainly: a consumer implementing against the contract will not see `redact`
from this node, and will see `expired` where the contract promised a warrant state. The next
contract commit is therefore an unfreeze of its own (per D13): either implement `redact` as a
decision, or remove it from the contract; and either move `expired` out of the decision space
into the warrant state, or add it to the contract. Until that commit lands, this document states
the gap rather than the aspiration.
