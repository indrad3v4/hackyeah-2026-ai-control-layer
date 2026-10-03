ARCHIVED 2026-10-03 — superseded by docs/TENET-CONTRACT.txt (canonical). Kept for history only.
======================================================================
# TENET Control Room — LIVE contract (PR #14)

STATUS: CONTRACT (acceptance criteria) · 2026-10-03 · branch `feat/control-room-v2-hermes`
AUTHORITY: this contract is the reviewer's copy of the operator's brief. If code and this file
disagree, this file wins until the operator says otherwise.

## 0. ONE SENTENCE

Turn the existing prototype (static console + kernel node + a `control_room/` skeleton) into a
**live TENET Control Room on Railway**, where the UI, the control-plane API, the agents and the
kernel all speak about the **same Action**, and every claim is proven by an artifact.

## 1. BOUNDARY (hard, no exceptions)

```
Agent → control-plane → WARRNT → decision → upstream/refusal → receipt
```
Never `Agent → allow → upstream`. Agents, Reflex, and the LLM are **never** the authorization
layer. WARRNT stays the sole authority for: action classification · warrant state · policy ·
decision · human hold · revoke · execution boundary · receipt/proof.

## 2. SECRETS

`DEEPSEEK_API_KEY` comes only from the environment (Railway variables / `/root/.hermes/.env`).
Never committed, printed, logged, returned by an API, embedded in frontend JS, put in a PR
comment or a screenshot. The only admissible statement about it is **PRESENT / ABSENT**.
Verification command must redact: `python -c "import os;print('PRESENT' if os.getenv('DEEPSEEK_API_KEY') else 'ABSENT')"`.

## 3. SURFACES

| surface | role | canonical? |
|---|---|---|
| Railway service (Reflex + control-plane) | live runtime | YES |
| `node/warrnt` (WARRNT kernel + its API) | authority | YES |
| GitHub Pages `index.html` | static showcase that POINTS to the live URL | NO |
| local console `node/warrnt/console.html` | kernel's own screen, unchanged | NO |

GitHub Pages must never claim to be the live agentic runtime. If it stays static, it says so and
links the Railway URL.

## 4. ACCEPTANCE CRITERIA (each with its evidence type)

Runtime
- [ ] AC1 DeepSeek is called for real — evidence: one saved provider response (status + model id + usage), no key value.
- [ ] AC2 Key never leaves env — evidence: grep over repo/PR/logs shows no key; `PRESENT` check in `/health`.
- [ ] AC3 OpenAI Agents SDK orchestrator runs — evidence: `run_id` + chosen specialist in the answer payload.
- [ ] AC4 Three specialist agents exist (Governance / Kernel / Control-Plane) — evidence: `/api/agents` + a call that reaches each.
- [ ] AC5 Answers are grounded in real WARRNT records — evidence: each answer carries `action_id`/receipt it cites; unknown id ⇒ explicit refusal to answer.
- [ ] AC6 Fallback/demo mode is visibly distinct from live — evidence: `/health` reports `LIVE` / `DEGRADED` / `DEMO`.

Control plane
- [ ] AC7 Required endpoints exist and answer: `GET /api/overview`, `/api/activity`, `/api/actions`, `/api/actions/{id}`, `/api/actions/pending`, `/api/agents`, `/api/warrants`, `POST /api/actions/{id}/approve`, `/api/actions/{id}/deny`, `POST /api/agents/{id}/revoke`, `POST /api/ask` (+ `/api/state` kept) — evidence: a saved transcript of real responses.
- [ ] AC8 Canonical objects exposed: Action, Event, Agent, Warrant, Decision, Receipt, Evidence.
- [ ] AC9 Event vocabulary emitted: tool_call.pending, tool_call.classified, human.required, decision, execution.started, execution.completed, execution.refused, warrant.revoked, receipt.committed.
- [ ] AC10 Human hold canonical flow: pending → human.required → decision → execution/refusal → receipt; `expired` is a **warrant state**, not a receipt decision — evidence: `human_hold_evidence.py`.
- [ ] AC11 Approve runs upstream once; deny never contacts upstream; revoke expires the pending hold — evidence: `console_hold_check.py` 17/17.

