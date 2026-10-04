# ACT-7 — Current to target: the console as a decision tool

Companion to `docs/act-7-product-diagnosis.md`. Same scope (`/root/work/tenet-live-trace`, HEAD
`be5e947`), same rules: docs only, no code changed, no server started, nothing committed. Design
bias: **80% human decision / 20% technical proof**; the primary object of the screen is the
**ACTION**.

Read with `docs/design-references.md` (Grafana, Stripe Radar, Linear, Vercel, CloudTrail, IAM Access
Analyzer, Cerbos, Permit.io, Sigstore Rekor, Tailscale) — this document does not restate those; it
adds the decision/approval-interface references collected for Act 7 at the end.

---

## 1. Current-to-target map

Each row: what is true today (verified), the target state, and **the backend that already carries the
target** — so no row requires a control whose endpoint does not exist.

| # | Current (verified) | Target | Existing backend that carries it | Cost |
|---|---|---|---|---|
| 1 | 0 `<input>` / `<textarea>` in `index.html` (242 lines); the only action control is the fixed "Run the paired allow / deny scenario" button (`index.html:102,240`) | One intent box at the top: the user's own AI-domain problem | `POST /api/ask` (`app.py:801`, docstring: real orchestrator, never authorizes) | Low |
| 2 | `/api/ask` is never called by the UI; `ControlAnswer` is never displayed | Answer + the proposal the AI submitted | `agents.py:157` verdict (`decision`,`tool`,`resource`,`executed`,`upstream_contacted`,`action_id`,`receipt`); `GET /api/actions/{id}` (`app.py:277`) | Medium |
| 3 | `/api/actions/pending` is live (`app.py:265`) but has no screen | A "Waiting for your decision" queue of held actions | `GET /api/actions/pending` (`app.py:265`); values kept by the kernel for the hold (`node/warrnt/proxy.py` human branch) | Medium |
| 4 | `approve`/`deny` endpoints live (`app.py:643,648`) but no button exists | Approve / Deny per held action | `POST /api/actions/{id}/approve\|deny` with `{by}` (`app.py:643,648`); SoD `409` (`tests/test_control_plane.py:715`) | Low |
| 5 | `upstream_contacted` exists per action (`app.py:277`) but is not the headline; DENY "Data involved" renders `{}` (defect, diagnosis §1.5) | One line per action: "upstream contacted / NOT contacted", plus the receipt | `/api/actions/{id}` (`app.py:277`), `/api/live-trace` (`app.py:528`), `/api/attest/non-contact` (`app.py:621`); repair the render line | Low |
| 6 | `next_action` (`models.py:20`) never rendered | A closing "what you can do next" line | `ControlAnswer.next_action` (`models.py:20`) | Low |
| 7 | "Stop agent" is `disabled` and needs `localStorage["warrnt_admin"]` (`index.html:103,239`) | Same control, but its unavailable state is explained in user words | `POST /api/agents/{id}/revoke` (`app.py:653`) — exists; only the affordance/labelling changes | Low |
| 8 | Panels `01–05` are all equal weight; kernel vocabulary (`warrant`, `TTL`, `receipt`) leads (`index.html:102–106`) | One dominant surface: the current ACTION and its decision; kernel detail collapses | no backend change — information architecture only | Medium |

**Non-goals of the target** (kept out): policy authoring (no endpoint), multi-agent intent routing
(`agents.py:130` fixes the proposal agent — diagnosis G12), any change to the receipt contract (D13),
anything that makes Prelint a runtime dependency (D2).

---

## 2. UX decisions — WHY / NEED / FIRST / HIDDEN / ACTION

One block per significant decision. Each block answers the five questions explicitly.

### D-A — The intent box is the first thing on the page

- **WHY:** a product whose first move is "press our demo button" is a demo, not a product. The user's
  own problem has to be what the screen starts from.
- **WHAT USER NEED DOES IT SOLVE:** "I have an AI task; I want to say what it is and see what happens"
  (diagnosis G1).
- **WHAT DOES THE USER SEE FIRST:** one text box labelled with their problem, and one button.
- **WHAT IS HIDDEN:** the orchestrator, the specialists, the model, the provider key. None is named.
- **WHAT ACTION CAN THE USER TAKE:** type an intent, submit → `POST /api/ask` (`app.py:801`).

