# TENET — the AI control layer

> **No warrant, no action.**

**Read the two names as one sentence.** *TENET* is the name of the **idea** — set on 2026-10-03,
with the evidence and the record of what came before it in
[`docs/concept-form-and-name.md`](docs/concept-form-and-name.md). The node that implements it
ships here as the product **TENET**; the kernel it drives is the Python package **`warrnt`**, because the demo, the video and the submission
were built under it and a rename at this point would be a paper change rather than a code change.
*TENET* is Latin, "it holds": the order holds the action, and the word reads the same forwards and
backwards — which is what the record must do, because a rewrite has to show. It is the palindrome
at the centre of the **Sator Square**, the oldest word square known (Pompeii, before AD 79).
Carried before it and kept on the record: **ADNOT** (*adnotare*, "to note down") was the Stage-3
name, dropped by the founder's decision on 2026-10-03 although it was the cleanest name on the
board; TESTIS (dictionary meaning), SURETY / WARDEN / VERDICT / ATTEST (live class 9/42 marks),
VOWEN / SIGLUM (live companies) were rejected earlier; **ADNOT and PRAES stay as the clearable
spares**. Honest caveat, measured today: **TENET is not a clearable product mark** (USPTO
99151322 live, TENET TECHNOLOGIES, Tenet Apps FZCO, the 2020 film), `tenet.ai` and npm / PyPI are
taken. `tenet.dev` and `tenet.io` resolve to nothing and are **not registered**.

Every action an AI agent takes carries a signed, scoped warrant — or it does not run.
No warrant, no action. This is the one thing that turns "we deployed agents" into
"we can stop one and prove why".

HackYeah 2026 · Partner task **AI Control Layer** (Goldman Sachs).

---

## Watch the demo (40 s)

▶ **[`warrnt-demo-40s.mp4`](warrnt-demo-40s.mp4)** — the 3:47 scenario end to end, 1920×1080,
no audio. An agent asks for 12 000 rows of customer PII; the layer **denies the call before it
runs**, zero rows leave the perimeter; the denial lands in the hash-chained receipt log; one
`/revoke` halts the agent in **0.8 s**. Frames are rendered deterministically, not screen-captured
— the rebuild kit is in [`warrnt-demo/`](warrnt-demo/). Slides:
[`warrnt-presentation.pdf`](warrnt-presentation.pdf).

