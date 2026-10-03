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

## D13 closure — frozen decision vocabulary and live state contract

The D13 vocabulary gap identified during Stage 4 is now closed in the runtime dependency `indrad3v4/warrnt`, merged from PR #2 on 2026-10-03.

- Receipt decisions are exactly: `allow | deny | redact | human | revoked`.
- Warrant lifecycle states are exactly: `active | revoked | expired`.
- An expired warrant is refused as `deny` with `warrant_state: expired`; `expired` is never a receipt decision.
- `redact` is executable: personal fields named by the rule are stripped before the upstream call, and the receipt records the redaction.
- `GET /api/state` exposes the Stage 4 `actions` taxonomy consumed by the console. This is an explicit D13 contract extension documented in README.

The old Pre-Lint findings remain useful as historical review context; they are no longer open implementation gaps.