UI (Reflex, Python only — no React/TS/Vite/Next)
- [ ] AC12 Views A–E exist: COMMAND (chat), ACTIVITY (timeline), ACTION INSPECTOR (the full field list), AUTHORITY (agents/warrants/pending), PROOF (receipts/hashes, trace correlation).
- [ ] AC13 The UI shows ACTION / WHY / WHO / AUTHORITY / POLICY / DECISION / EXECUTION / PROOF.
- [ ] AC14 One Action is the same object in UI, API and kernel — evidence: same `action_id` and the same `receipt` in all three, screenshotted.

Agent trace vs security trace
- [ ] AC15 Both traces exist and correlate on `run_id` / `action_id`; they are never merged into one trust system — evidence: `/api/activity` + a correlated pair.

Deployment
- [ ] AC16 Railway service live, health-checked, deterministic `GET /health` with live status.
- [ ] AC17 Public URL externally reachable and tested from outside (not only localhost).
- [ ] AC18 Survives a restart with state intact (volume/`/data` or documented reset).

Journeys (each = a saved external transcript against the deployed URL)
- [ ] AC19 "What is happening?" → grounded answer with run_id + specialist + evidence records.
- [ ] AC20 "Why was support-copilot blocked?" → cites a real Action Inspector record: action_id, warrant, class, decision, reason, upstream_contacted.
- [ ] AC21 "Show me the warrant." → real warrant record, no invention.
- [ ] AC22 "Stop support-copilot." → real revoke through WARRNT + receipt.
- [ ] AC23 Human-hold action end-to-end (pending → human.required → operator → decision → execution/refusal → receipt).
- [ ] AC24 "Did it reach the CRM?" → answered from `upstream_contacted` / `execution_result` / receipt, never from the model's memory.

Proof that gate the merge
- [ ] AC25 All tests pass: `cd node && python -m pytest -q` · `human_hold_evidence.py` · `console_hold_check.py` · `console_check.py` · `check_console.py` · `ask_evidence.py` · `sync-node.sh --check` · `doc_qa.py --node node --run` · control-room tests · compile checks.
- [ ] AC26 CI green on the branch head.
- [ ] AC27 Browser verification against the **deployed** URL (headless Chromium), screenshots kept as artifacts.
- [ ] AC28 GitHub Pages situation documented: what it serves, why, and the link to the live URL.
- [ ] AC29 Evidence artifacts committed (or referenced by path) — receipts, API transcripts, browser run, provider call.

## 5. EVIDENCE RULES

Cline's self-report is **not** evidence. Evidence = test output, CI run, API response, browser
verification, receipt, deployment state, GitHub state. Every "implemented/live/verified/deployed/
working" claim in the final report must point at one of those. If something is not done, the report
says exactly what remains.

## 6. OUT OF SCOPE (say so instead of doing it)

- No new taxonomy: action classes = observe, read_personal, draft, write_reversible, irreversible,
  authorize; decisions = allow, deny, redact, human, revoked; warrant states = active, revoked, expired.
- No rewriting of unrelated history; do not repurpose PR #13; do not break the WARRNT dependency
  contract — if the kernel must change, go through the WARRNT repo workflow and bump the pinned SHA.
- No 14 agents: exactly 1 orchestrator + 3 specialists.
- No secret in any artifact.

## 7. WORKFLOW

CONTRACT → PLAN → PLAN REVIEW (operator) → ACT (Cline) → TEST → EXTERNAL VERIFICATION →
EVIDENCE → COMMIT → PUSH → DEPLOY → BROWSER VERIFY.

Cline is the coding executor (deepseek-chat). Hermes is orchestration + review + external
verification. One Cline task at a time per file set.