### D-B — Show what the AI wants to do, before any verdict

- **WHY:** the review surface must show the *payload / proposed action*, not a bare yes-no ("empty
  confirm dialogs do not count", `aiuxplayground.com` HITL guide). A human only adds signal if they
  can see the thing being decided.
- **WHAT USER NEED DOES IT SOLVE:** "I need to see what it is about to do before I let it" (G2).
- **WHAT DOES THE USER SEE FIRST:** the proposed ACT — the tool and the resource in plain words
  ("read the EUR/USD rate"), plus who is asking, as attribution only.
- **WHAT IS HIDDEN:** the `action_id`, the run id, the hash, the receipt, the model trace — one click
  away under "Technical details".
- **WHAT ACTION CAN THE USER TAKE:** read it; the only control at this point is to continue watching
  the decision the kernel already reached. Nothing is executable by the user yet.

### D-C — The held action appears in a queue that asks a question a human can answer

- **WHY:** ask at the moment of judgement, with the specific thing named — "send this email to 340
  recipients?" beats "allow agent to use email tools?" (`promptic.us`). And it must be a queue, not a
  modal, because the human's pace is not the agent's (`aydesign.ai` approval-queue pattern).
- **WHAT USER NEED DOES IT SOLVE:** "something is waiting on me and I can decide it" (G3).
- **WHAT DOES THE USER SEE FIRST:** the row sentence — who, did what, to what, and why it stopped
  (the kernel's own `reason`, e.g. `irreversible · a person decides`).
- **WHAT IS HIDDEN:** the class-decider internals, the warrant, the policy rule text. Shown only if
  the user opens technical details.
- **WHAT ACTION CAN THE USER TAKE:** review; open the row; nothing fires without a decision.

### D-D — Approve and Deny are the only primary buttons

- **WHY:** the product's whole value is one human decision on an irreversible act. Primary controls
  should map 1:1 to the decision vocabulary; over-gating and button clutter both train blind clicks.
- **WHAT USER NEED DOES IT SOLVE:** "let it through, or stop it" (G4).
- **WHAT DOES THE USER SEE FIRST:** two buttons of equal visual weight (Cancel-and-Send-as-peers,
  `aiuxplayground.com`; never a default-yes).
- **WHAT IS HIDDEN:** separation-of-duties rules, the requester identity check, audit plumbing — until
  a `409` is returned, which is then explained in plain words ("this is your own request; a different
  person must decide").
- **WHAT ACTION CAN THE USER TAKE:** **Approve** → `POST /api/actions/{id}/approve`; **Deny** →
  `POST /api/actions/{id}/deny`, both `{by}` (`app.py:643,648`).

### D-E — The consequence is one plain sentence: did anything leave the boundary?

- **WHY:** the layer's reason to exist is the deny-before-contact claim. That claim is only worth
  anything if it is stated, not inferred.
- **WHAT USER NEED DOES IT SOLVE:** "did data actually leave, or not?" (G5).
- **WHAT DOES THE USER SEE FIRST:** `Upstream contacted` / `Upstream was NOT contacted`, per action.
- **WHAT IS HIDDEN:** the journal path, the sha256, the latency, the endpoint URL — proof layer.
- **WHAT ACTION CAN THE USER TAKE:** read-only; this is the verification surface, not a control.

### D-F — Technical proof is real but collapsed (progressive disclosure, 20% layer)

- **WHY:** transparency that shows everything erodes trust as fast as hiding everything ("too much
  technical information cancels out the explanation", `aidrivendev.org`); the right amount, in the
  right order, with a path to more. But proof must never be *absent* — sigstore/CloudTrail in
  `design-references.md` set the precedent.
- **WHAT USER NEED DOES IT SOLVE:** "let me verify this if I want to."
- **WHAT DOES THE USER SEE FIRST:** the plain outcome and its receipt id.
- **WHAT IS HIDDEN (behind "Technical details"):** receipt hash, chain/proof (`/api/proof/{run_id}`),
  model trace, latency, tokens, endpoint — the artifacts a judge or auditor wants.
- **WHAT ACTION CAN THE USER TAKE:** expand; copy the receipt; `POST /api/attest/non-contact`
  (`app.py:621`) is available for the non-contact attestation.

### D-G — A refusal shows its reason on the same line as the refusal

- **WHY:** from Stripe Radar (already in `design-references.md`): a machine refusal and a human
  decision meet on one line; the reason sits beside the verdict, not behind it.
- **WHAT USER NEED DOES IT SOLVE:** "why did it say no?" (G5, the DENY leg).
- **WHAT DOES THE USER SEE FIRST:** `deny — no entitlement to market_data.fx.read` (the real reason
  string from `docs/tenet-happy-path-evidence.json`).
- **WHAT IS HIDDEN:** the entitlement graph and the policy structure behind the reason.
- **WHAT ACTION CAN THE USER TAKE:** read-only; a denial is an event on the record, not a control.

### D-H — Nothing runs without a decision (the enforcement boundary is visible, not implied)

- **WHY:** D5 — enforcement happens before execution. The interface must show that the boundary is
  the kernel's, not the UI's; the model proposes and holds no authority.
- **WHAT USER NEED DOES IT SOLVE:** "I can trust that a deny really stopped it."
- **WHAT DOES THE USER SEE FIRST:** the decision word (`allow` / `deny` / `human`) on the action.
- **WHAT IS HIDDEN:** the gate chain (class → actor scope → order policy) as an implementation detail.
- **WHAT ACTION CAN THE USER TAKE:** none — this is a statement of the boundary, and that is the point.

### D-I — The agent is attribution, never the headline

- **WHY:** the brief: the primary object is the ACTION, not the agent. "Agent inventory first" is the
  failure mode already named in `docs/act-4-diagnosis.md` §1.
- **WHAT USER NEED DOES IT SOLVE:** "tell me what happened, not who your system contains."
- **WHAT DOES THE USER SEE FIRST:** the action and its consequence; the agent name is a byline.
- **WHAT IS HIDDEN:** the agent roster, warrants, TTLs — no navigation there from the main surface.
- **WHAT ACTION CAN THE USER TAKE:** open the agent's identity only from within an action.

---

## 3. References collected for Act 7 (decision / approval interfaces)

New to `docs/design-references.md` for this act; not a restructure of that file. Two were opened and
read in full (marked *opened*); the rest were captured from search listings (title + URL + summary)
and are listed as such — no URL here is invented.

- *opened* — `https://aiuxplayground.com/guides/how-to-design-human-in-the-loop` — HITL build
  playbook; "empty confirm dialogs do not count"; Gemini's Cancel/Send as co-equal choices. Source of
  D-B, D-D.
- *opened* — `https://aidrivendev.org/articles/progressive-disclosure-ai` — three-layer disclosure
  (result → rationale → full trace); over-disclosure cancels the benefit of explanation. Source of
  D-F.
- `https://aiuxplayground.com/pattern/progressive-disclosure` — "anything authorizing a side effect
  belongs above the fold". Source of D-A/D-F.
- `https://uicoach.io/ux-laws/progressive-disclosure` — "disclosure must never demote consent or
  consequence". Source of D-F.
- `https://agentscamp.com/guides/workflow/human-in-the-loop-ai-workflows` — gate by blast radius;
  default-deny on timeout. Source of D-C/D-E.
- `https://agentic-patterns.com/patterns/human-in-loop-approval-framework` — approval framework
  components (risk class, context-rich request, approve/reject/modify, audit trail). Source of D-C.
- `https://promptic.us/articles/human-in-the-loop-patterns-for-ai-agents` — "approval is a budget";
  triage by reversibility; ask at the moment of judgement. Source of D-C.
- `https://arifmughal.com/blog/human-in-the-loop-patterns-ai-agents` — five-pattern matrix; "show the
  payload, not the pitch"; OWASP ASI09 approval fatigue. Source of D-B/D-D.
- `https://aydesign.ai/blog/human-in-the-loop-ai-design-guide-2026` — diff / dry-run / approval-queue
  scoring. Source of D-C.
- `https://prxhub.com/justin/citation-ux-and-evidence-navigation` — evidence navigation layering
  (marker → preview → full detail). Source of D-F/D-G.
