# ACT-5b CONTRACT — make the hero RENDER the real payload (round 2, defect fix)

ROLE: You are the implementer on the TENET repo, second round on branch
`feat/live-security-trace`. Round 1 (ACT-5) is in the working tree, uncommitted. You change
code; you do not renegotiate scope. The defect below is MEASURED, not suspected.

TASK: The hero renders dashes because the page reads key paths the projection does not emit.
Align `index.html` to the real `/api/live-trace` payload, and replace the false-green test
with a test that renders the page in a real browser.

CONTEXT: (measured by the orchestrator on the round-1 tree, local instance PORT=8099)
`GET /api/live-trace` returns exactly (leaves):
```
run_id action_id timestamp origin agent agent_role principal on_behalf_of entitlements[]
scope[] action.tool action.intent action.class action.args.{keys,sha256,values_withheld}
checks.identity.{ok,detail} checks.entitlement.{ok,right} checks.warrant.{id,state,sig_ok,
ttl_remaining} checks.policy.{ok,detail} decision reason decided_by upstream.contacted
upstream.http_status upstream.endpoint upstream.value upstream.response_sha256
upstream.latency_ms receipt_id model.provider model.model_served model.trace_id model.calls
model.tokens incomplete[] ; plus root-level llm_authority, authority_source, mode
```
`index.html` reads (grep of the round-1 file): `t.request?.tool`, `t.request?.args`, `t.ts`,
`t.boundary_crossed`, `t.warrant.warrant_id`, `t.warrant.scope`, `t.warrant.state`,
`t.warrant.delegated_by`, `t.upstream?.target`, `t.upstream?.method`,
`t.model.model`, `t.model.llm_authority`, `c.authorized_before_execution`,
`c.receipt_present`, `c.warrant`. **None of those paths exist in the payload.**

Real rendered DOM (chromium `--headless --dump-dom --virtual-time-budget=6000`,
`http://127.0.0.1:8099/` after one self-check), text of the hero card:
```
01 · Live security trace LIVE SECURITY TRACE fx-trader → tool · Agent fx-trader
Requested action — {} Decision allow Reason read-only · live reference rate · in scope ·
class observe Authority tenet-kernel Warrant no warrant in record Data boundary Boundary
crossing is unproven in the record. Upstream contact not specified · yes Receipt 0c32692c
Checks ? Authorized before execution ? Boundary crossed ? Warrant ? Receipt Recorded —
Model (proposes only) — · trace — · llm_authority: unknown
```
That is the mentor's original complaint ("the centre promises a decision and shows nothing")
with a better title: 6 of 12 rows are dashes while the kernel holds real evidence
(`A-0002 · fx-trader · fx.read_rate · ALLOW · W-9001 active · HTTP 200 · receipt 0c32692c`).
Round 1's tests passed because they asserted the page's TEXT, not the rendered result —
a source-reading test. That is why this round exists.

ИКР: a jury member screenshots the hero and every line on it is real evidence from the last
enforced action: agent, tool, ALLOW, the four checks as ✓, warrant id+state, "upstream
contacted · HTTP 200", the receipt. No dashes where the kernel has data; `unknown` only where
the record genuinely has nothing (intent, identity, principal).

ACCEPTANCE CRITERIA:

AC1 — Every path the page reads exists in the payload. The rendering uses these exact paths:
`t.agent` · `t.action.tool`, `t.action.class`, `t.action.args` · `t.decision`, `t.reason`,
`t.decided_by` · `t.checks.entitlement.ok|right` · `t.checks.warrant.id|state|sig_ok|
ttl_remaining` · `t.checks.policy.ok|detail` · `t.checks.identity.ok|detail` ·
`t.upstream.contacted`, `t.upstream.http_status`, `t.upstream.endpoint`, `t.upstream.value`,
`t.upstream.response_sha256`, `t.upstream.latency_ms` · `t.receipt_id` ·
`t.model.model_served`, `t.model.trace_id`, `t.model.llm_authority` (root `llm_authority`
when the trace block omits it) · `t.timestamp` (render ISO+local time, not the raw float) ·
`t.origin` · `t.incomplete` · `t.principal`, `t.on_behalf_of`. No `request`, no `ts`, no
`boundary_crossed`, no `t.warrant` object, no `authorized_before_execution`, no
`receipt_present`.

