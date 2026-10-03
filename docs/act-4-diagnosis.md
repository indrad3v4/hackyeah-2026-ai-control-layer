# ACT-4 — diagnosis before code (product shift: kernel dashboard → security decision tool)

## 1. CURRENT USER STORY (what the screen says today)
`index.html` (657 lines, served at `/`) is inventory-first: three tables — AGENTS / WARRANTS /
KILL SWITCH — with columns `Agent · State · Warrant · Last action · TTL`, plus a header
counter `Checks 80 pytest · 35/35 · 18/18 · 29/29 · 20/20` and a `warrnt @ 2026-10-03`
label. A security operator learns what the system *contains*, never what an agent is
*doing*, *why* it is allowed, or *whether data left the boundary*.

## 2. CURRENT API SOURCE OF TRUTH (real, already authoritative)
`control_plane/kernel.py` is the only read implementation; the UI is one of its consumers.
| endpoint | returns |
|---|---|
| `/api/overview` | counters + authority summary + mode |
| `/api/activity` | ordered real events (run_id, action_id when the record carries them) |
| `/api/actions`, `/api/actions/{id}` | canonical action log; one action = decision + receipt + upstream_contacted |
| `/api/agents`, `/api/warrants` | authority state |
| `/api/state` | agents/warrants/receipts/actions/revoked/last_stop + chain + proof |
| `/api/proof`, `/api/proof/{run_id}` | per-run receipt chain + correlation |
| `/api/upstream/log` | real upstream contacts |
| POST `/api/actions/{id}/approve|deny`, `/api/agents/{id}/revoke`, `/api/ask`, `/api/demo/run`, `/mcp` | the action surface |
No second model is needed: the projection the UI requires is a join over these, not new state.

## 3. REAL FIELD VOCABULARY (from the live chain, not from theory)
`scripts/tenet_deepseek_chain.py` produced, per case: `run_id`, `tool`, `decision`
(allow|deny|human|revoked), `action_id` (A-0001/A-0002), `receipt_id`, `upstream_contacted`
(bool), `boundary_attempts`, `attempts`, `status`; provider evidence: `request_id` (DeepSeek),
`input/output_tokens`, `x-ds-trace-id`; upstream log: `call_id`, `path`, `status`.
Measured: deny → `upstream_contacted=false, attempts=0`; allow → `upstream_contacted=true,
attempts=1`, Frankfurter HTTP 200.

## 4. CONTRADICTIONS
1. **Inventory leads, decision trails.** The strongest material in the system — a request that
   was stopped *before* data left the boundary — is invisible on the first screen.
2. **`call_id = action_id` in the upstream log** (measured: `call_id="A-0002"`). The call id is
   borrowed from the action id, so one action can never show 0/1/n attempts.
3. **No distinct `proposal_id`, `decision_id`, `upstream_call_id`.** Causality is flattened into
   one id, which is exactly the authority leakage ACT-3 forbids.
4. **No `SecurityEvent` projection.** The operator must hand-join four endpoints and still cannot
   see "was upstream contacted?" on the list screen.
5. **Kernel vocabulary on the product surface:** `TTL`, `MCP`, `six kinds of act`, pytest counts,
   `warrnt` branding.

## 5. MINIMUM DATA CONTRACT (one object, projections only)
```
SecurityEvent = {
  event_id, run_id, timestamp,
  agent, actor, intent, resource, tool, action_class,
  warrant, policy, decision, decision_id,
  upstream_contacted (bool), upstream_call_id, execution_result, receipt_id,
  model_trace_id, model_requested, model_served, latency_ms, tokens,
  boundary_attempts, attempts
}
```
Rules: every field is a projection of kernel state or of the persisted provider/upstream
evidence — no invented value, `null` when unknown, never a default that reads as success.
`authority_source = "tenet-kernel"`; `llm_authority = false` always.
UI rule: `upstream_contacted=false` renders "Upstream was NOT contacted"; `decision=deny` renders
"Blocked before execution"; `decision=human` renders "Waiting for human approval".

## 6. IMPLEMENTATION PLAN — first vertical slice
**Slice A (this repo, now):**
1. `kernel.security_events()` — read-only projection joining actions + receipts + provider/upstream
   evidence; plus `kernel.security_event(run_id)` returning the causal graph.
2. `GET /api/security-events`, `GET /api/security-events/{run_id}` — same data, no new authority,
   503 when the kernel cannot answer (same refusal contract as every other read).
3. `index.html` rewritten story-first: EVENT → WHY → WHAT HAPPENED → PROOF → DENY → HUMAN →
   REVOKE, every line from the API; kernel panels move under "TECHNICAL DETAILS"; product name
   TENET; no pytest counters, no TTL columns, no `warrnt` on the product surface.
4. Contextual revoke on the selected active action; no free-floating red button.

**Slice B (mirror, upstream-first — blocked on the same warrnt merge as the 18 red tests):**
`upstream_call_id` (U-…) minted at the boundary instead of `call_id = action_id`;
`proposal_id` (P-…) and `decision_id` (D-…) persisted per decision. Until that merge, slice A
must render `upstream_call_id: null` honestly rather than relabel `action_id`.

**Acceptance:** ALLOW, DENY, HUMAN, REVOKE live; `upstream_contacted` evidence-backed;
`model_trace_id` evidence-backed; authority kernel-owned; UI state changes only from API state.


---

## MEASURED STATE (03.10, after Cline slice A + SoD fix)

Suite: **207 passed / 13 failed** (was 202/18 before the SoD patch).

All 13 remaining failures trace to ONE cause: the mirror (`node/warrnt`, pinned `a3b99218`)
does not export the contract the control plane was written against. Verified absent in the
canonical repo itself (`indrad3v4/warrnt`, working clone `/root/work/warrnt-base`, HEAD
`5cf785d`, and every local branch incl. `feat/actor-register`):

| missing in canonical warrnt | demanded by | effect |
|---|---|---|
| `upstream_log_path()` | `tests/test_control_plane.py:845` imports it | 4 failures; `/api/upstream/log` cannot read the journal `serve_tenet.sh` writes |
| `_sha256_of()` | `control_plane/kernel.py:145` | `ImportError` on the evidence path |
| actor `principal` / `on_behalf_of` / `entitlements` in the projected agent row | ACT-2 tests | 4 failures; projection returns `""` |
| action `requester` | `test_requester_may_not_approve_their_own_hold` | SoD cannot be attributed |
| `boundary_attempts` (0 deny / 1 allow) | ACT-2 §4 | 2 failures |
| denial receipt with `reason="separation of duties"`, `decision="deny"` | D5 | refusal is raised but not recorded |
| `upstream_call_id` distinct from `action_id` | ACT-4 §2 | `call_id == action_id` in the upstream journal |

Also: `warrnt/actors.py` in canonical == mirror (identical) - the actor/entitlement machinery
exists there under its own vocabulary (`ActorKind`, `ActorProfile`), which is why the
projection must read the canonical names instead of a phantom contract.

### Fixed in this pass (control plane, not the mirror)

`SeparationOfDutiesRefused` was imported from `warrnt.controlplane`, where it does not exist -
so `/api/actions/{id}/approve|deny` returned **500** in production. The rule now lives where it
is enforced (`control_plane/kernel.py`), applies to approve *and* deny, and the app imports it
from its own layer. 4 approve/deny tests flipped to green.
