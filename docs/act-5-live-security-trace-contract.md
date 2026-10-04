# ACT-5 CONTRACT — LIVE SECURITY TRACE (the empty centre of the Control Room)

ROLE: You are the implementer on the TENET repo. You change code; you do not decide scope.
The contract is the scope. The orchestrator (Indra's Hermes) verified every number below
against the LIVE deployment and this source tree; treat them as facts, not questions.

TASK: Turn the currently empty hero area of the Control Room into a LIVE SECURITY TRACE
(agent -> TENET checks -> decision -> boundary crossing -> proof), fed by REAL kernel
evidence, and make the live deployment able to produce that evidence without a credential
ever reaching the browser. Model & Resources becomes a secondary strip.

CONTEXT: (measured 2026-10-03, base commit 00960ca = origin/main, index.html 14376 bytes):

1. The Control Room hero («01 · Security decision») renders
   "Waiting for a real agent action…" with every field "—" because
   `GET /api/security-events` returns `{"count":0,"events":[]}`. This is the empty centre a
   HackYeah mentor flagged: the largest block on screen promises a decision and shows nothing.
2. Root cause: nothing in the deployment ever produces a kernel action. The only trigger,
   `POST /api/demo/run`, requires the `x-warrnt-admin` header, and by design no credential
   reaches the browser. So in production the kernel records zero actions, and the honest
   empty state is what the jury sees.
3. Proof that the product CAN fill the screen (measured live by the orchestrator):
   `POST /api/demo/run` with the admin token -> `{"scenario":"fx.read_rate","agent":"fx-trader",
   "run_id":"demo-efb9e8ee","action_id":"A-0001","decision":"allow",
   "reason":"read-only · live reference rate · in scope · class observe","executed":true,
   "upstream_contacted":true,"execution_result":{"rows":1,"outcome":"ok",
   "endpoint":"https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD","http_status":200,
   "response_sha256":"f63f64a5…","value":1.1225,"latency_ms":45.179,"boundary":"outbound"},
   "receipt":"4f343b25","tool":"fx.read_rate"}` and immediately after,
   `GET /api/security-events` -> `count: 1` with the same action as a full SecurityEvent
   (`event_id:"A-0001"`, `action_class:"observe"`, `warrant:"W-9001"`, `warrant_state:"active"`,
   `policy:"the node decides"`, `decision:"allow"`, `upstream_contacted:true`,
   `upstream_call_id:null`, `actor:null`, `intent:null`, `decision_id:null`).
4. Consequences of (3) that this contract must fix, not hide:
   - `actor`, `intent`, `decision_id`, `upstream_call_id` are null in the event, so the screen
     cannot show WHO proposed, ON WHOSE BEHALF, and WHICH boundary attempt happened.
   - The identity/authority evidence exists but only in `GET /api/agents`
     (`principal`, `on_behalf_of`, `entitlements`, `scope`) and `GET /api/warrants`
     (`scope`, `state`, `sig_ok`, `ttl_remaining`); nothing joins them to the decision.
   - State lives in `TENET_STATE_DIR` (default `/tmp/tenet-state`), so a redeploy wipes the
     record and the centre is empty again on the next jury screen.
5. Second (already fixed upstream, keep it fixed): the Model & Resources strip showed
   `0/0 input/output tokens` because the service held a dead `DEEPSEEK_API_KEY`; the live strip
   now shows `22 calls · 942 tokens · provider trace 200`. Do not regress that.

ИКР (ideal final result): a jury member looking at the centre for five seconds sees a real
chain — agent, on whose behalf, what it asked for, what TENET checked, the decision, whether
data actually left, and the receipt — and never needs the source code, the mentor's annotation,
or a fake animation to understand it. Zero fabricated events: absent evidence renders as
UNKNOWN / NOT PROVEN / INCOMPLETE, never as success.

ACCEPTANCE CRITERIA:

AC1 — `GET /api/live-trace` (read-only, no credential) returns the LAST real action composed
with its authority evidence, shape:
```
{"trace": {...}|null, "authority_source": "tenet-kernel", "llm_authority": false, "mode": "live"}
```
`trace` fields: `run_id, action_id, timestamp, origin, agent, agent_role, principal,
on_behalf_of, entitlements[], scope[], action{tool,intent,class,args}, checks{identity,
entitlement, warrant{id,state,sig_ok,ttl_remaining}, policy}, decision, reason,
decided_by, state, executed:true|false|null, upstream{contacted,http_status,endpoint,value,
response_sha256, latency_ms}|null, receipt_id, model{provider,model_served,trace_id,calls,
tokens}, incomplete[]`. When no action exists, `"trace": null` and nothing else is invented.

`state` is the action row's own resolved lifecycle state, verbatim (`"approved"`, `"denied"`,
`"pending"`, `"decided"`, …) — never mapped or renamed; `null` (and named in `incomplete`) when
the row carries none. `executed` is `true` only when the record itself proves the call ran (the
same evidence the crossing is proven from: an execution result with a real `http_status`),
`false` when the record proves it did NOT run (a denial: the row carries an execution result and
no crossing), and `null` (named in `incomplete`) when the record does not say.