AC2 — The four checks render from `checks`: identity → `?`/"not recorded" when `ok` is null;
entitlement → ✓ + right; warrant → ✓ id + state + `sig_ok` + ttl; policy → ✓ + detail.

AC3 — Boundary crossing has three honest states, derived ONLY from `upstream.contacted`:
true → "CONTACTED · HTTP <status> · <endpoint> · value <v> · sha <first 8>…"; false →
"NOT CONTACTED — the decision held the boundary"; null/absent → "NOT PROVEN in the record".
`decision == "allow"` must never render as a crossing on its own.

AC4 — Add `const TRACE_KEYS = { ... }` to the page: the declared list of payload paths the
page reads (dotted paths, `[]` for arrays). A test proves the declaration covers the payload:
run the real projection (`kernel.live_trace()` against the repo's own kernel after one
scenario) → flatten its leaves → assert every declared path exists and that every path the
render code interpolates is declared. Data↔data contract, not a grep of prose.

AC5 — `scripts/check_rendered_trace.py`: boots nothing itself; takes a URL (default
`http://127.0.0.1:8099/`), drives `/usr/bin/chromium --headless --no-sandbox --disable-gpu
--virtual-time-budget=6000 --dump-dom`, extracts the `#traceCard` text and asserts, for a
served instance that has just run one self-check: the text contains the agent id, the tool,
`ALLOW`, `W-9001`, `HTTP 200`, the receipt id from `/api/live-trace`, contains no
`Requested action —`, no `no warrant in record`, no `Checks ?`, and prints the extracted hero
text on success. Exit 0/1. Skip cleanly (exit 2 + message) if chromium is absent.
This script is the acceptance tool — the orchestrator runs it; you must show its real output.

AC6 — Do NOT delete the round-1 tests, but the "hero is the trace" test must stop asserting
source text: replace it with AC4's contract test. A test that reads index.html's prose to
claim the hero works is the defect this round fixes.

AC7 — Keep everything else from ACT-5 intact (routes, rate limit, startup warm trace, honest
empty state, model strip, no credential in the page, `llm_authority: false`,
`authority_source: "tenet-kernel"`).

AC8 — Evidence packet, real output only:
```
cd /root/work/tenet-live-trace
/root/work/tenet-cp-venv/bin/python -m pytest -q 2>&1 | tail -3
PATH=/root/work/tenet-cp-venv/bin:$PATH PORT=8099 TENET_STATE_DIR=/tmp/tenet-5b-state bash scripts/serve_tenet.sh >/tmp/tenet-5b.log 2>&1 &
sleep 6 ; curl -s -X POST localhost:8099/api/scenario/self-check >/dev/null ; sleep 1
/root/work/tenet-cp-venv/bin/python scripts/check_rendered_trace.py http://127.0.0.1:8099/
git add -A && git commit -m "feat: live security trace hero renders the kernel's real evidence"
git log --oneline -1 ; git status --short
```
Kill the server after the check. Commit on `feat/live-security-trace`; do NOT push.

CONSTRAINTS:
- Read the round-1 files before editing (`index.html`, `control_plane/kernel.py`,
  `control_plane/app.py`, `tests/test_live_trace.py`).
- No fabricated fallback values: a missing field renders `—`/`unknown`/`not recorded`; never
  a plausible default, never a synthetic event.
- Keep the honest empty state and the `incomplete` list rendered.
- Multi-file, one pass, then verify. Do not touch `control_plane/kernel.py`'s projection shape
  unless a path is genuinely wrong — the payload is the contract here.

NON-GOALS:
- No new endpoint, no schema change, no animation, no decorative chart.
- No push, no merge to `main`, no deploy, no Railway change.
- No rewrite of panels 03/04 beyond what the shared renderer needs.

OUTPUT FORMAT: one commit on `feat/live-security-trace` + the AC8 block pasted verbatim
(commands and real stdout, including the extracted hero text), the path-mapping table
(before → after), and any evidence gap named.

SELF-CHECK:
1. Did you render the page in chromium and paste the text? (required)
2. Every path in the render code appears in the payload — proven how?
3. Does a deny/no-crossing case still render "NOT CONTACTED / NOT PROVEN"? (test name)
4. Is any dash left where the kernel HAS data? (list them or say none)
5. Full suite green, count pasted? Branch has exactly one new commit?
