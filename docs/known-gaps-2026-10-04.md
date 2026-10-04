# Known gaps — 2026-10-04

Eight gaps in the complexity/scale story, measured against the deployed code, not the node mirror.
Every item is a tracked issue: [#32](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/32) · [#33](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/33) · [#34](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/34) · [#35](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/35) · [#36](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/36) · [#37](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/37) · [#38](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/38) · [#39](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/39)

## Measured, pre-fix (the number any fix must move)

Local run on `b2ce580` (the commit production runs), through `control_plane.app`, writing via the
app's own `/mcp` so the store read is the store written. The chain length printed at every row is the
length the application itself reports — an empty read is not a proven pass.

| эндапойнт | R=0 J=0 | R=500 J=0 | R=2000 J=0 | R=2000 J=2000 |
|---|---|---|---|---|
| `/state` | 0.8 мс | 7.6 мс | 23.6 мс | 24.0 мс |
| `/stream` | 0.9 мс | 7.0 мс | 23.9 мс | 24.0 мс |
| `/overview` | 0.8 мс | 3.8 мс | 12.1 мс | 12.2 мс |
| `/live-trace` | 0.8 мс | 1.2 мс | 1.1 мс | 4.7 мс |
| `/model-usage` | 0.6 мс | 0.8 мс | 0.7 мс | 4.1 мс |
| `/security-events` | 0.6 мс | 1.4 мс | 0.8 мс | 4.5 мс |

Fits: `/api/state` ≈ 0.84 ms + 11.4 µs × R · `/api/stream` ≈ 0.94 + 11.5 × R · `/api/overview` ≈ 0.81 + 5.6 × R.
Journal-bound: `/live-trace` 1.14 → 4.68 ms, `/model-usage` 0.72 → 4.11, `/security-events` 0.85 → 4.47 at 2000 journal rows.
Full console cycle (all six, R=2000, journal=2000): **73.5 ms of server time every 2 s**, one console.

Reproduce: `python eng/app_scale_bench.py` (writes `app-scale-curve.json`).

## The eight

| # | gap | issue |
|---|---|---|
| 1 | benchmark_scale.py imports `warrnt.api` — it measures the node mirror, while production runs `control_plane/app.py` with 33 routes, none of them measured | [#32](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/32) |
| 2 | a row of the scale table is an HTTP 404 (`/api/security-events` on the node), not a measurement | [#33](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/33) |
| 3 | the polling budget is wrong twice: 2000 ms cadence in code vs 1.5 s in the doc, and three of six endpoints carry an O(R) verdict | [#34](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/34) |
| 4 | three endpoints read whole files (provider journal, `origins.jsonl`) on every cycle — no cache, no offset reads | [#35](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/35) |
| 5 | `app.state.runs` grows without bound | [#36](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/36) |
| 6 | a synchronous `httpx.Client` inside awaited tool functions stalls the whole event loop | [#37](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/37) |
| 7 | `actions(limit=200)` / `_receipt_index(200)` lose older runs — data loss where the UI assumes an index | [#38](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/38) |
| 8 | no space accounting for the journal, origins and runs; no retention policy for any store | [#39](https://github.com/indrad3v4/hackyeah-2026-ai-control-layer/issues/39) |

## Fixed in parallel

`scripts/benchmark_scale.py` is being replaced by a measurement of the deployed app; the O(R) verdict is
moved to the write path with a cached verdict and an explicit "recompute now" for audit; journal reads are
made incremental; the run store is bounded — on the branch `fix/perf-scaling`. The curve above is the
"before"; the same script re-run on that branch is the "after".
