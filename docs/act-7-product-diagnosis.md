# ACT-7 — Product diagnosis: from a kernel console to a decision tool

Scope: `/root/work/tenet-live-trace`, branch `feat/real-data-flow-control-room`, HEAD `be5e947`.
This is a docs-only diagnosis. No code was changed, no server was started or restarted, nothing was
committed. Its predecessor is `docs/act-4-diagnosis.md` (kernel dashboard → security decision tool);
this document does not repeat that endpoint inventory, it moves one step further: from *security
decision tool* to *product a non-technical owner of an AI-domain problem can actually use*, and it
designs for **80% human decision / 20% technical proof**. The primary object of the interface is the
**ACTION**, not the agent, the warrant, the kernel or the model.

Everything under FACT was read or run against the repo just now; each claim cites a file+line, an
endpoint, or an artifact. Anything not verified is under GAP and labelled **unverified**.

---

## 1. FACT — what exists and works today

### 1.1 The live loop (proven; not re-proven here)

The canonical paired demo is captured in `docs/tenet-happy-path-evidence.json` (captured
`2026-10-03T23:53:53+0000`):

| | ALLOW leg | DENY leg |
|---|---|---|
| agent | `fx-trader` | `support-copilot` |
| tool | `fx.read_rate` | `fx.read_rate` |
| action id | `A-0002` | `A-0003` |
| run id | `demo-c6d6c5ac` | `demo-c83c6ae1` |
| decision | `allow` | `deny` |
| reason | `read-only · live reference rate · in scope · class observe` | `no entitlement to market_data.fx.read` |
| upstream contacted | **true** | **false** |
| result | Frankfurter HTTP 200, EUR/USD `1.1225`, `22.78` ms, sha256 `f63f64a5e9b3584bd32e0ea70927ea574bea7ef36df1a28fefb4ed6410400297` | `execution_result: {}` |
| receipt | `1fbb161d` | `bfc7eacc` |

The upstream journal counter proves the deny never crossed the boundary:
`sent_before: 1 → sent_after_allow: 2 → sent_after_deny: 2`
(`docs/tenet-happy-path-evidence.json`, `upstream`). The kernel is the only authority in this loop;
the model proposes and holds none (`llm_authority: false`).

I did **not** re-run this loop. The read-only rig was not answering (see GAP G8).

### 1.2 The real HTTP surface (`control_plane/app.py`)

26 routes exist. The ones that matter to a product surface:

| Route | Line | What it is |
|---|---|---|
| `GET /` | `app.py:187` | serves `index.html` |
| `GET /health` | `app.py:194` | liveness |
| `GET /api/overview` | `app.py:214` | counters + authority summary + mode + `upstream_configured` |
| `GET /api/activity` | `app.py:233` | ordered real events |
| `GET /api/actions` | `app.py:255` | the canonical action log |
| `GET /api/actions/pending` | `app.py:265` | **the hold queue** (real) |
| `GET /api/actions/{id}` | `app.py:277` | one action = decision + receipt + `upstream_contacted` |
| `GET /api/agents` | `app.py:293` | authority state (identity/delegation) |
| `GET /api/warrants` | `app.py:305` | warrant register |
| `GET /api/state` | `app.py:313` | agents/warrants/receipts/actions/revoked + chain + proof |
| `GET /api/proof`, `/api/proof/{run_id}` | `app.py:338`, `app.py:354` | per-run receipt chain |
| `GET /api/model-usage` | `app.py:452` | model trace evidence |
| `GET /api/security-events`, `/{run_id}` | `app.py:490`, `app.py:507` | the SecurityEvent projection |
| `GET /api/live-trace?action_id=` | `app.py:528` | one action + its authority evidence, read-only join |
| `POST /api/scenario/self-check` | `app.py:566` | runs the fixed paired allow/deny scenario |
| `GET /api/upstream/log` | `app.py:604` | real upstream contacts |
| `POST /api/attest/non-contact` | `app.py:621` | attests a non-contact |
| `POST /api/actions/{id}/approve` | `app.py:643` | **release a hold → allow** |
| `POST /api/actions/{id}/deny` | `app.py:648` | **refuse a hold → deny** |
| `POST /api/agents/{id}/revoke` | `app.py:653` | pull an order |
| `POST /api/demo/run` | `app.py:679` | operator-token demo |
| `POST /mcp` | `app.py:745` | the agent entry point |
| `POST /api/ask` | `app.py:801` | **human-intent entry point** (see 1.4) |

