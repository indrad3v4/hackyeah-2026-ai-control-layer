# Concept lock — the form, and the name

Stage 3 of the 7-stage route (divergence → convergence). This file records **what we
decided, why, and what we rejected** — so the choice can be audited later without
re-reading the whole thread.

## 1. The five tests the form must pass

Taken from the brief's own language, not invented:

| # | Test | The brief's question |
|---|---|---|
| T1 | **Agent-level restriction** | can the layer stop *this agent* even when the *user* has the right? |
| T2 | **Data entitlement** | are entitlements a separate, hard gate (not a copy of user permissions)? |
| T3 | **Proof of delegation** | is "on behalf of the user" **proven**, or merely asserted? |
| T4 | **Stream + judge** | does it judge a *stream of actions* before execution, rather than report after? |
| T5 | **Destructive is a class** | is destructiveness a taxonomy, or a single boolean flag? |

## 2. Fifteen hypotheses, one form

Fifteen candidate forms were generated across three axes — *role in the relationship*
(surety / witness / key / mandate / wall) × *carrier* (gateway / CLI / MCP / policy file)
× *material of truth* (signature / log / paper / config / pause) — and each was scored
0–2 against T1–T5 plus a durability test (does it outlive the system and the person?).

Winner, 12/12: **the witness at the boundary** — an in-line control plane that answers,
for every single step, one question:

> may **this agent** perform **this action** with **these parameters**, on behalf of
> **this user**, **right now**?

Its five load-bearing parts, each closing one test:

1. **A registry of actors** — humans, autonomous systems, chatbots, MCP suppliers (T1).
2. **An action taxonomy** — six enforceable action classes (`observe`, `read_personal`, `draft`,
   `write_reversible`, `irreversible`, `authorize`) plus the cross-cutting `boundary` field (T5).
3. **Proof of delegation** — a short-lived, per-task token, not session trust (T3).
4. **A separate entitlement gate** — entitlements as the source of truth (T2).
5. **An append-only decision record** plus a **break-glass** override with automatic
   expiry (T4, and the operational part everyone under-invests in).

Rejected, and why — the failing test is named for each:

| Rejected | Score | Why |
|---|---|---|
| Key + config | 5/12 | static: says nothing about delegation (T3 = 0) |
| Pause + CLI | 6/12 | no entitlement path (T2 = 0) |
| Surety + signature | 8/12 | proves delegation, but arrives *after* the action (T4 = 1) |
| Witness + public log | 9/12 | strong on proof, weak on acting *before* the fact |
| Mandate + MCP server | 10/12 | strong, but the judge lives inside one protocol surface |
| Wall + stream/judge | 10/12 | no proof of *who* authorised (T3 = 1) |

## 3. The two canon tests

**The idea tree.** Trunk: *the witness at the boundary*. Branches: registry, taxonomy,
delegation proof, entitlement gate, record + break-glass. Every branch needs the trunk to
make sense, and the trunk without branches is a slogan — the mark of a real form.

**Social screening.** The form survives a change of model vendor, a change of protocol
version, and a change of owner: the record outlives the owner, the rule outlives the
framework. Known weak spot, stated rather than hidden: an immutably *public* record would
be feared, so it stays "paper on request", not permanent publication.

## 4. Why this is not the mainstream answer

The 2026 market sells policy-enforcement gateways: registry + policies + logs. The
differentiator here is not the presence of a judge — everyone has one — but that the
**verdict must explain itself in human language *before* execution, and leave paper for
every "no"**. Vendors that decide out-of-band state the problem themselves: alerting is
not a control, because the log arrives after the table is gone.

## 5. The name: TENET

Set by the founder on 2026-10-03, replacing ADNOT.

*tenet* — Latin, third person of *tenēre*, "to hold": **the order holds the action**. It is also
the palindrome at the centre of the **Sator Square** — the oldest word square known (Pompeii,
before AD 79) — reading identically in both directions, which is exactly what the record must do:
a rewrite has to show. The name it replaced, **ADNOT** — *adnotare*, "to note down", in Roman law
an *adnotatio* was the note that gave a document its force — was dropped by the founder's
decision, not for a defect: it was the cleanest name on the board (zero marks, free domains) and
it stays on the record as a spare.

| Check (2026-10-03) | TENET | ADNOT (kept for reference) |
|---|---|---|
| `.dev` / `.io` / `.ai` | `.dev`, `.io` free (no DNS record); `.ai` taken (44.232.173.249) | all three free (no DNS) |
| npm / PyPI | taken / taken (HTTP 200) | 404 / 404 |
| US trademark registry | **crowded — not clearable**: USPTO 99151322 "TENET" (American Sports Licensing, live), TENET TECHNOLOGIES (filed 2000), Tenet Apps FZCO | **0 results** for "adnot" |
| Live product with this name | Tenet Healthcare, the 2020 film, Tenet Apps | none in AI or security (only surnames and a small Indian dev firm) |

Honest reading: TENET names the **idea** here and in the pitch. It is not a product mark — a
product or a domain carrying it would need its own clearance, or one of the spares (ADNOT,
PRAES).

Rejected finalists, with the reason kept on the record:

- **TESTIS** — legally clean, but *testis* is the anatomical term in English; the
  registry confirms it (the only marks were class-5 remedies "for disorders of male
  organs"). Reputationally dead.
- **SURETY · WARDEN · VERDICT · ATTEST** — live class 9/42 trademarks, including
  "Warden AI" and an assurance-software vendor a banking jury may know.
- **VOWEN · SIGLUM** — live companies (a voice-to-text AI; Siglum Labs Ltd).
- **ADNOT** — the Stage-3 name, dropped 2026-10-03 by the founder's decision; still the cleanest
  on the board (zero marks, `adnot.dev` / `.io` / `.ai` free, not on npm or PyPI) — the spare.
- **PRAES** — clean and legally the most precise ("the one who answers for another"),
  kept as the reserve name; on the ear it reads as "prays".

## 6. What this locks, and what it does not

Locked: the form (witness at the boundary), the core (Form · Drama · Benefit), the name.
Not locked: implementation, mechanism and demo subject — that is stage 4.


## D13 reconciliation — Stage 4 taxonomy unfreeze

Stage 4 formally changed the action taxonomy named in this locked concept. This is an explicit unfreeze, not a silent reinterpretation of the original lock.

- Previous locked taxonomy: `destructive / irreversible / outbound / read`.
- Canonical Stage 4 taxonomy: `observe / read_personal / draft / write_reversible / irreversible / authorize`.
- Cross-cutting field: `boundary = internal | outbound`; `outbound` is not an action class.
- Migration: `read` → `observe + read_personal`; `destructive` → the harmful subset of `irreversible`; `irreversible` remains `irreversible`; `outbound` → `boundary`.
- New classes: `draft` and `authorize` represent acts the original four-type list could not express.

The runtime implementation and Stage 4 consumers now use the canonical six-class taxonomy.
