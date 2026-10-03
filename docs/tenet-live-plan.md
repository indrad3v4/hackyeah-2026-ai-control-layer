# PLAN — TENET Control Room LIVE (AC1–AC29) vs. frozen decisions D1–D13

**Scope of this document:** plan only. No edits, commits, pushes, or deploys. Every claim below is checkable against the tree at `/root/.hermes/hackyeah/ai-control-layer` on branch `pr14-work` (tracks `origin/feat/control-room-v2-hermes`).

**Authority note.** `docs/tenet-live-contract.md` is *untracked* (`git status` shows `?? docs/tenet-live-contract.md`). Per its own §"AUTHORITY" it wins over code until the operator says otherwise, but a contract that is not committed cannot gate a PR. Step 0 commits it.

---

## 1. What ALREADY exists vs what is MISSING — per acceptance criterion

Legend: ✅ exists · 🟡 partial · ❌ missing.

### Runtime

| AC | State | Evidence in tree |
|---|---|---|
| **AC1** DeepSeek called for real | ❌ | No `deepseek`/`DEEPSEEK` string anywhere in `control_room/`, `node/warrnt/`, `scripts/`. `control_room/agents.py:63` gates the whole live path on `os.getenv("OPENAI_API_KEY")` — the wrong provider, and no DeepSeek client/model is ever constructed. |
| **AC2** Key never leaves env | 🟡 | No key handling exists at all (good: nothing leaks). But `/health` in `node/warrnt/api.py:184` returns only `{ok, node, chain}` — no `PRESENT`/`ABSENT` line as AC2's evidence requires. |
| **AC3** OpenAI Agents SDK orchestrator runs | 🟡 | `control_room/agents.py:9-12` imports `Agent/Runner/function_tool` optionally; `build_agents()` + orchestrator with agents-as-tools exist (`agents.py:52-74`). But it short-circuits to a canned sentence when the key is absent (`:63-64`), and there is no test that it ever runs; `specialists` is hardcoded to all three (`:75`), so "chosen specialist" is not real. |
| **AC4** Three specialist agents | 🟡 | All three are built (`agents.py:52-57`: Governance/Kernel/Control-Plane). No `GET /api/agents` on the *control-plane/Reflex* side — the node's `GET /agents` (`api.py:244`) lists *kernel* agents, not the three Hermes specialists. No evidence that a call reaches each. |
| **AC5** Answers grounded in real WARRNT records | 🟡 | Node side is strong: `node/warrnt/controlplane.py:147-300` `answer()` builds every sentence from Action fields and refuses when the record is empty (`:256-259`, `:265-271`). But the *agentic* surface (`control_room/agents.py:59-75`) only attaches a state snapshot; it does not carry an `action_id`/receipt per claim, and does not refuse on an unknown id. |
| **AC6** LIVE / DEGRADED / DEMO visible | ❌ | No such vocabulary exists. `node/warrnt/api.py:184-186` `/health` has no mode field. `index.html:269-271` has a client-side `source=live|demo` toggle, but that is the static page, not the deployed `/health`. |

### Control plane