### 1.3 The kernel really holds — not a label

- `Kernel.pending()` returns `self.proxy.actions.listing(state="pending")`
  (`control_plane/kernel.py:127–128`).
- On a `human` decision the proxy keeps the request in memory **and persists the held row with its
  values (mode 0600) so a restart can hand the exact action back**:
  `action.state, action.kept_for_hold = "pending", True` (`node/warrnt/proxy.py`, the `Decision.human`
  branch inside `intercept`, `node/warrnt/proxy.py:212`).
- `Kernel.resolve_hold(action_id, approve, by)` (`kernel.py:979`) → `proxy.resolve_hold`
  (`node/warrnt/proxy.py:340`), wired to `POST /api/actions/{id}/approve|deny` (`app.py:643,648`).
- Separation of duties is enforced: a requester may not approve their own hold; the hold stays
  `pending` and the API answers `409` (`tests/test_control_plane.py:715`).
- The end-to-end hold is tested: `test_approve_flow_pending_to_allow_with_receipt`
  (`tests/test_control_plane.py:123`) asserts `decision == "human"`, that the action appears in
  `/api/actions/pending`, and that approval produces a receipt. `test_revoke_expires_a_pending_action`
  (`:182`) covers expiry.
- Which acts reach a person is fixed policy: `irreversible` acts are decided by a person
  (`payments.transfer`, `infra.deploy`), `authorize` acts by the operator-human only
  (`docs/stage-4-action-classes.md`, the six-class table). So a real tool exists today whose verdict
  is `human` and which therefore creates a real pending hold.

### 1.4 There is already a safe human-intent entry point, and a proposal capability

- `POST /api/ask` (`app.py:801`) runs the **real orchestrator** (`control_room/agents.py:266`,
  `answer()`) and "never authorizes anything" — it is the safe place for a human to type an intent.
- The orchestrator holds one write-shaped tool, `_propose_action` (`control_room/agents.py:113`). It
  "writes nothing itself: it calls the kernel's own `Kernel.intercept` — the same entry point `/mcp`
  and `/api/demo/run` use" (`agents.py:115–121`) and returns the verdict in the kernel's own words,
  including `decision`, `action_id`, `receipt`, `executed`, `upstream_contacted` (`agents.py:157`).
  The agent token is read from the kernel registry, never passed as an argument (`agents.py:123`).
- `ControlAnswer.next_action` exists (`control_room/models.py:20`) as the advisory "what now" hint.

So the whole backend chain the minimum slice needs — intent → proposal → kernel verdict → held action
→ human decision → consequence → proof — **already exists**. It is simply not on the screen.

### 1.5 What the screen shows today (`index.html`, 242 lines)

- **0 `<input>`, 0 `<textarea>`** in the whole file (verified: `grep -c` returns 0 for both). There is
  **no user-intent entry in the UI at all.**
- Five numbered sections:
  - `01 · The action under control` (`index.html:102`, `id="traceCard"`) — the last intercepted action
    card. Its empty state ("TENET has enforced nothing yet") carries a **"Run the paired allow / deny
    scenario"** button (`id="selfCheck"`, handler `index.html:240`) that POSTs
    `/api/scenario/self-check`.
  - `02 · Who decides` (`index.html:103`) — `authoritySource` = `tenet-kernel`, the `llm_authority:
    false` note, and a **disabled "Stop agent" button** (`id="revoke"`, enabled only for a selected
    live agent; the handler requires an operator token in `localStorage["warrnt_admin"]`,
    `index.html:239`).
  - `03 · Models & resources` (`index.html:104`, `id="resourceStrip"`) — calls / tokens / latency.
  - `04 · Actions on the record` (`index.html:105`, `id="feed"`) — the event feed.
  - `05 · Inspect this action` (`index.html:106`, `id="details"`) — one selected record + a
    **"Refresh evidence"** button.
