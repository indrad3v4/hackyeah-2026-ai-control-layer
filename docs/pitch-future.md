# TENET — the pitch, and what production needs

This is the document to talk from: what TENET is, what is demonstrably true about it today, what a
production deployment must still fix, and the script and answers for a pitch. Everything claimed
here is reproducible from this repository or measured against the live service.

## 1. In one line

**No warrant, no action.** TENET sits between an autonomous agent and the systems it can change:
every action must carry a signed, scoped, expiring warrant, every decision lands in a hash-chained
receipt, and the one control that matters — stopping the agent — is measured, not asserted.

## 2. Why this exists

Agents got the ability to act before they got the ability to be accountable. A model with a tool
call and a credential can move money, export a customer list or change production, and the stack
that surrounds it answers the wrong questions: *who are you* (authentication) and *is this allowed*
(policy). Neither answers **on whose authority, for how long, over which data, and can you show me
afterwards**.

That gap is not a demo problem, it is a regulatory one: an autonomous system's actions have to be
attributable, bounded and reconstructible — after the fact, by someone who does not trust the
system's own word for it. TENET is built around that sentence.

## 3. What is true today, with numbers

| claim | evidence |
|---|---|
| every intercepted call produces a receipt, before execution | `node/` — the receipt is written ahead of the upstream call; a denial writes its reason |
| the chain is tamper-evident and recomputable | `GET /verify` recomputes from genesis; the anchor signs the head |
| stopping an agent is measured, not declared | time-to-stop is computed from the halt to the node refusing that agent's next call |
| positive **and** negative tests per control | 229 test functions across `node/tests` and `tests/` |
| the write path does not degrade with history | 16.0 ms at 10 receipts → 16.2 ms at 5 000 (`scripts/benchmark_scale.py`) |
| reads are the scalability limit, and where | `/api/state` ≈ 10–12 µs per receipt → the console's 1.5 s poll budget is spent at **120 000–150 000 receipts** |
| capacity per node | 59–61 calls/s, four fsyncs on the call path; ~17 processes for 1000 agents at 1 call/s |
| storage | 473 B per receipt → 1 M receipts ≈ 0.47 GB |
| the constraint is documented, not hidden | `docs/complexity-and-scale.md`, `docs/asil-agentic-mapping.md` |

Two of those numbers are worth saying out loud in a pitch, because they are the kind of thing teams
usually do not know about their own system: **the write path is flat, and the read path is not.**

## 4. What the live demo shows — and the one thing to fix before showing anyone

The Control Room's self-check runs four beats: **allow · redact · deny · hold**. Against the
deployed instance right now it reports:

```
allow   fin-reconcile · payments.read      → deny    "warrant W-4417 TTL elapsed"
redact  support-copilot · crm.read         → deny    "warrant W-4419 TTL elapsed"
deny    support-copilot · crm.bulk_export  → deny    ✓
hold    report-bot · crm.bulk_export       → human   ✓
summary {"beats": 4, "distinct_verdicts": 2, "verdicts": ["deny","deny","deny","human"]}
```

The causes are the seed TTLs and nothing else: 900 s for `payments.read`, 420 s for `crm.read` —
both well under an hour, while the journey never renews anything before it runs. So the two beats
that need a *live* permit age out within minutes of a deploy, and the page then shows a beat whose
label ("the call crossed the boundary") sits beside a verdict that says `deny`.

This is the single highest-value fix in the whole list, because it is the artifact a judge clicks:
the system is behaving correctly and the demo is lying about it. Three changes, any one of which
helps, in order of preference:

1. **Renew before the beats.** The journey is a demo; have it re-mint the seed warrants (the issuer
   is already idempotent) before it runs the four.
2. **Give the demo profile longer permits.** TTL is a control — that is exactly what a permissive
   *demo* profile is for, while the strict profile keeps the short ones.
3. **Make a beat that fails say so.** Each beat has a declared expectation; assert it and print
   `expected allow, got deny — the permits have expired` instead of rendering a meaning that
   contradicts the verdict. A demo that cannot fail loudly is worse than one that fails.

## 5. From demo to production — what is reasonable to do

Ordered by value, not by effort.

| # | what | why now |
|---|---|---|
| 1 | **fix the demo's expired permits** (§4) | it is showing a false failure today |
| 2 | **one entry point** — drop the static Pages copy, or give it an API base *and* CORS | right now the Pages URL returns `405` to every POST: a judge who opens it sees a broken product |
| 3 | **the missing half** — semantic channel, control catalogue, budgets (`warrnt#8`) + the ASIL `integrity.floors` gate | requirement 4 says hybrid *must*; half of it is not in the build |
| 4 | **operational hardening, from the project's own red-team findings** — one HMAC key per trust root, an authenticated `/reset`, rate limits and backpressure, a latency SLO, request nonces against replay | every one of these is already written down as CONFIRMED in `docs/roast-journey-*` and none is fixed |
| 5 | **the read path at scale** — incremental chain verdict, segmented verification, paginated export, retention and storage accounting | the console saturates the node at ~150 k receipts; retention is a brief requirement and absent |
| 6 | **productisation** — per-agent identity that is not a bearer token, multi-tenant control plane, policy authoring, SIEM export, an SLA | this is what turns a hackathon submission into something a bank can buy |

Items 1–3 are days, not months. Items 4–5 are the difference between a pilot and a deployment.

## 6. The pitch itself

**The narrative, in four moves.**

1. *Agents act; nobody can say on whose authority.* Show the receipt of a denied export and ask who
   authorised the call that was allowed next to it.
2. *TENET makes authority a first-class object.* A warrant is signed, scoped to parameters, bounded
   in TTL, and carried through every decision. The kernel is the only thing that executes.
3. *And it proves itself.* Hash-chained receipts, an anchor, a recomputable chain, a measured
   time-to-stop — plus the two numbers nobody else has: a flat write path and a documented read
   limit.
4. *This is what regulators are about to require.* Attribution, bounds, and reconstructibility for
   autonomous action.

**The 60-second demo.** Deliberately one story: an intent becomes an action card; the kernel
decides; the boundary is visible (`upstream_contacted`); a receipt appears; the kill switch stops
the agent and the stop is timed. Speak the four beats and the reasons on screen, and — once §4 is
fixed — let the page prove it.

**The four questions to expect, answered honestly.**

| question | answer |
|---|---|
| "What if the model is wrong?" | It never authorises anything. The model is an input to a decision; the kernel decides, and the receipt says which control spoke. |
| "What stops me replaying a leaked token?" | Nothing yet — there is no nonce or idempotency key today. It is on the roadmap at #4, and it is the one finding I would not defend. |
| "Why not just use OPA / Cedar?" | Those answer *is this allowed*. They do not carry authority (who issued it, for how long, over what), and they do not leave a chain you can hand an auditor. TENET sits beside them. |
| "What does it cost to run?" | One node holds ~60 calls/s and 473 B per call; capacity scales by sharding agents, not by scaling a database. |

## 7. Why this team

The differentiator is not the demo, it is the discipline the repository already enforces: a frozen
decision record, a mirror that cannot be hand-edited, receipts before execution, tests for both
polarities of every control, and two documents in which the authors went looking for their own
weaknesses and wrote them down (`docs/roast-journey-gs-2026-10-03.md`). That habit is the thing
that survives contact with production.

## 8. The ask

A pilot with one agent team and one real tool behind the control layer: six weeks, three engineers,
the roadmap in §5 items 1–5. Success is measurable in the terms the customer already uses — every
agent action attributable, every denial explicable, every export reconstructible, and a kill switch
whose latency is printed on the screen.