| AC | State | Evidence in tree |
|---|---|---|
| **AC7** Required endpoints answer | 🟡 | **Exist now:** `GET /api/actions` (`api.py:294`), `GET /api/actions/{id}` (`:302`), `POST /api/actions/{id}/approve` (`:311`), `POST /api/actions/{id}/deny` (`:327`), `POST /api/ask` (`:343`), `GET /warrants` (`:234`), `GET /agents` (`:244`), `GET /api/state` (`:192`). **Missing:** `GET /api/overview`, `GET /api/activity`, `GET /api/actions/pending` (pending is only a nested key on `/api/actions`, `:299`), `GET /api/agents` (only unscoped `/agents`), `POST /api/agents/{id}/revoke` (only `POST /revoke` with a body, `:353`). |
| **AC8** Canonical objects exposed | 🟡 | `node/warrnt/controlplane.py:47-77` defines the canonical `Action` dataclass; models exist on the mirror side (`node/warrnt/models.py`) and a *separate* `control_room/models.py`. Missing as first-class API objects: `Event`, `Receipt` (only raw list `GET /receipts`), `Evidence` (only inline in `/api/ask`), `Decision` (a string field, no object), `Warrant` (list exists, no typed object), `Agent` (unscoped). |
| **AC9** Event vocabulary emitted | ❌ | None of `tool_call.pending/classified`, `human.required`, `decision`, `execution.started/completed/refused`, `warrant.revoked`, `receipt.committed` exist. Grep confirms zero hits. Transitions currently surface only as receipt rows and `action_log` snapshots. |
| **AC10** Human-hold canonical flow; `expired` is a warrant state | 🟡 | Flow exists: `proxy.py:224-...` `resolve_hold`, node states `pending/approved/denied/expired` (`controlplane.py:68`), `node/scripts/human_hold_evidence.py` + `node/evidence/human_hold-*.{json,md}` exist. The `human.required` **event** is missing (AC9 gap). |
| **AC11** Approve runs upstream once; deny never contacts; revoke expires hold | 🟡 | Real: `POST /api/actions/{id}/approve` runs upstream exactly once and records the human decision before execution (`api.py:311-325`); deny leaves `upstream_contacted=false` (`:327-341`). `node/scripts/console_hold_check.py` (17 checks referenced in AC11) exists. Revoke-expires-pending-hold is covered by `node/warrnt/proxy.py` revoke path + `node/tests/test_human_hold.py`; needs an explicit assertion at the deployed layer. |

### UI (Reflex)

| AC | State | Evidence in tree |
|---|---|---|
| **AC12** Views A–E (COMMAND/ACTIVITY/ACTION INSPECTOR/AUTHORITY/PROOF) | ❌ | `control_room/control_room.py` has **one** page: a header, two static boxes, and a chat box (`:26-48`). The five views do not exist. (The rich screens live in `node/warrnt/console.html` and `index.html`, which are *not* Reflex and are declared non-canonical by the contract §3.) |
| **AC13** UI shows the 8-field ladder | 🟡 | Only as a static string in a box (`control_room.py:33`). Not driven by data. |
| **AC14** One Action is the same object in UI, API, kernel | 🟡 | True *within the node* (same `action_id`/`receipt` in `/api/actions/{id}`, `/api/state.action_log`, receipt — proved by `scripts/ask_evidence.py:130-141`). Not true in the Reflex UI, which renders only `result.answer` strings (`control_room.py:22-24`). |

### Agent trace vs security trace

| AC | State | Evidence in tree |
|---|---|---|
| **AC15** Two traces correlate on `run_id`/`action_id`, never merged | 🟡 | `run_id` is threaded through the kernel (`x-warrnt-run` header, `api.py:262`; `Action.run_id` `controlplane.py:53`). No `/api/activity` endpoint and no agent-side run record, so there is nothing to correlate *from the agent trace* yet. |

### Deployment

| AC | State | Evidence in tree |
|---|---|---|
| **AC16** Railway live, health-checked, deterministic `/health` | ❌ | No `Dockerfile`, `Procfile`, `railway.*`, or nixpacks config anywhere (find returned nothing). `/health` exists locally (`api.py:184`) but carries no mode. |
| **AC17** Public URL tested from outside | ❌ | No deployed URL recorded in the tree. |
| **AC18** Survives restart with state intact (volume `/data` or documented reset) | ❌ | The kernel *is* file-backed and restart-safe (append-only `receipts.jsonl` + `anchors.jsonl` + `issuer.key` under `WARRNT_HOME`, default `./state`; `registry.py:32-52`, `config.py:32-45`). But `WARRNT_HOME` is not pointed at a Railway volume, and the in-memory `ActionStore` (`controlplane.py:80-102`, `MAX_ACTIONS=200`) loses the action log on restart — so AC18 is only half-satisfiable without a volume + persistence decision. |

### Journeys (AC19–AC24)