`decided_by` (ACT-7d): the real resolver of a person-resolved hold is named verbatim from the
row's own `decided_by`; where the kernel alone decided it reads `"tenet-kernel"`. No name is
invented either way.
AC1b — every field whose evidence is missing is `null` AND its name appears in `incomplete`.

AC2 — Honest boundary rule: `upstream.contacted` is true ONLY when the action carries an
execution result with an `http_status`; `decision == "allow"` alone must never produce
`contacted: true`. A deny with no attempt yields `contacted: false` and no `http_status`.

AC3 — `POST /api/scenario/self-check` (no credential, the browser's only trigger):
fixed scenario only (agent `fx-trader`, tool `fx.read_rate`, args `{"base":"EUR",
"symbols":"USD"}` — no request-supplied tool/args at any point), reads the agent token
in-process from the kernel registry exactly as `/api/demo/run` does, runs a REAL crossing, and
returns the AC1 `trace` object. Rate limit: at most one run per 3 s -> `429
{"error":"rate limited","retry_after_s":N}`. No live upstream configured -> `503
{"error":"no upstream configured"}` and NO record written. `run_id` prefix `selfcheck-`; the
action metadata carries `origin: "operator self-check"`.

AC4 — Startup warm trace: in the app lifespan, if the kernel holds zero actions AND a live
upstream is configured, the control plane runs the same fixed scenario once (`run_id` prefix
`startup-`, `origin: "startup self-check"`). A failure logs one line and never blocks startup.
Rationale: the first screen after any deploy must not be blank; the label states plainly that
the control plane ran its own boundary self-check.

AC5 — Frontend (`index.html`, static, polls every 2 s):
(a) hero title "LIVE SECURITY TRACE"; the chain Agent -> on-behalf-of/principal ->
    requested action -> TENET checks (identity / entitlement / warrant / policy, each ✓, ✗,
    or `?` when not recorded) -> decision badge (ALLOW / DENY / HUMAN / REDACT / REVOKED,
    visually dominant) -> boundary crossing stated explicitly ("Upstream contacted · HTTP 200
    · EUR/USD 1.1225 · sha f63f64a5…" vs "Upstream not contacted" vs "Crossing not proven")
    -> receipt id;
(b) `incomplete` fields render as an explicit "INCOMPLETE: <names>" line, never hidden;
(c) empty state: "No enforced action recorded yet — the trace appears after the first real
    call." plus one button "Run boundary self-check" (POSTs AC3, then refreshes);
(d) Model & Resources is demoted to a compact secondary strip (same numbers, ~1 line);
(e) the page still contains NO token, NO prompt text, NO API key, and the revoke control stays
    behind the admin credential exactly as today.

AC6 — `POST /api/demo/run` keeps requiring `x-warrnt-admin`; nothing else is loosened. No new
credential is introduced; `llm_authority: false` remains in every payload.

AC7 — Tests: `tests/test_live_trace.py` proves AC1 (no action -> `trace: null`), AC2 (allow
without `http_status` -> not contacted + named in `incomplete`), AC3 (429 on the second
immediate call; 503 without upstream; a successful call writes exactly one new action), AC5(e)
(the served HTML contains no `WARRNT_ADMIN` value, no agent token, no `sk-`), and AC4 (startup
path is idempotent: with an existing action it runs nothing). Existing suites stay green.

AC8 — Evidence packet, pasted verbatim into the final report (real output, not summaries):
```
cd /root/work/tenet-live-trace
python -m pytest -q tests/test_live_trace.py ; python -m pytest -q 2>&1 | tail -3
# local live proof (the contract's own scenario, real upstream):
PORT=8099 bash scripts/serve_tenet.sh > /tmp/tenet-local.log 2>&1 &
sleep 4
curl -s localhost:8099/api/live-trace
curl -s -X POST localhost:8099/api/scenario/self-check
curl -s -X POST localhost:8099/api/scenario/self-check   # expect 429
curl -s "localhost:8099/api/security-events?limit=3" | head -c 600
git log --oneline -1 ; git status --short
```
Report: files changed, API changes, test output, the curl bodies, and any remaining
evidence gap by name.

CONSTRAINTS:
- Authority stays in the kernel: `authority_source: "tenet-kernel"`, the model proposes only.
  Never make a projection field look like a permission.
- Do not rename or move internal compatibility names (`warrnt/*`, `node/warrnt`, pin,
  `W-xxxx`, `A-xxxx`) — the product is called TENET, the dependency namespace stays `warrnt`.
- Do not weaken a gate to make a demo pass: no token in the page, no fake event, no invented
  http_status, no "unknown" rounded to success.
- Keep the honest empty state; never auto-fabricate activity on a timer.
- Multi-file, plan-first: read the files you change before writing (app.py, kernel.py,
  config.py, index.html, tests/*), then implement in one pass.
- The fixed scenario args are constants in the server, never read from the request body.
- Record the outcome ledger row at the end:
  `/opt/hermes/venv/bin/python3 /root/.hermes/scripts/agentic_runs.py log --class coding
   --lane deepseek-chat --effort low --rounds 1 --usd 0 --verified yes --accepted yes
   --artifact docs/act-5-live-security-trace-contract.md`

NON-GOALS:
- No decorative animation, no synthetic activity feed, no CPU/token charts.
- No global rename `warrnt -> tenet`.
- No new database, no schema migration, no push/merge to `main`, no deploy from this task.
- Do not touch the deployed Railway service, its variables, or the provider key.
- Do not rewrite the Agents / Warrants / Live-activity / Details panels beyond what AC5 needs.

OUTPUT FORMAT: a single commit on branch `feat/live-security-trace` (branch already exists,
base 00960ca) with a conventional message (`feat: live security trace in the control room`),
then the AC8 evidence block pasted verbatim in your final message: commands + real stdout,
files changed with line counts, API changes, remaining gaps. Do NOT push; the orchestrator
pushes after external verification.

SELF-CHECK before you report done:
1. Did AC1/AC1b hold with `trace: null` when the kernel is empty? (test output)
2. Is there ANY path where `contacted` is true without an `http_status`? (name it or say none)
3. Does the served page contain a token? (`grep -n "WARRNT_ADMIN\|sk-\|warrnt_admin" index.html`)
4. Did the local run produce a REAL row in `/api/security-events`? (curl body)
5. Did the full suite stay green? (tail of pytest)
If any answer is "no" or "not verified", say so in the report — a false claim here is worse
than an incomplete task.
