# ACT-7 · minimal implementation plan — vertical slice #1

Locked slice: **intent entry + real human control (HOLD / Approve / Deny / Revoke)**, one
complete user journey, no invented lifecycle.

## FACT — verified in the repo today

| Need | What already exists | Where |
|---|---|---|
`/api/ask` | real orchestrator call; **never authorizes** (`llm_authority: false`) | `app.py:801`, docstring |
Run one real action | `POST /api/demo/run` reads the agent token **server-side**, calls `k.intercept(agent_id, token, "fx.read_rate", args)` | `app.py:679` |
ALLOW | `fx-trader` entitled to `market_data.fx.read` → upstream contacted, HTTP 200, receipt | live run, PR #29 |
DENY | `support-copilot` not entitled → `upstream_contacted=false` | live run, PR #29 |
HOLD | **real catalog rule**: `W-9003 fx-auditor`, `scope="fx.read_rate ⇒ require-human"`, `Rule(effect="human")` | `kernel.py:1128` |
HOLD evidence | `node/evidence/human_hold-20261003T1707*.json` (3 real files) | repo |
Approve / Deny | thin wrappers over the kernel's one resolve path, operator token `X-WARRNT-ADMIN` | `app.py:643,648`, `_resolve` |
Revoke | thin wrapper over the kernel's one revoke path | `app.py:653` |
Pending list | `proxy.pending()` → `actions.listing(state="pending")` | `app.py` `actions_pending`, `kernel.py:127` |
Tests already asserting the hold | `decision == "human"` | `test_control_plane.py:128,191`, `test_live_trace.py:130,408` |
Honest operator gate in the UI | revoke reads `localStorage.warrnt_admin`; without it: "Stop agent is protected." | `index.html:239` |

Three states, three different real agents, **the same resource** `fx.read_rate`:
`fx-trader` → ALLOW · `support-copilot` → DENY · `fx-auditor` → HOLD.

## GAP — what is missing for the user loop

1. **No input in the UI at all** — `index.html` has no `<input>`, no `<textarea>`.
2. **No bridge from a proposal to a runnable action.** `/api/ask` returns `next_action` as an
   advisory **string** (`control_room/models.py:20`) and `action_id` only when the answer
   already cited an existing action. The model cannot produce a runnable action — the bridge
   must not pretend otherwise.
3. **No control block**: approve / deny / revoke exist as routes but the UI shows only a
   disabled "Stop agent".
4. **No consequence line** ("nothing leaves TENET" / "data leaves TENET" / "not sent yet").
5. **Empty `()`** on the DENY card's DATA INVOLVED row.
6. No human-language layer: sections are named after infrastructure (02 Who decides, 03 Models
   & resources) instead of the decision.

## MINIMUM SLICE — the smallest complete journey

1. **Intent box** at the top: "What should your AI do?" → `POST /api/ask` (real, non-authoritative).
   The answer is shown as a **proposal**, explicitly not a permission.
2. **No new bridge endpoint is needed — the bridge already exists.** The orchestrator carries
   the `propose_action` tool (`control_room/agents.py:113`), which calls the *same*
   `Kernel.intercept` entry point as `/mcp` and `/api/demo/run` and returns the kernel's own
   verdict: `{submitted, proposed_by: deepseek, authority: tenet-kernel, llm_authority: false,
   agent, tool, resource, action_id, decision, reason, executed, upstream_contacted, receipt,
   rationale}` (`agents.py:157`). The model is instructed (`agents.py:227`) to call it with a
   tool id from the live set (`fx.read_rate`, `equity.read_snapshot`). **The gap is that
   `/api/ask` returns that verdict inside `evidence` and the UI never renders it.** So the
   slice surfaces what already exists; it invents no lifecycle and adds no authority.
   The agent on that path is chosen by `PROPOSAL_AGENT_ENV` (default `fx-trader`,
   `agents.py:129`) — a process-level setting, not a per-request one.
3. **Action card, human-first**: what the AI wants to do · who is asking · what it reaches ·
   why TENET decided this · **what happens outside TENET** · what actually happened · proof.
   Technical identifiers stay under "Technical details".
4. **Control block** (only real controls): on HOLD — "Nothing has been sent yet." + Approve /
   Deny; on any state — Revoke. All three hit the existing routes with the operator token the
   operator supplies (same honest gate as revoke today; absent token → the honest message).
5. **Fix the empty `()`** with a truthful string, only when the backend really holds no data.

## WHO ACTS — the one remaining real choice (corrected after verification)

The bridge is not hypothetical, so the question changed. What is verified:

- the **model's own proposal path already produces the canonical ALLOW** (`fx-trader` on
  `fx.read_rate`), with a real receipt — the intent journey needs no new route;
- the agent on that path is **fixed per process** (`PROPOSAL_AGENT_ENV`, default `fx-trader`),
  so a fresh intent cannot make `support-copilot` or `fx-auditor` act;
- `support-copilot` (DENY) and `fx-auditor` (HOLD) are reachable **only** through
  `POST /api/demo/run`, which accepts `agent` and reads the agent token server-side.

So the slice needs one explicit human choice, and only this one:

- **1 (smallest, honest) — LOCKED by Indra, 2026-10-04.** — the intent box keeps the real proposal path (`fx-trader`, ALLOW),
  and a separate, visible **"who acts" selector** drives the real `/api/demo/run` for
  `support-copilot` (DENY) and `fx-auditor` (HOLD) against the **same** `fx.read_rate`.
  Nothing is invented; the three states are three kernel verdicts.
- **2** — give `propose_action` a per-request agent override so the intent itself can name the
  agent. Real, but it changes the assistance surface (`agents.py`), not only the UI.
- **3** — proposal path only; DENY/HOLD stay behind the existing scenario button.

## PRELINT — recorded exactly as found (no prize claimed)

- `AGENTS.md` documents the policy: "Prelint enforces these on every pull request", and D2 keeps
  Prelint integration on the `prelint` branch only, never a runtime dependency.
- **The mechanism is not present in this repository today:** `git ls-remote --heads origin`
  lists 27 heads and none matches `prelint`; there is no `prelint` reference in
  `.github/workflows/ci.yml` or in `README.md`. Local `remotes/origin/prelint` refs are stale
  from an older fetch.
- Therefore the honest engineering story is: the gate **policy** is documented and the CI
  workflow exists, but Prelint itself is not inspectable here. Any prize claim would be
  unfounded and is not made.

## Acceptance (machine-checkable)

- [ ] intent → proposal shown; the proposal is never an authorization
- [ ] ALLOW: upstream contacted, delta `1→2`, real value + receipt on screen
- [ ] DENY: `upstream_contacted=false`, upstream delta unchanged
- [ ] HOLD: action NOT executed, "not sent yet" shown, then Approve → executed, Deny → not
- [ ] REVOKE: agent loses authority, the next attempt is refused
- [ ] every control either works or states honestly why it cannot (no fake control)
- [ ] positive + negative test per new control (D10)
- [ ] `pytest` green, pre-lint green, live proof on a clean rig from the committed SHA
- [ ] README story updated only where the journey changed