All six require a **saved external transcript against the deployed URL**. The *capabilities* exist locally:
- AC19 grounded "what is happening" — `controlplane.py:289-297` ✅ logic, ❌ transcript.
- AC20 "why was support-copilot blocked" — `controlplane.py:247-277`, seed warrant `W-4419` denies `crm.bulk_export` (`seed.py:31`) ✅ logic, ❌ transcript + needs `action_id`/class/decision/reason/`upstream_contacted` as one record.
- AC21 "show me the warrant" — `controlplane.py:280-287` ✅ logic, ❌ transcript.
- AC22 "stop support-copilot" → real revoke + receipt — `POST /revoke` (`api.py:353`) ✅ logic, ❌ transcript; `POST /api/agents/{id}/revoke` **missing**.
- AC23 human-hold end-to-end — flow exists, but **not** through the deployed Reflex URL; ❌ transcript.
- AC24 "did it reach the CRM?" from `upstream_contacted` — `controlplane.py:215-245` ✅ logic, ❌ transcript; and the *agentic* answer must be forbidden from answering this from model memory (currently no guard).

### Merge-gate proofs

| AC | State | Evidence in tree |
|---|---|---|
| **AC25** All checks pass | 🟡 | `cd node && pytest` suite exists (11 test files). `human_hold_evidence.py`, `console_hold_check.py`, `console_check.py`, `check_console.py`, `ask_evidence.py`, `sync-node.sh --check`, `doc_qa.py --run` all exist. **Missing:** a control-room runtime test that exercises the agentic path (current `tests/test_control_room.py` only asserts `Literal` shapes — `:4-12`), and Reflex app tests. |
| **AC26** CI green | 🟡 | `.github/workflows/ci.yml` runs node tests, `tests/test_control_room.py`, `py_compile` of `models.py`+`agents.py`, and mirror check. It does **not** install `requirements-control-room.txt` or import Reflex/agents, so the new UI/agent code is essentially untested. |
| **AC27** Browser verification against deployed URL | ❌ | `node/scripts/console_shot.py` + `docs/f1/capture.py` do headless Chromium against *localhost*. No deployed-URL capture. |
| **AC28** GitHub Pages situation documented | 🟡 | `index.html` exists and is honest about `demo feed` (`:195`, `:269-271`), and README §"What works today" separates running vs designed (`README.md:197-242`). But nothing documents *what Pages serves and the link to the live URL* yet. |
| **AC29** Evidence artifacts committed/referenced | 🟡 | Rich precedent exists (`node/docs/`, `node/evidence/`, `docs/f1..f3`, `warrnt-screen/`). The new deliverables (provider call, API transcript, browser run, deployment state) are ❌. |

**Bottom line:** the **kernel + node control plane** (AC7 partial, AC8 partial, AC10, AC11, AC14-in-node, AC18-half, AC19-24 logic) largely **exist**. The **agentic layer** (AC1, AC3, AC4 agent surface, AC5 agent-side, AC6, AC12, AC13, AC15 endpoint) and the **deployment layer** (AC7 missing routes, AC9, AC16, AC17, AC18 volume, AC26 CI coverage, AC27, AC29) are **missing**.

---

## 2. Files to create or modify

**Create**
- `docs/tenet-live-contract.md` — currently untracked; commit the authoritative contract (Step 0).
- `AGENTS.md` edit only (see §6), not a new file.
- `control_room/state_client.py` — one typed client for the node control-plane API so agents/UI share one source.
- `control_room/evidence.py` — agent-side grounding: turns node records into `Evidence` with `action_id`/receipt, and refuses on unknown ids (AC5).
- `control_room/health.py` — centralized mode computation `LIVE|DEGRADED|DEMO` (AC6).
- `control_room/provider.py` — the DeepSeek provider adapter (model id, usage capture) behind the frozen provider seam (AC1).
- `control_room/api.py` — FastAPI control-plane service (or a Reflex custom endpoint module) exposing the missing routes (AC7).
- `control_room/activity.py` — event vocabulary emitter + `/api/activity` backing store (AC9, AC15).
- `control_room/views/command.py`, `views/activity.py`, `views/action.py`, `views/authority.py`, `views/proof.py` — the five Reflex views (AC12, AC13).
- `.github/workflows/deploy.yml` (or `railway.toml`, one of the two) — deploy + health gate.
- `railway.toml` — build/start/healthcheck/volume declaration (§5).
- `tests/test_control_room_agents.py` — positive + negative agentic tests (AC25/D10).
- `tests/test_control_room_api.py` — endpoint contract tests (AC7, AC8).
- `tests/test_control_room_health.py` — LIVE/DEGRADED/DEMO tests (AC6).
- `scripts/tenet_live_journeys.py` — runs AC19–AC24 against a URL, saves transcripts (AC29).
- `scripts/tenet_browser_verify.py` — headless-Chromium check against the deployed URL (AC27).
- `evidence/agentic/` — provider response, API transcript, browser run, deployment state (AC29).

