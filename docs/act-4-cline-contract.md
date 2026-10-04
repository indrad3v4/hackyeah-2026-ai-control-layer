# ACT-4 SLICE A — contract for the coding agent (Cline)

Role: product architect + security UX designer + control-plane engineer.

Read first: `AGENTS.md` (D1–D13 + Amendment 1), `docs/act-4-diagnosis.md`,
`docs/act-3-causal-graph.md`, `control_plane/kernel.py`, `control_plane/app.py`, `index.html`.

## GOAL
Turn the Control Room from a kernel inventory into a security decision tool: the first screen
answers, in plain language, what an AI agent is trying to do, why TENET allowed or blocked it,
whether data actually left the boundary, and what the operator can do now.

## HARD CONSTRAINTS
1. **No new state, no new authority.** `security_events()` is a read-only projection of kernel
   state + persisted evidence. Nothing in this slice may decide anything.
2. **Do NOT edit `node/`** — it is a generated MIRROR of `warrnt` (see `MIRROR.md`). Mirror changes
   are proposed upstream in `warrnt`, never patched here.
3. **Do NOT commit.** Leave the working tree for review. `git status --short` + `git diff --stat`
   is the handoff.
4. **No invented values.** Unknown → `null`. Never a default that reads as success.
5. **`upstream_call_id` is not available yet** (slice B). Render `null` and keep `action_id`
   separate; do NOT relabel `action_id` as a call id anywhere.
6. Keep every existing endpoint working — this is additive.

## DELIVERABLES
1. `kernel.security_events(limit)` and `kernel.security_event(run_id)` returning the
   `SecurityEvent` object from the diagnosis (§5) and, for one run, the causal graph
   (`run_id → model_trace_id → action_id → decision → upstream_call_id → receipt_id`),
   with `authority_source="tenet-kernel"` and `llm_authority=false`.
2. `GET /api/security-events`, `GET /api/security-events/{run_id}` — JSON projections; 503 with the
   same refusal body as the other reads when the kernel is unavailable.
3. `index.html` rewritten **story first**:
   - Screen 1: `AI AGENT ACTIVITY` — agent, what it wants (`EUR → USD market rate`), purpose,
     TENET status (identified / authority checked / policy checked / allowed), upstream result,
     and buttons `SEE WHY · SEE EVIDENCE · STOP AGENT`.
   - Screen 2 (WHY): WHO / WHAT / DATA / AUTHORITY (warrant) / POLICY / DECISION / WHY, plain
     language, technical fields expandable.
   - Screen 3 (WHAT HAPPENED): the real chain, each step labelled, all from API state.
   - Screen 4 (PROOF): run_id, model trace, action, decision, upstream call, receipt — with the
     line "These IDs are evidence. Authority lives in the TENET kernel decision."
   - DENY story: "The request stopped before data left the boundary" + proof that the upstream log
     contains no call.
   - HUMAN story: pending action, upstream NOT contacted, `APPROVE` / `DENY`.
   - REVOKE: contextual to the selected active action/agent, and states what was stopped.
   - Technical details (agents, warrants, TTL, MCP, pytest counts, chain) live only under a
     collapsed `TECHNICAL DETAILS` section. Product name is TENET; `warrnt` may not appear on the
     product surface.
4. All four stories must work from real API state; no hardcoded narrative, no fake feed.

## VERIFY BEFORE REPORTING
- `python -m pytest tests/ -q` — report the exact pass/fail line. Known pre-existing reds: the 18
  ACT-2 identity/entitlement tests caused by the mirror gap (a separate curable cause) — name them
  as pre-existing, do not "fix" them by editing `node/`.
- Live: start the control plane, run the real chain (`scripts/tenet_deepseek_chain.py`), then show
  ALLOW / DENY / HUMAN / REVOKE rendering from `/api/security-events` with real ids and
  `upstream_contacted` values.

## REPORT
PRODUCT INSIGHT · IMPLEMENTED FLOW · API CHANGES · UI CHANGES · LIVE EVIDENCE · TESTS ·
REMAINING GAPS. Claims only what was executed.
