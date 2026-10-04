# ASIL, adapted to agentic systems

Automotive safety uses **ASIL** (Automotive Safety Integrity Level, ISO 26262): a level from
**QM** (ordinary quality management) through **A, B, C, D** assigned to a function by
`Severity × Exposure × Controllability`. The level then dictates how much rigour the function
needs — redundancy, independence, evidence, diagnostic coverage.

This document adapts that idea to autonomous agents and to this control layer. It is a design
instrument, not a certificate: nothing here claims an agent can be "ASIL D certified". What it
gives us is a principled way to answer the question a bank actually asks — *how much control
does this particular action deserve?* — instead of applying the same rules to reading a table
and moving money.

## 1. The three factors, translated

| ISO 26262 factor | Questions in a car | Questions for an agent | Where this project already measures it |
|---|---|---|---|
| **Severity** | How bad is the harm if it fails? | What is the blast radius of the act — reversible? money? personal data out of the perimeter? production down? | the **act classes**: `observe`, `draft`, `read_personal`, `write_reversible`, `irreversible`, `authorize` |
| **Exposure** | How often is the situation encountered? | How often does the agent act, under how broad a warrant, and with how much of a person in the loop? | warrant TTL and scope, `per_agent`/`per_tool` ceilings, the operator's revocation record |
| **Controllability** | Can the driver still react? | Can a person stop it, how fast, and can they undo it? | **time-to-stop** (`status.last_stop`, measured from the halt to the node refusing the agent's next call), the human hold, break-glass, `/revoke` |

The useful consequence: an agent with a narrow warrant, a short TTL, a person watching, and an
undoable act needs far less machinery than an unattended nightly job with a bulk-egress warrant.

## 2. Default level per act class

The class is a **floor**, and context may raise it (never lower it — D5: a class may raise the
decision, never lower it). Bulk, external destination, and personal data each raise the level.

| Act class | Default | Rationale |
|---|---|---|
| `observe` | **QM** | read-only, nothing changed |
| `draft` | **QM→A** | produces an artefact that changes nothing outside the boundary |
| `read_personal` | **A** | disclosure of personal data is the harm; scale and destination raise it |
| `write_reversible` | **B** | wrong but undoable |
| `irreversible` | **C** | cannot be undone: money moved, data deleted, a document filed |
| `authorize` | **D** | changes the rules themselves — a warrant, a limit, a regulation |

Raisers to apply on top of the class, all of which this project already detects:

- **bulk** (rows/volume above the order's threshold) → +1
- **egress** (destination outside the perimeter, or a URL in the content) → +1
- **personal data present in the payload** → at least A, +1 if combined with egress
- **unattended** (no human in the loop for the run) → +1
- **shared warrant** (one order covering several agents) → +1

## 3. What each level requires of the control layer

Requirements are expressed against the controls this project actually has, so the table is
checkable rather than aspirational.

| Level | Gate requirements | Evidence owed | Test obligation (D10) |
|---|---|---|---|
| **QM** | receipts only; the order is still checked | receipt row | smoke |
| **A** | + deterministic content checks (secrets, personal data) at `block`; budget enforced | receipt with the control that decided | positive + negative |
| **B** | + actor scope and order policy at `block`; redaction allowed instead of refusal | + action record, redaction list | positive + negative + a redaction case |
| **C** | + the **semantic channel** enabled and fail-closed; human hold for exceptions; break-glass with a required postmortem | + both channel verdicts on the record | + a case where the channels disagree |
| **D** | + a **person decides** (no machine allow); the class floor is not liftable by break-glass; anchor recomputed and independently verified; both channels must agree | + signed anchor, verification output | + a test that the floor cannot be lifted, and one that a single channel is not enough |

## 4. ASIL decomposition is why the hybrid defence exists

ISO 26262 allows *decomposition*: an ASIL D requirement may be met by two sufficiently
**independent** channels each carrying ASIL B(D). The agentic reading is exactly requirement 4 of
the brief:

```
   deterministic channel          semantic channel
   (patterns, scope, budget)      (local model scoring intent)
              \                     /
               \                   /
                -> both must allow -> the act proceeds
                -> either refuses  -> the act does not proceed (fail-closed)
                -> either silent   -> refuse, never pass (silence is not agreement)
```

Two conditions make decomposition real rather than decorative, and both are testable:

1. **Independence.** The channels must not share a failure mode. A pattern library and a model
   have genuinely different blind spots (a pattern cannot read intent; a model can be talked out
   of one), which is why they compose. Independence is *broken* when both are fed by the same
   pre-processed, already-truncated payload, or when one key signs everything.
2. **No single channel may be sufficient above its level.** If the semantic channel is
   unavailable for an ASIL C act, the act is refused — "I could not check" is not "I checked".

## 5. Freedom from interference

ASIL also requires that a lower-integrity function must not corrupt a higher one. For agents that
means: one agent's compromise must not become another's authority. This project does that with
per-agent tokens bound to per-agent warrants, per-agent budgets and per-agent halt state — but a
review of this codebase already found the sharpest counter-example: **one HMAC key serves four
different trust roots** (order issuance, the anchor, break-glass, and the operator token). One
leak therefore compromises every root at once, which is precisely the coupling that decomposition
is supposed to prevent. Key separation per trust root is the fix, and it is still open.

## 6. Diagnostic coverage and safe state

- **Safe state** here is *deny*, and the pipeline is fail-closed end to end: an unhandled control
  error becomes a refusal, not a pass; a halted agent is refused before any gate runs.
- **Diagnostic coverage** is the receipt chain, the anchor, `/verify`, and the gate suite
  (`console_check`, `security_boundaries`, `verify_live`, `first_demo_path`). What is missing is
  *continuous* diagnosis at scale: the chain verdict is recomputed on every read, so it cannot be
  polled at high receipt counts (see `complexity-and-scale.md`).

## 7. Honest state of play in this submission

| Requirement of this document | Status |
|---|---|
| act classes as a severity proxy | **present** (`actions.py`, the class table) |
| time-to-stop as a controllability measure | **present and measured on the record** |
| budgets as exposure limits | **designed (D7); enforced only in the node PR that is still open** |
| deterministic channel | **present** |
| semantic channel (needed from level C up) | **absent from the delivered node** — implemented in an unmerged pull request |
| independence of the two channels | **not demonstrable today**: the semantic channel is not in the build |
| key separation per trust root | **absent** (one key, four roots) |
| integrity level carried on the warrant | **absent** — see below |

### The one concrete change this document asks for

Carry the level explicitly instead of leaving it implicit in prose. Concretely:

```yaml
# in the control catalog
integrity:
  floors:            # act class -> minimum level that may not be lowered
    observe: QM
    read_personal: A
    write_reversible: B
    irreversible: C
    authorize: D
  raisers:           # context that raises the level
    bulk: 1
    egress: 1
    personal_data: 1
    unattended: 1
```

A gate reads the act class, applies the raisers, and refuses when the controls required at that
level are not enabled (`off`/`monitor` where the level demands `block`). That converts this
document from a policy statement into an enforced one, and it is the same catalog the rest of the
control layer already reads — no new mechanism.

## 8. What this buys, in one sentence

A reviewer can take any intercepted action, read its class and context, and answer *"was this
treated as seriously as it deserved?"* — which is the question ASIL exists to make answerable,
and the question a control layer that applies one rule to every action cannot answer.