**Modify**
- `AGENTS.md` — record the D6 unfreeze (its own commit, §6).
- `control_room/agents.py` — swap the `openai` gate for the provider seam and use the evidence client (AC1, AC3, AC5).
- `control_room/control_room.py` — replace the single page with the five-view shell (AC12, AC13).
- `control_room/models.py` — add `Event`, `Receipt`, `Decision` as first-class canonical objects (AC8), aligned to the node's `Action`.
- `rxconfig.py` — production config: `Env.PROD`, backend/frontend host+port from env, health route (AC16).
- `requirements-control-room.txt` — add the DeepSeek client dependency and uvicorn/fastapi pins already implied (AC1, AC16).
- `node/warrnt/api.py` — add `/api/overview`, `/api/activity`, `/api/actions/pending`, `/api/agents`, `/api/agents/{id}/revoke`, and the mode field on `/health` (AC6, AC7, AC15).
- `node/warrnt/controlplane.py` — emit the AC9 event sequence at each transition; persist `ActionStore` to `WARRNT_HOME` (AC9, AC18).
- `node/warrnt/console.html` — surface the new mode + activity feed (AC6, AC9) **only if** the kernel change is mirrored upstream first (see §6).
- `scripts/sync-node.sh` — bump the pinned SHA **after** the kernel change lands upstream (D2/mirror contract).
- `.github/workflows/ci.yml` — install control-room deps, run the new tests, `doc_qa`, mirror check (AC25, AC26).
- `README.md` — refresh the running-vs-designed split with the deployed URL (D12, AC28).
- `index.html` — state it is a static showcase and link the Railway URL (AC3/§3, AC28).
- `docs/tenet-live-contract.md` — the contract file itself is tracked here; no content change to criteria.

**Hard constraint on `node/`:** `node/` is a verbatim mirror (see `node/MIRROR.md`, `scripts/sync-node.sh`); it must **not** be edited by hand. Any kernel change (AC6/AC7/AC9/AC18) goes through the `warrnt` repo workflow, then `sync-node.sh` bumps the pin. Editing `node/` directly fails `sync-node.sh --check` and contradicts the contract §6.

---

## 3. Sequencing — each step independently verifiable

**Step 0 — Commit the contract.** Land `docs/tenet-live-contract.md` so the gate exists in git.
*Verify:* `git ls-files docs/tenet-live-contract.md` prints the path.

**Step 1 — D6 unfreeze commit (its own commit, §6).** Record the decision change before any DeepSeek code exists.
*Verify:* `git show --stat HEAD` shows only `AGENTS.md`; `git log -1 --format=%s` matches the unfreeze subject.

**Step 2 — Kernel control-plane routes (upstream `warrnt` repo).** Add the missing endpoints + event vocabulary + `/health` mode, merge there, then bump the mirror pin here.
*Verify:* `bash scripts/sync-node.sh --check` and `cd node && python -m pytest -q`.

**Step 3 — Provider seam (no live call yet).** `control_room/provider.py` with an injectable client; unit tests use a fake.
*Verify:* `python -m pytest -q tests/test_control_room_health.py tests/test_control_room_agents.py` (with the fake) — no network.

**Step 4 — Grounded evidence + refusal.** `control_room/evidence.py` binds every claim to `action_id`/receipt and refuses unknown ids.
*Verify:* same pytest file, negative cases (unknown id ⇒ explicit refusal).

**Step 5 — Reflex five views.** Wire COMMAND/ACTIVITY/ACTION INSPECTOR/AUTHORITY/PROOF to the client.
*Verify:* `python -m pytest -q tests/test_control_room_api.py tests/test_control_room.py` and `python -m py_compile control_room/*.py control_room/views/*.py`.