Live console: open [`index.html`](index.html) (no dependencies, `file://` works — see [Run it](#run-it)).

---

## The problem

Enterprises are shipping agents faster than they can govern them. An agent runs under
production credentials, moves data, calls tools — and when something goes wrong at 3:47
in the morning, the team finds out at 9:15 from a log they cannot trust and cannot stop.

The gap is not visibility. Everyone has visibility. The unanswered question is:

**Who authorised this agent action — and where is the proof?**

A monitor tells you what already happened. It does not grant authority, and it cannot
revoke it. You can watch an agent work and still be unable to fire it.

The hidden fear is not the breach. It is the silence after: sitting in front of a
regulator, not knowing what your own agent did three minutes ago. Not knowing is
worse than knowing.

## The solution

Attach authority to the action itself. Before an agent calls a tool, a proxy in front
of it decides — and that decision is an artifact, not a log line.

Five load-bearing bricks:

0. **Actor register — `this agent cannot`.** Before any warrant is read, the layer knows
   *who is asking*: four classes of actor (`operator-human`, `autonomous-system`, `chatbot`,
   `mcp-supplier`), each with tools it may never call and data it has no entitlement to.
   The limit is on the actor, not on the rights of the user on whose behalf it acts — so a
   valid warrant for the same tool does not widen it. This is the question that separates a
   control layer from a permission system.
1. **Identity, not a key.** Every agent gets a scoped, ephemeral identity. No shared
   API keys, no "one credential for the whole fleet".
2. **Pre-execution enforcement.** `allow` / `deny` / `require-human` is decided on the
   *parameters of the call* before the call executes — not queued for review after.
3. **Kill switch.** Monitoring is not containing. `/revoke` pulls the agent's warrant
   and stops the chain mid-flight.
4. **Receipt.** Every action lands in an append-only, hash-chained record: who, what,
   why, who authorised, when. This is the measurement layer — the proof.

The warrant is not a metaphor. It is the artifact: a signed order with a scope, a TTL,
and the signature of whoever authorised it.

## Architecture

```
        ┌────────────┐   tool-call (params)   ┌──────────────────────────┐
        │   agent    │ ─────────────────────▶ │  TENET kernel (MCP)       │
        │ (scoped    │                        │  intercept BEFORE exec    │
        │  identity) │ ◀──── allow / deny ─── │                           │
        └────────────┘                        └───────────┬──────────────┘
                                                          │
              ┌──────────────────┬────────────────────────┼──────────────────┐
              ▼                  ▼                         ▼                  ▼
      ┌──────────────┐   ┌──────────────┐        ┌──────────────┐   ┌──────────────┐
      │ Warrant      │   │ Policy       │        │ Append-only  │   │ /revoke      │
      │ issuer       │   │ engine       │        │ receipt log  │   │ kill switch  │
      │ scope·TTL·   │   │ per-param    │        │ hash-chained │   │ pull warrant │
      │ signature    │   │ allow/deny/  │        │ who·what·why │   │ stop chain   │
      │              │   │ redact·human │        │ ·authoriser  │   │              │
      └──────────────┘   └──────────────┘        └──────┬───────┘   └──────────────┘
                                                         │
                                                  ┌──────▼───────┐
                                                  │ Console      │  one screen,
                                                  │ GET /api/state│  four tiles
                                                  └──────────────┘
```

### The shape, against the microkernel canon

The node is drawn and built as a **microkernel**: a small core that coordinates, everything that
decides living outside it as a control plugin. The canon this is checked against is the
[microkernel architecture pattern](https://www.geeksforgeeks.org/system-design/microkernel-architecture-pattern-system-design/)
(minimal kernel · services as separate modules · a defined interface · inter-process
communication · service management · drivers outside the kernel). Component by component, with
the file that carries it:

| Canon component | What carries it here | State |
|---|---|---|
| Minimal kernel | `warrnt/proxy.py` — 238 of the node's 1 931 lines (12 %); it coordinates and holds no control table | built |
| Services as separate modules | 17 modules outside the kernel, three of them the control gates themselves (`warrnt/plugins/act_class.py`, `actor_scope.py`, `order_policy.py`), plus `policy.py`, `actions.py`, `actors.py`, `registry.py`, `anchor.py`, `upstream.py` | built |
| A defined interface | a gate = name · order · `check(ctx) → (decision, reason, detail) \| None`; outward, the seam is HTTP + JSON-RPC (MCP) | built |
| Inter-process communication | the agent talks MCP over HTTP; the upstream is behind the `upstream.py` adapter, so the transport is not the policy | built |
| **Service management** | `warrnt/gates.py` — `register(..., replace=True)` swaps a gate and `unregister(name)` pulls one **while the node runs**; discovery is `pkgutil` over `warrnt/plugins/` | built |
| Drivers outside the kernel | `build_upstream()` — the kernel never names a vendor | built |

**The kernel names no control.** `proxy.py` contains zero decision call sites — no `classify(`,
no `apply_class(`, no `engine.evaluate(`, no `actors.check(`. Gates are files under
`warrnt/plugins/` (`act_class` → `actor_scope` → `order_policy`, by `order`); adding one is adding
a file. `tests/test_gates.py` proves it, including that a gate dropped into the package at test
time stops the pipeline without a line of the kernel changing, and that the pipeline fails
**loudly** (a `RuntimeError`) rather than silently allowing when no gate decides.

**What is drawn but not built**, so the diagrams are not read as more than they are: discovery
through `importlib.metadata.entry_points` (we use `pkgutil` over the package), gate order and
enable/disable read from the catalog, and `watch()` hot reload.

**The price of the shape**, named rather than hidden: the split costs an indirection at every
decision and makes a failure harder to trace — which is why the kernel is the only place that
answers, and why "no gate decided" is an error instead of a default.

The proxy sits between the agent and any MCP server. It sees the tool name and the full
argument set, evaluates the active warrant's scope against them, and only then forwards —
or rejects. A rejection is written to the receipt chain *before execution*, so the proof
exists whether the action happened or not.

**`GET /api/state` contract** (what the console polls — the seam between core and screen):

```json
{
  "revoked": 1,
  "last_stop": 0.8,
  "agents":   [ { "id": "...", "role": "...", "state": "active|halted",
                  "warrant": "W-4419", "ttl": 420, "ttl0": 420, "last": "..." } ],
  "warrants": [ { "id": "W-4419", "agent": "...", "scope": "...",
                  "ttl": 420, "ttl0": 420, "state": "active|revoked|expired" } ],
  "actions":  [ { "class": "observe", "decider": "machine",
                  "decider_text": "the node decides", "meaning": "...",
                  "tools": ["infra.plan"] } ],
  "receipts": [ { "t": "14:02:43", "decision": "allow|deny|redact|human|revoked",
                  "what": "<code>crm.read</code> ...",
                  "meta": "order W-4419 · policy: read-only",
                  "hash": "d46ef77e" } ]
}
```

The `actions` field is an explicit D13 contract extension. It is the machine-readable Stage 4 taxonomy consumed by the console's taxonomy strip; its six class values are `observe | read_personal | draft | write_reversible | irreversible | authorize`.

Two of the five decisions **execute**, and the `tools/call` result says so:

* `allow` — the payload goes through untouched.
* `redact` — the call runs, and the personal fields named by the rule are stripped from the
  payload *before* the upstream is called. The result carries `redacted` (the fields removed)
  and `upstream_params` (what the upstream was actually allowed to see), so the screen can show
  the difference between what was asked for and what left the node. This is the vocabulary's
  fifth value doing real work: `inspect_pii` refuses the act, `redact` lets the act happen
  without the data.
* The other three (`deny`, `human`, `revoked`) are refusals and leave the perimeter untouched —
  `executed: false`, and the executor counter does not move. An order whose TTL elapsed is one
  of these: a `deny` whose detail carries `warrant_state: expired`, because `expired` is a
  *warrant state*, not a decision.

## The demo vector (the 3:47 moment)

One scenario, deterministic, run end to end:

1. Three agents run under three signed warrants.
2. At **3:47**, `support-copilot` asks to export customer email and PESEL:
   `crm.bulk_export {table:"customers", fields:["email","pesel"], rows:12000}`.
3. Its warrant says *read-only, no PII fields* → the call is **DENIED before execution**.
   Zero rows leave the perimeter.
4. The denial is written to the hash-chained receipt log, with the authorising order.
5. One `/revoke` pulls warrant **W-4419**; the agent halts in **0.8 s**.

**Authorised. Recorded. Revocable.**

## ACT-2 — identity, entitlement, refusal (2026-10-03)

Three questions the screen could not answer, now answered — each with a test that fails if the
answer is removed.

- **Who acts, and for whom.** A warrant is a delegation, so it carries `principal` and
  `on_behalf_of` inside the signed payload, and the node serves them on `GET /api/agents`. One
  builder (`MCPProxy._new_agent`) makes both a seeded and a live-warrant agent, so an order issued
  later cannot have a different shape than one issued at seed time.
- **Authority to act is not the right to data.** The entitlement register lives with the operator
  (`control_plane/kernel.py`): a warrant may allow `equity.read_snapshot` and the register may still
  withhold `market_data.equity.read`. The gate runs **before the order is priced**, refuses with
  `gate: "entitlement"` and the named right, and the refusal is recorded — an action, a receipt, a
  chain entry — exactly like any other decision.
- **A refusal is an event.** Separation of duties — the requester may not decide their own hold —
  is filed in the hash-chained registry *before* the caller is told `409`, and the held action is
  left `pending`.
- **How far a call got is a number, not a claim.** `Action.boundary_attempts` counts the exits at
  the two places a call actually leaves the perimeter: a deny and a hold carry `0`, an allow carries
  `1`. The upstream's own access log is read by one function (`warrnt.api.upstream_log_path`) and
  digested by one other (`warrnt.api._sha256_of`), so "it never contacted anything" is checked
  against the far side rather than asserted.
- **The mirror is pinned to the fixes.** `node/` is `warrnt@274d13a`; the canonical repository's own
  suite is **160 passed**, this repository's is **229 passed**.

## What works today

Honest split between what is running and what is designed.

**Working and verified (2026-10-02):**

- **The node itself** — [`indrad3v4/warrnt`](https://github.com/indrad3v4/warrnt): the MCP
- **The node's source, inside this package** — [`node/`](node/), a mirror pinned to
  `warrnt@274d13a`, so the code and its 160 tests can be read without leaving the repository.
  The canonical repository is still [`indrad3v4/warrnt`](https://github.com/indrad3v4/warrnt)
  (`node/MIRROR.md` says so, and `scripts/sync-node.sh --check` proves the mirror still matches).
  proxy, per-parameter policy, signed warrants with TTL, the hash-chained registry with
  `GET /verify`, `/revoke`, and the console served from the node. `pytest -q` → **229 passed**;
  a clean-machine run (`scripts/f2_clean_run.sh`) starts from an empty temp dir, clone, fresh
  venv, deps from PyPI.
- **The actor register** — `GET /actors`, `warrnt/actors.py`, ten tests, PR
  [#1](https://github.com/indrad3v4/warrnt/pull/1). The load-bearing test: same agent, same
  signed warrant, same parameters — change only the actor's class and the answer flips
  `allow` → `deny`, with nothing run upstream.
- **Console** — `index.html`, one dense screen, four tiles
  (agents · warrants · kill switch · proof), **zero dependencies, no page scroll**.
  Verified in headless Chromium at 1920×1080, 1440×900, 1366×768, 2560×1440: four tiles
  present, all in view, `scrollHeight == innerHeight`, `overflow-y: hidden`.
  Screenshots in `warrnt-screen/shot-*.png`.
- **Two data paths, one screen.** The console polls `GET /api/state` every 1.5 s.
  On a 200 it renders the **live feed**; on failure it falls back to the built-in
  **demo feed** and replays the 3:47 scenario. The screen is real; the feed is swappable.
- **Demo video** — `warrnt-demo-40s.mp4`, 1920×1080, 25 fps, 40.0 s, H.264 (~1.9 MB).
  Recorded deterministically: page state is a pure function of virtual time, so frames
  do not drift and the take is reproducible, not screen-captured by hand.
- **`/api/state` contract** — documented above and frozen; it is the interface the
  proxy must satisfy. The freeze was lifted once, to add `redact` to the receipt
  vocabulary: the task requires redaction as a control action, and a receipt the
  chain cannot record is not a receipt. Any further change goes through D13.

**Designed here, built in the node repo (the core):**

- The MCP proxy, per-parameter policy, warrant issuing with signature + TTL, the append-only
  receipt store, `/revoke` and the actor register all exist and are tested — in
  [`indrad3v4/warrnt`](https://github.com/indrad3v4/warrnt), not in this package.
- What is *not* wired here: this console's live feed talks to a running node only when you
  serve it with one (`?source=live`); offline it replays the scripted 3:47 state machine.
  The screen renders exactly the JSON the node emits, so the seam is one HTTP call wide.

We would rather show you a small thing that truly runs than a big thing that only
looks finished.

## Run it

```bash
# the screen — offline, file:// works (demo feed)
chromium warrnt-screen/index.html

# or serve it so a live /api/state can be polled
cd warrnt-screen && python3 -m http.server 8099
#  ->  http://127.0.0.1:8099/index.html

# query flags: ?source=live|demo (default: auto)   ?qa=1 (self-measures viewport fit)

# reproof the demo video (deterministic)
cd warrnt-demo && python render_demo.py 10 40
ffmpeg -y -framerate 10 -start_number 0 -i frames/f_%04d.jpg \
  -vf "fps=25,fade=t=in:st=0:d=0.4,fade=t=out:st=39.4:d=0.6,format=yuv420p" \
  -c:v libx264 -preset slow -crf 18 -movflags +faststart -t 40.0 \
  /root/.hermes/media/video/warrnt-demo-40s.mp4
```

## Concept lock

The form and the name are decided, and the decisions — including what was rejected — are
recorded in [`docs/concept-form-and-name.md`](docs/concept-form-and-name.md).

- **Form** — *the witness at the boundary*: an in-line judge that answers, for every step,
  whether **this** agent may perform **this** action, on behalf of **this** user, right now.
- **Name** — **TENET** (Latin *tenet*, "it holds"): the order holds the action, and the record
  reads the same both ways. The name of the idea, not a product mark — the register is crowded
  (see the check table above); `tenet.dev` / `tenet.io` free, `tenet.ai` taken.
- Fifteen candidate forms were scored against five tests taken from the brief; every
  rejected form is on the record with the test it fails.

## What's next

- **Settle the idea's address** — `tenet.dev` / `tenet.io` resolve to nothing and are free; the
  mark under that name is crowded, so if a product or a domain must be defensible, clear one of
  the spares (ADNOT, PRAES) instead. The idea has a name and still no address.
- **Break-glass with a term** — the last unbuilt artifact of the Stage 4 table: an emergency
  override that names who used it, for how long, and audits every use.
- **RFC 3161 external timestamp** for the anchor — deliberately not added inside the 17-hour
  window, because it needs an outside service and could break the demo.
- Identity issuance per agent/task is real in the node (ephemeral identity per call, warrant scope
  tied to it); what is not built is a multi-tenant issuer, and it stays that way on purpose.

---

*TENET is a working demo of the AI control layer: authority attached to the action,
proof attached to the authority.*

## Triggering the canonical live scenario (operator)

The Control Room's first screen is a story, not a dashboard, and that story has to be real:

```bash
curl -sS -X POST -H "x-warrnt-admin: $WARRNT_ADMIN_TOKEN" \
  https://<host>/api/demo/run
```

`POST /api/demo/run` runs the one canonical scenario server-side - agent `fx-trader` asks for the
EUR/USD reference rate through `fx.read_rate` - and returns the whole correlation: `run_id`,
`action_id`, `decision`, `receipt` and the crossing the kernel recorded (`endpoint`,
`http_status`, `response_sha256`, `value`). The agent token is read from the kernel's own registry
inside the serving process, so **no credential ever reaches the browser** and the page cannot
become a second authority. Without an operator token the route answers 401; with no live upstream
configured it answers 503 and refuses to invent a rate.

`upstream_contacted` is true only when the upstream answered with an HTTP status - a permitted
call whose transport failed is reported as exactly that, not as a crossing.

## What the container runs

`bash scripts/serve_tenet.sh` starts both roles as one process tree: the real tool server
(`python -m upstream.frankfurter_server`, loopback) and the control plane (`uvicorn
control_plane.app:app` on `$PORT`, one worker). The control plane is pointed at the tool server by
URL (`WARRNT_UPSTREAM`) and never imports it, so the kernel still decides before a byte leaves.
If the tool server fails to bind, the control plane comes up DEGRADED and `/api/demo/run` refuses.
