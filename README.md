# TENET — AI Control Layer

> **No warrant, no action.**

TENET is an enforcement layer for AI agents: an agent may propose an action, but it cannot execute that action unless the control plane and enforcement kernel authorize it first.

Built for **HackYeah 2026 · AI Control Layer / Goldman Sachs challenge**.

**Live Control Room:** https://hackyeah-2026-ai-control-layer-production.up.railway.app/

---

## The pitch

AI agents are moving from chat into systems that can read data, write records, call APIs and move information across trust boundaries.

The security question is not only **what did the agent do?** It is: **what was it trying to do, who authorized it, what policy was applied, did data actually leave, and where is the proof?**

TENET puts that decision **before the tool call**.

```text
USER / SYSTEM → AI AGENT → TENET CONTROL PLANE → ENFORCEMENT KERNEL → UPSTREAM
                         identity → entitlement → warrant → policy → decision
                                                            ↓
                                             receipt + evidence
```

**The model proposes. The kernel decides. The upstream executes. The receipt proves what happened.**

## What the security operator gets

### What is happening?
- Who is acting?
- What does the agent want?
- Which resource/tool is involved?
- Which warrant and policy apply?
- What did TENET decide?

### Did anything leave?
- **not contacted** — the request was stopped before the upstream;
- **contacted** — the record contains evidence of an upstream response;
- **not proven** — TENET refuses to invent a crossing it cannot prove.

### Why?

`agent proposal → identity/entitlement → warrant → policy → kernel decision → upstream → receipt`

### What can I stop?

A protected **Stop agent** action revokes authority through the same enforcement path. The UI does not create a second security mechanism.

## Security model

| Layer | Question |
|---|---|
| Identity | Who is making the request? |
| Entitlement | Does this actor have the right to the requested data/resource? |
| Warrant | Is this agent authorized for this action and scope? |
| Policy | Are these exact parameters allowed? |
| Decision | allow / deny / redact / human / revoked |
| Execution | Was the upstream actually contacted? |
| Receipt | What evidence was recorded? |

### Agent restriction is independent of user rights

A user may have access to a resource while an agent acting on that user's behalf is still forbidden from using it.

### Authority is not entitlement

A valid warrant does not automatically create data entitlement. A missing data entitlement can deny an otherwise warrant-compatible request before the upstream is contacted.

### Delegation is explicit

Agent records carry principal, on-behalf-of identity, entitlements and scoped authority.

## Why the model is not the security boundary

TENET can use DeepSeek for reasoning and orchestration. DeepSeek is **not** authoritative.

`run_id → model_trace_id → action/proposal → kernel decision → upstream call → receipt`

**Authority lives in the kernel decision.**

The Control Room exposes real provider resource evidence: requested model, served model, provider trace ID, calls, input/output/total tokens, latency and response status.

No API credential is returned to the browser.

## Canonical demo

An agent requests a customer-data export that is outside its warrant/policy scope.

```text
AGENT
  │  export customer records
  ▼
TENET
  ├─ identity
  ├─ entitlement
  ├─ warrant
  └─ policy
  ▼
DENY
  ├─ upstream contacted: NO
  └─ receipt: YES
```

The important property is:

> **The forbidden call never reached the data source.**

The denial is itself recorded, giving the security team evidence of the attempted action and the fact that execution did not happen.

## Happy path

The 40-second proof video (`docs/tenet-happy-path.mp4`) shows one resource and two agents. Every number, hash, receipt and verdict below was read back from the running kernel during the recorded run - none of it is scripted prose.

```text
USER REQUEST
  "Read the latest EUR/USD reference rate"
        │
        ▼
AI AGENT WANTS DATA
  fx-trader  →  fx.read_rate
        │
        ▼
TENET DECIDES BEFORE ANYTHING MOVES
  who is acting?  what may this agent access?
        │
        ├─────────────── ALLOW ───────────────┐
        │  value EUR/USD 1.1225               │  same resource
        │  upstream HTTP 200, 15.8 ms         │  same request
        │  sha256 f63f64a5…                   │
        │  receipt ee872944                   │
        ▼                                     ▼
  upstream called 1 → 2              support-copilot → fx.read_rate
                                             │
                                             ▼
                                     DENY — no entitlement to
                                     market_data.fx.read
                                     upstream contacted: NO (still 2 calls)
                                     receipt c4bfbe40
```

Selected timeline (the compact frames in the video):

| t | What the video shows | Where it comes from |
|---|---|---|
| 0–3.5 s | the user's request, in plain words | the request the demo route carries |
| 3.5–8 s | `fx-trader` wants `fx.read_rate` | the agent action the kernel intercepted |
| 8–13.5 s | identity, entitlement, warrant, policy — then the verdict | kernel decision path |
| 13.5–19 s | **ALLOW**: the real value arrives (1.1225, HTTP 200, 15.8 ms, sha256, receipt `ee872944`) | live Frankfurter response, recorded in `evidence.json` |
| 19–25 s | `support-copilot` asks for the *same* resource | second agent action |
| 25–31 s | **DENY**: *Frankfurter was NOT contacted* (upstream calls stay at 2), receipt `c4bfbe40` | kernel denial + upstream call journal |
| 31–40 s | both outcomes side by side, then the closing line | the two records above |

