# WARRNT — the AI control layer

> **No warrant, no action.**

Every action an AI agent takes carries a signed, scoped warrant — or it does not run.
No warrant, no action. This is the one thing that turns "we deployed agents" into
"we can stop one and prove why".

HackYeah 2026 · Partner task **AI Control Layer** (Goldman Sachs).

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
        │   agent    │ ─────────────────────▶ │  WARRNT proxy (MCP)       │
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

The `actions` field is an explicit D13 contract extension. It is the machine-readable Stage 4
taxonomy consumed by the console's taxonomy strip; its six class values are
`observe | read_personal | draft | write_reversible | irreversible | authorize`.

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

## What works today

Honest split between what is running and what is designed.

**Working and verified (2026-10-02):**

- **The node itself** — [`indrad3v4/warrnt`](https://github.com/indrad3v4/warrnt): the MCP
  proxy, per-parameter policy, signed warrants with TTL, the hash-chained registry with
  `GET /verify`, `/revoke`, and the console served from the node. `pytest -q` → **60 passed**;
  a clean-machine run (`scripts/f2_clean_run.sh`) starts from an empty temp dir, clone, fresh
  venv, deps from PyPI.
- **The actor register** — `GET /actors`, `warrnt/actors.py`, ten tests, PR
  [#1](https://github.com/indrad3v4/warrnt/pull/1). The load-bearing test: same agent, same
  signed warrant, same parameters — change only the actor's class and the answer flips
  `allow` → `deny`, with nothing run upstream.
- **Console** — `warrnt-screen/index.html`, one dense screen, four tiles
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
- **Name** — **ADNOT** (*adnotare*, "to note down"): the verdict is noted and shown, before
  the action runs. `.dev` / `.io` / `.ai` free, zero trademarks found, no live product.
- Fifteen candidate forms were scored against five tests taken from the brief; every
  rejected form is on the record with the test it fails.

## What's next

- Wire the MCP proxy and serve `/api/state` — the console goes from demo feed to live.
- Persist the receipt chain and expose verification (recompute the hash chain).
- Real identity issuance per agent/task, with warrant scope tied to the identity.

---

*WARRNT is a working demo of the AI control layer: authority attached to the action,
proof attached to the authority.*