**Step 6 — Real DeepSeek call.** Turn on the provider with `DEEPSEEK_API_KEY` present; capture one provider response (status + model id + usage).
*Verify:* `python -c "import os;print('PRESENT' if os.getenv('DEEPSEEK_API_KEY') else 'ABSENT')"` → `PRESENT`; save the redacted provider response to `evidence/agentic/`.

**Step 7 — Journeys + browser against deployed URL (after Step 8 gives a URL).**

**Step 8 — Railway deploy.** Service up, health-checked, volume mounted.
*Verify:* `curl -sf "$TENET_URL/health"`; `curl -sf "$TENET_URL/api/overview"`.

**Step 9 — Deployed journeys + browser + evidence commit.**
*Verify:* `python scripts/tenet_live_journeys.py --url "$TENET_URL"` and `python scripts/tenet_browser_verify.py --url "$TENET_URL"`.

**Step 10 — CI coverage + README/Pages honesty.**
*Verify:* `python -m pytest -q node/tests tests` and `python scripts/doc_qa.py --node node --run`.

---

## 4. Exact verification command per step

```bash
# Step 0
git ls-files docs/tenet-live-contract.md

# Step 1 (unfreeze is its own commit)
git show --stat HEAD | grep -q '^ AGENTS.md' && git log -1 --format='%s'

# Step 2 (kernel changed upstream, mirror re-pinned here)
bash scripts/sync-node.sh --check
cd node && python -m pytest -q && cd ..
python -m pytest -q node/tests

# Step 3 (provider seam, no network)
python -m pytest -q tests/test_control_room_health.py tests/test_control_room_agents.py

# Step 4 (grounding + refusal)
python -m pytest -q tests/test_control_room_agents.py -k 'grounded or refusal or unknown'

# Step 5 (views + compile)
python -m py_compile control_room/*.py control_room/views/*.py
python -m pytest -q tests/test_control_room.py tests/test_control_room_api.py

# Step 6 (key presence only — never the value)
python -c "import os;print('PRESENT' if os.getenv('DEEPSEEK_API_KEY') else 'ABSENT')"

# Step 7 (local end-to-end before deploying)
python scripts/tenet_live_journeys.py --url http://127.0.0.1:8000

# Step 8 (deployed service)
curl -sf "$TENET_URL/health" | python -m json.tool
curl -sf "$TENET_URL/api/overview" | python -m json.tool
curl -sf "$TENET_URL/api/activity" | python -m json.tool

# Step 9 (external verification against the deployed URL)
python scripts/tenet_live_journeys.py --url "$TENET_URL"
python scripts/tenet_browser_verify.py --url "$TENET_URL"

# Step 10 (full gate)
cd node && python -m pytest -q && cd ..
python -m pytest -q node/tests tests
python scripts/check_console.py
python scripts/ask_evidence.py
python scripts/sync-node.sh --check
python scripts/doc_qa.py --node node --run
```

---

## 5. Railway deployment shape

**Service boundary.** The **kernel is its own service**, not embedded in the Reflex service. Rationale: the contract §3 table lists the Railway service (Reflex + control-plane) and `node/warrnt` (kernel) as two rows, both canonical; the mission forbids the agent runtime becoming an enforcement dependency (`docs/pr14-control-room-v2-hermes-brief.md` §"Architecture target"). So:
- **Service A — `warrnt-kernel`:** the FastAPI node (`node/warrnt/api.py`), the sole authority. Owns the volume.
- **Service B — `tenet-control-room`:** Reflex + the control-plane/agentic surface; talks to Service A over HTTP via `WARRNT_CONTROL_API`. Never imports the kernel as a library (preserves the boundary and the mirror).

**Start command.**
- Service A: `uvicorn warrnt.api:create_app --factory --host 0.0.0.0 --port $PORT` (or `python -m warrnt serve` — `node/warrnt/cli.py:main`).
- Service B: Reflex prod backend, e.g. `reflex run --env prod --backend-port $PORT` (exact flag set confirmed at Step 8 against the installed Reflex version).