The property the video is built around:

> **The same question, asked by two agents, ends two different ways - and the denied call never reaches the data source.**

The headline card follows the record the operator selects, so the ALLOW can still be inspected after the DENY has happened; with nothing selected it shows the latest action.

`evidence.json` next to the video holds the raw values it was built from (`value`, `http_status`, `response_sha256`, `latency_ms`, both `receipt` ids, and the upstream call counter before/after each action).

## Architecture

**MCP is the transport/protocol boundary. TENET's enforcement kernel is the authority boundary.**

The agent/runtime can reason, plan and request an action. It cannot bypass the kernel and call the upstream directly.

## Repository

```text
control_plane/       HTTP/API seam and kernel-backed projections
control_room/        DeepSeek orchestration and provider evidence
node/                pinned internal implementation mirror
index.html            pitch / operator Control Room
tests/                contract and security tests
docs/                 architecture and implementation contracts
```

The internal Python namespace remains `warrnt` where compatibility with the canonical dependency and mirror requires it. **The product surface is TENET.**

## API surface

`GET /api/security-events?limit=20` — live security-decision feed.

`GET /api/security-events/{run_id}` — causal evidence graph.

`GET /api/model-usage` — read-only DeepSeek resource evidence.

`GET /api/overview` · `/api/state` · `/api/activity` · `/api/actions` · `/api/agents` · `/api/warrants`.

`POST /api/actions/{action_id}/approve` · `/deny`.

`POST /api/agents/{agent_id}/revoke`.

`POST /mcp` — intercepted `tools/call` path.

## Evidence discipline

- LLM output is not authority.
- A receipt is not authorization; the kernel decision is authority.
- Process success is not automatically upstream contact.
- Unknown stays unknown.
- An action ID is never relabelled as an upstream call ID.
- A denial is an event and is recorded.

> **The UI cannot manufacture a cleaner story than the evidence supports.**

## Implemented

- pre-execution MCP interception;
- signed/scoped warrants with TTL;
- actor-specific restrictions and entitlement checks;
- explicit on-behalf-of delegation;
- parameter-aware policy decisions;
- allow / deny / redact / human / revoked vocabulary;
- contextual revoke;
- append-only/hash-chained receipt evidence;
- upstream access-log evidence;
- explicit DeepSeek provider integration;
- provider trace/resource journal;
- security-event projection and causal evidence graph;
- operator Control Room with live model-resource display;
- the Control Room classified-data-row honesty rule: a crossing is shown only when the record
  carries an upstream `http_status`, and an intercept has no destination to show;
- the AC3/AC4 data-flow proof pair — `scripts/data_flow_demo.py` raises the real upstream and
  control plane and drives one ALLOW (`fx-trader`) and one DENY (`support-copilot`), reading the
  upstream's own `sent` counter on both sides of each call. Executed result: allow `sent` +1 with
  a real `https://api.frankfurter.dev/v1/latest?...` crossing (`value 1.1225`), deny `sent` +0 with
  `upstream.contacted: false`.

## Deliberately not claimed

A diagram is not presented as a deployed feature. If evidence is unavailable, TENET shows unknown or incomplete. A future enterprise connector is not presented as installed until it exists and is exercised.

The Control Room's live render is proven by a real headless render (`chromium --dump-dom`, the same
mechanism as `scripts/check_rendered_trace.py`), and by `tests/test_control_room_experience.py`
(AC3: JSON-object values never render as `[object Object]`; the action card is the first block,
before any technical identifier; the empty state explains TENET and offers a way to start; a `429`
with `retry_after_s` renders `Rate limited · retrying in Ns` with the real N). Where chromium is
absent the test **skips** with a reason — it never claims a render it did not perform.


## Demo sentence

> **Watch the agent ask for data. TENET stops it before the request reaches the data source — then shows you the evidence.**

## Run locally

```bash
python -m http.server 8099
# open http://127.0.0.1:8099/index.html
```

Tests: `python -m pytest tests/ -q`

The paired data-flow proof (raises the real upstream + control plane, prints raw JSON, exits
non-zero unless the pair is a genuine allow-crossing / deny-non-contact):

```bash
python scripts/data_flow_demo.py
```

Console gates: `python scripts/check_console.py` (both inline script blocks parse) and
`python scripts/console_layout_check.py index.html` (layout invariants).

DeepSeek is configured in the deployment environment with `DEEPSEEK_API_KEY`. Never commit or print the secret.

## Principles

1. **No warrant, no action.**
2. **No entitlement, no data.**
3. **The agent cannot grant itself authority.**
4. **The model is not the authority.**
5. **The upstream is never contacted before the decision.**
6. **A denial is an event.**
7. **Proof is evidence, not narration.**
8. **Unknown stays unknown.**
9. **The product surface speaks TENET; internal compatibility names stay internal.**
10. **Every security claim should be testable.**

## Links

- Live Control Room: https://hackyeah-2026-ai-control-layer-production.up.railway.app/
- Project repository: https://github.com/indrad3v4/hackyeah-2026-ai-control-layer
- Canonical enforcement dependency: https://github.com/indrad3v4/warrnt