- **No pending-hold UI, no approve/deny button** anywhere in `index.html`, even though
  `/api/actions/pending` and both decision endpoints are live. A held action is invisible and
  un-actionable from the product.
- **Known real defect:** on the DENY card the "Data involved" line renders
  `action class not recorded {}` — the empty object is printed where the field list should be
  (`docs/tenet-happy-path-evidence.json`, `selected_render.deny`, captured from the live UI). The
  earlier brief described this as "empty parentheses `()`"; the artifact actually on disk shows `{}`.
  The verified form is `{}`.

### 1.6 Prelint — the honest state

`AGENTS.md:3` says "Prelint enforces these on every pull request" and **D2** (`AGENTS.md:12`) says
"Prelint integration lives on the `prelint` branch only. Tooling for code review must never become a
runtime dependency of the control layer itself."

Verified: local remote-tracking refs `refs/remotes/origin/prelint` (`d842687e`, message
"docs(decisions): D13 — a frozen contract changes only by a recorded unfreeze") and
`refs/remotes/origin/chore/prelint-align-d5` (`5bc5bdd3`) exist. **But** a fresh
`git ls-remote --heads origin` returns 27 heads and includes neither; and `git ls-tree -r
origin/prelint` contains only `AGENTS.md`, `README.md`, `index.html` and media — **no `scripts/`, no
prelint tooling**. So on this box Prelint is a documented *review policy*, not an inspectable
mechanism. See GAP G9.

### 1.7 Prize

There is partner context for the task, but **no documented prize was found in this repository**. That
is the whole statement; no prize is claimed.

---

## 2. GAP — what is missing before a non-technical person gets real value

The product's stated job is: a person with an AI-domain problem states an intent, **sees what the AI
wants to do**, sees the consequence, controls it, and gets the proof. Today it delivers step one's
backend and none of the interface.

| # | Gap | Evidence | Verified? |
|---|---|---|---|
| G1 | No way to state an intent | `index.html` has 0 `<input>`/`<textarea>` (1.5); `POST /api/ask` (`app.py:801`) is never called by the UI | verified |
| G2 | Nothing renders what the AI *wants to do* | the `_propose_action` verdict (`agents.py:157`) and the `/api/ask` answer have no surface; `ControlAnswer` is never displayed | verified |
| G3 | A held action is invisible | `/api/actions/pending` is live (`app.py:265`) but `index.html` has no pending list | verified |
| G4 | The user cannot decide a hold | `approve`/`deny` endpoints live (`app.py:643,648`) but no button in `index.html` | verified |
| G5 | Consequence is not stated in user terms | `upstream_contacted` exists per action (`app.py:277`) but is buried; the DENY "Data involved" line is broken (`{}`) | verified |
| G6 | No "what do I do now" | `next_action` (`models.py:20`) is never rendered | verified |
| G7 | The brake is unreachable for the target user | "Stop agent" is `disabled` and needs an operator token in `localStorage` (`index.html:103,239`) | verified |
| G8 | The live loop was not re-executed | the rig on `127.0.0.1:8399` returned empty bodies to `curl` for `/health`, `/api/overview`, `/api/actions/pending`, `/api/agents`; the canonical numbers are cited from `docs/tenet-happy-path-evidence.json`, not re-measured | **unverified (this session)** |
| G9 | Prelint mechanism not inspectable | `AGENTS.md:3,12` document it; no prelint code on `origin/prelint` and neither named branch appears in a fresh `ls-remote` (1.6) | **unverified** |
| G10 | End-to-end intent→hold not demonstrated | whether `/api/ask` in a live deployment actually reaches `_propose_action` for an irreversible tool and yields a pending hold is asserted by code (`agents.py:113–163`, `proxy.py` human branch) but was not run (see G8) | **unverified** |
| G11 | One action can never show 0/1/n upstream attempts | `call_id = action_id` in the upstream log (`docs/act-4-diagnosis.md` §4); whether this is still true now was not re-measured | **unverified** |
| G12 | Multi-agent intent routing | `_propose_action` falls back to a single fixed agent, `PROPOSAL_AGENT_ENV or "fx-trader"` (`agents.py:130`); a non-technical user cannot choose *which* agent carries their intent | verified (code) |