**Health check path.**
- Service A: `GET /health` → deterministic JSON (`api.py:184`), extended in Step 2 with a mode field.
- Service B: `GET /health` → reports `LIVE` / `DEGRADED` / `DEMO` (AC6), which itself reflects Service A's health.

**Volume for state.** Mount a Railway volume at `/data` and set `WARRNT_HOME=/data` so `receipts.jsonl`, `receipts.*.jsonl.rotations.jsonl`, `anchors.jsonl`, and `issuer.key` survive restarts (satisfies AC18 for the receipt chain/anchor). Additionally `ActionStore` persistence (Step 2) writes its ledger under `WARRNT_HOME` so the action log survives too; if the operator prefers a documented reset instead of full persistence, that reset must be stated in the README (AC18 allows "or documented reset").

**Env vars — BY NAME ONLY (no values here):**
- Service A (kernel): `WARRNT_HOME`, `WARRNT_HOST`, `WARRNT_PORT`, `WARRNT_ADMIN_TOKEN`, `WARRNT_DEV`, `WARRNT_UPSTREAM`, `WARRNT_ISSUER_KEY`, `WARRNT_ANCHOR`, `PORT`.
- Service B (control room): `WARRNT_CONTROL_API`, `WARRNT_ADMIN_TOKEN`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `PORT`, `TENET_ENV`, `TENET_FALLBACK_MODE`.
- Shared/CI: `TENET_URL`, `RAILWAY_TOKEN`, `RAILWAY_PROJECT_ID`, `RAILWAY_SERVICE_ID`.

`DEEPSEEK_API_KEY` is referenced **by name only**; it is never printed, logged, returned, embedded, or placed in any artifact. The only admissible statement about it is `PRESENT` / `ABSENT`.

---

## 6. Conflicts with frozen decisions (AGENTS.md)

| # | Frozen decision | Conflict | Resolution |
|---|---|---|---|
| **C1** | **D6** — no paid API on the critical path; semantic layer targets a local Ollama model; a cloud model may never be a *requirement*. | The operator brief ("Cline is the coding executor (deepseek-chat)"; contract AC1 "DeepSeek is called for real") and AC3 require a real DeepSeek call in the agentic layer. | **Recorded unfreeze** (below). |
| **C2** | **D4** — deterministic first, semantic second; the semantic layer is *local*. | Placing DeepSeek in the semantic slot is a provider change to D4's "local model", even though the ordering (deterministic → semantic) is preserved because WARRNT still runs first. | Fold the provider wording into the same unfreeze; D4's *ordering* is explicitly kept. |
| **C3** | **D3** — one control catalog is the single source of truth for permitted models. | The permitted-models list must name the DeepSeek model; hardcoding a model id in `control_room/provider.py` violates D3. | Model id comes from the catalog via `DEEPSEEK_MODEL`, not a literal in code. No unfreeze needed if done this way; flagged so it is not skipped. |
| **C4** | **D7** — token/cost/compute-time budgets enforced at request time. | A paid provider introduces real cost, so budgets must be enforced before the model call (not just displayed). | Enforce per-agent/per-model budget in the provider seam *before* dispatch; record the block. No unfreeze; a new requirement. |
| **C5** | **D10** — a control without both a positive and a negative test is incomplete. | New controls (provider, mode, budget, event vocabulary) need positive + negative tests. | Covered by `tests/test_control_room_*.py` in §2/§3. |
| **C6** | **D2 / mirror contract** — `node/` is a verbatim mirror; do not edit here; Prelint tooling stays off `main`'s runtime. | AC6/AC7/AC9/AC18 require kernel changes, and editing `node/` in place fails `sync-node.sh --check`. | Change the kernel in the `warrnt` repo, then bump the pin here. Any Prelint steps stay on the `prelint` branch (D2). |
| **C7** | **D13** — a frozen interface changes only by a recorded unfreeze, as its own commit; fix the vocabulary before adding a control. | AC9's ten event names and AC8's new objects extend the vocabulary. | Treat the event vocabulary addition as part of the same recorded unfreeze family; the vocabulary change is its own commit before the controls that consume it. |
| **C8** | **D1** — `main` carries only the deliverable. | Deployment/CI artifacts for the live service must live on `main`; Prelint stays on `prelint`. | Keep `railway.toml`/deploy on the delivery branch; no Prelint runtime dependency. |