---

## 3. MINIMUM PRODUCT SLICE

**The smallest set of changes that turns the console into the stated product — every control maps to
an endpoint that already exists (`docs/act-7-current-to-target.md` §1 gives the mapping).**

1. **Intent entry (fixes G1).** Add one text box to the console that POSTs `{q}` to `POST /api/ask`
   (`app.py:801`). Field label states the user's own problem, e.g. "What do you need done?".
2. **Proposal / answer surface (fixes G2).** Render the `/api/ask` answer and, when the orchestrator
   used `_propose_action`, the kernel verdict it returned — `decision`, `tool`, `resource`,
   `executed`, `upstream_contacted`, `action_id`, `receipt` (`agents.py:157`). Fetch the referenced
   action with `GET /api/actions/{id}` (`app.py:277`) so the proposal resolves to a real record.
3. **The hold queue (fixes G3).** Render `GET /api/actions/pending` (`app.py:265`) as a "Waiting for
   your decision" list; one row per held action with the agent, the tool, the action class, and the
   held values the kernel kept for the hold (`proxy.py` human branch).
4. **The two decisions (fixes G4).** Per held action, **Approve** → `POST /api/actions/{id}/approve`
   and **Deny** → `POST /api/actions/{id}/deny`, both with `{by}` (`app.py:643,648`). Handle the `409`
   separation-of-duties refusal (`tests/test_control_plane.py:715`) as an explanation, not an error.
5. **Consequence + proof on the action (fixes G5).** After a decision, show the two facts that matter
   in one line each: **"upstream contacted / NOT contacted"** and the **receipt id** (`app.py:277`,
   `/api/live-trace` `app.py:528`). Repair the DENY "Data involved" line so the fields are named
   (defect in 1.5).
6. **Next step (fixes G6).** Render `next_action` (`models.py:20`) as the closing line of the answer.

**Explicitly out of the slice** (do not build): any new backend authority; any change to the receipt
contract (D13); a policy-authoring UI (no endpoint exists); model/warrant/kernel controls as primary
objects; multi-agent intent routing (G12, no endpoint). Nothing here proposes a control whose backend
does not exist.

---

## 4. Top 5 product failures (ranked by user value / demo value / implementation cost)

Scores are the author's judgement, stated plainly so they can be argued.

| Rank | Failure | Why it fails the user | User value | Demo value | Impl. cost |
|---|---|---|---|---|---|
| **1** | **No intent entry point** (G1) | The user cannot begin. 0 inputs in 242 lines; the only "do" control is a fixed scenario button. The product never hears the user's problem. | High | High | Low |
| **2** | **The human hold is invisible and undecidable** (G3+G4) | The one decision the product exists for — approve/deny an irreversible act — cannot be made on screen, even though the hold, the queue and both endpoints are live and tested. | High | High | Medium |
| **3** | **The AI's proposal has no surface** (G2) | Even with an intent box, the user cannot *see what the AI wants to do* before it is decided; the `_propose_action` verdict is returned and discarded. Directly blocks the "sees what the AI wants to do" step. | High | Medium | Medium |
| **4** | **The DENY card is broken and kernel-voiced** (G5) | The single record a reviewer reads renders `action class not recorded {}`, and the labels are the kernel's, not the user's. The proof looks unfinished at exactly the moment it should build trust. | Medium | High | Low |
| **5** | **No "what now", and the brake is dead** (G6+G7) | After a decision the user gets no next step; the Stop-agent brake is disabled and needs an operator token the target user does not hold. The product answers but does not guide or reassure. | Medium | Medium | Low |