### Proposed exact recorded unfreeze for D6 (its own commit)

**Commit subject:** `docs(agents): unfreeze D6 — permit DeepSeek as the semantic-layer provider in the agentic control room`

**Reason (to be recorded verbatim in `AGENTS.md`):**
> The operator brief for PR-14 requires a real provider call in the agentic layer (acceptance criterion AC1), and the agentic layer is not the enforcement path. The kernel remains the sole authority and the deterministic layer still runs first. The original D6 prose — "everything runs on local models, no paid API is available or permitted on the critical path" — is therefore relaxed *only* for the agentic/assistive surface, and only when the deterministic layer has already passed.

**Scope wording to insert (exact text):**
> **D6 (as amended) — Everything on the *enforcement* path runs on local models.** The WARRNT kernel and the control layer's deterministic checks never depend on a paid API: pattern checks (PII, secrets, authentication, permitted-model checks) run before any model call, and the semantic layer targets a locally served model (Ollama). The **agentic/assistive layer only** (the orchestrator and its three specialists) may call a paid provider — DeepSeek — and only on input the deterministic layer has already passed and only when `DEEPSEEK_API_KEY` is PRESENT. That provider is never a requirement for the system to function: with the key ABSENT the agentic layer reports `DEMO`/`DEGRADED` per AC6 and the enforcement path is unchanged. A cloud model may never be a requirement for the enforcement path, and no model output is ever an authorization decision. The permitted provider/model list lives in the control catalog (D3), and its request-time budgets are enforced (D7).

**Consumers to update (each named, each in this unfreeze review):**
1. `AGENTS.md` — the D6 text above (the unfreeze commit itself).
2. `control_room/agents.py` — replace the `OPENAI_API_KEY` gate (`:63`) with the provider seam.
3. `control_room/provider.py` — new adapter honoring the amended D6 (local default, DeepSeek only for the agentic surface).
4. `requirements-control-room.txt` — add the DeepSeek client; keep Ollama/local path documented.
5. `README.md` — add the enforcement-vs-agentic split to "What works today" (D12 honesty).
6. `docs/pr14-control-room-v2-hermes-brief.md` / `docs/tenet-live-contract.md` — cross-reference the amended D6 so the brief and the contract cite the same decision number.
7. CI (`ci.yml`) — assert the enforcement path imports no paid provider.

**Constraints of the unfreeze:** it is **one commit of its own**, it states the reason, the exact decision text changed (D6), and every consumer above; it does **not** touch D4's ordering, D13's vocabulary rule, or D6's "no cloud model may be a requirement for the enforcement path" invariant.

---

## 7. Secrets handling

- `DEEPSEEK_API_KEY` is referenced **by name only**. No value is printed, invented, or placeholdered anywhere in this plan, in code, in tests, in logs, in responses, in the frontend, in CI, or in evidence.
- The only admissible statement is presence: `python -c "import os;print('PRESENT' if os.getenv('DEEPSEEK_API_KEY') else 'ABSENT')"` (contract §2).
- Same rule for `WARRNT_ADMIN_TOKEN`, `WARRNT_ISSUER_KEY`, `RAILWAY_TOKEN`, and every other variable in §5: names only, never values.
- Saved provider evidence records **status + model id + usage**, never the key and never a request/response body carrying personal data.

---

## Open questions for the operator (blocking one step, not the plan)

1. **Production runtime for the missing routes (AC7).** Put `/api/overview`, `/api/activity`, `/api/actions/pending`, `/api/agents`, `/api/agents/{id}/revoke` in the **kernel** (`node/warrnt/api.py`, requires an upstream `warrnt` change + mirror pin bump) or in the **control-plane service** (`control_room/api.py`, no mirror change)? This choice decides whether Step 2 touches the mirror.
2. **AC18 persistence depth.** Is a mounted `/data` volume with the persisted `ActionStore` required, or is a documented reset acceptable? AC18 permits either.

All six remaining journeys (AC19–AC24) and AC17/AC27 are blocked only on a deployed URL, which is why deploy is sequenced before evidence capture.
