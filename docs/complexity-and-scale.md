# Complexity and scale

Requirement 10 asks for the time and space behaviour of this solution on a **large** agentic
system, and for the current implementation. Both are below, separated honestly: what was measured
on the delivered code, and what the structure implies as it grows.

Everything in §2–§3 was **measured**, not estimated. Method and the script to reproduce it are in
§6. Measurements are on Windows, Python 3.14, through the in-process test client (no network
stack), so the I/O terms — which dominate writes — are at their most favourable; a real socket
adds to the constant, not to the growth.

**Symbols** — `R` receipts in the chain · `A` agents · `W` warrants · `G` gates · `P` payload
size in characters · `S` patterns/signatures in force · `k` page size.

## 1. Per intercepted call (the write path) — O(1) in chain length

| Operation | Time | Space |
|---|---|---|
| identity + warrant binding | O(1) dict lookups | O(1) |
| gate chain (`gates.run`) | O(G), each gate O(1) except the content scan | O(1) |
| deterministic content scan | O(P·S) with regex/signatures; **O(keys)** in the delivered build, which matches personal data by field *name* | O(1) |
| budget check | O(1) lookup + O(entries in window) prune | O(window) |
| receipt append + hash + anchor | O(P) to hash the row, O(1) amortised in R | O(1) |
| **end to end** | **O(P + G + S·P)** — no term in R | — |

Measured end to end:

```
receipts already in the chain    median call latency
        10                          16.0 ms
       100                          16.0 ms
     1 000                          18.8 ms      <- noise, not growth
     5 000                          16.2 ms
```

**Flat.** The call path does not degrade as the chain grows, which is the property that matters
for a long-running deployment — and worth stating carefully, because the measurements bounce: a
later run of the same script printed 19.1 ms at 1 500 receipts and 16.2 ms at 5 000, i.e. *lower*
at three times the history. There is no monotonic term in `R`; what moves is I/O. 16 ms is not
compute: it is **four fsyncs** on the critical path
(the receipt, the execution receipt, the action store, the anchor). Throughput is therefore
I/O-bound and per-process:

```
write throughput   61 calls/s sequential (16.5 ms per call)
```

Payload sensitivity (the same call with a bigger argument):

```
    100 chars -> 15.9 ms      1 000 -> 16.2 ms      10 000 -> 16.1 ms      100 000 -> 17.6 ms
```

So a 1000× payload costs +1.7 ms in the delivered build — the scan is not the bottleneck today.
It becomes one if content patterns are enabled: `S` regexes over `P` characters is `O(P·S)`, and at
`P = 100 000`, `S = 15` that is 1.5 M regex evaluations *per call*. §5 recommends the fix the
original brief already names (Aho–Corasick, `O(P + matches)`).

## 2. Reads — where the linear terms live

```
  R      /verify    /api/state   /receipts   /api/security-events?limit=200
 250      5 021 us     5 862 us    2 083 us      841 us
 500      7 314 us     7 881 us    3 192 us      659 us
1000     12 459 us    12 988 us    5 663 us      685 us
2000     22 649 us    23 274 us   10 716 us      903 us
```

| Endpoint | Complexity | Evidence |
|---|---|---|
| `/verify` (recompute the chain) | **O(R)** | 5.0 → 22.6 ms as R goes 250 → 2000: ≈ **10.0 µs per receipt** |
| `/api/state` | **O(R)** — it carries the chain verdict | ≈ **9.95 µs per receipt** |
| `/receipts` | **O(R)** — serialises the whole registry | ≈ 5.0 µs per receipt |
| `/api/security-events?limit=k` | **O(k)**, `k ≤ 200` → O(1) in R | flat, 0.66–0.90 ms |
| `/api/actions`, `/api/agents`, `/api/warrants` | O(A), O(W) over their own stores | linear in their own size, not R |

### The threshold that matters

The console polls `/api/state` **every 1.5 s**. Two independent runs of the shipped script fitted
`/api/state ≈ 5.9 ms + 9.95 µs × R` and `≈ 3.7 ms + 12.14 µs × R`, so the poll budget is exhausted
somewhere in

```
R ≈ 120 000 - 150 000 receipts   — past this the node spends its time answering its own console
```

The spread is machine variance in a per-row hash, not a different shape: both fits are lines.

At one receipt per intercepted call that is ~150 000 calls of history — reachable inside a single
long-running deployment, and it fails as *self-inflicted saturation*, not as an error. This is the
single most important scalability finding in this document.

## 3. Space — linear, and cheap per row

```
960 KiB for 2 080 receipts   = 473 B per receipt  -> 1 M receipts ≈ 0.47 GB
anchors: 389 KB for the same run ≈ 187 B per receipt (a second file of the same order)
in memory: the registry holds its entries in a list -> O(R) resident, ≈ a few times 473 B/row
           with Python object overhead
```

Space is `O(R + A + W)` on disk and `O(R)` in memory. There is no retention policy and no
accounting of it anywhere in the code — requirement 2 of the brief asks for exactly that
("storage space / history of sensitive data shared") and it is **not implemented**.

## 4. What this means for a large agentic system

Let `N` agents each making `c` calls per second.

- **Throughput** — one node process sustains **61 calls/s**. With a per-node state (the receipt
  chain and the action store are local, and that is what makes the evidence credible), capacity
  scales by **sharding agents across processes**: `processes ≈ N·c / 61`. 1000 agents at 1 call/s
  is ≈ 17 processes. That is linear and horizontal, which is the right shape.
- **Latency** — the write path is flat in history, so a shard's latency does not degrade over a
  long run. Reads on the same shard do, per §2.
- **The anchor** is per node and its cost is per receipt, so anchor volume grows with calls, not
  with agents — one more reason to shard by agent rather than by request.
- **The semantic channel** (unmerged) is a bounded, cached call: one round trip per distinct
  payload, `O(1)` per repeat. It is latency-additive per call, not complexity-additive.
- **The deep risk is not big-O, it is a single hot read.** `O(R)` reads on the node that also
  serves the console is how a healthy system falls over politely.

## 5. What to change, in order of value

1. **Make the chain verdict incremental.** Verify on append, keep the head, and let `/verify` and
   `/api/state` read the cached verdict (with an explicit "recompute now" path for audits). This
   removes `O(R)` from the hot read path and raises the console threshold from ~150 k receipts to
   unbounded — the largest single win, and a small change.
2. **Rotate and bound segments.** The registry already has archive/rotation plumbing
   (`history()`, `_archive_path`); verify per segment so the recompute cost is `O(segment)`, not
   `O(lifetime)`.
3. **Paginate and index the read APIs.** `/receipts` and `/export` should take a cursor and return
   `O(k)`; add an index on `(agent, ts)` so filtered exports stop scanning `O(R)` rows.
4. **Fewer fsyncs per call.** Four per call sets the 61 calls/s ceiling; a group commit (one
   barrier per batch) buys a multiple without changing the guarantees the receipts make.
5. **Aho–Corasick for content patterns** when `S` grows past a handful: `O(P + matches)` instead of
   `O(P·S)`, and it is what the original security brief asked for.
6. **Stream the registry** instead of holding `entries` in memory: `O(1)` resident with an offset
   index, which also bounds memory on a node that runs for months.
7. **Retention and storage accounting** — required by the brief and missing: a policy for what is
   kept, for how long, and a number for it.

## 6. Reproducing these numbers

```bash
pip install -r node/requirements.txt
python scripts/benchmark_scale.py        # prints the tables in §1–§3
```

The script drives a real node through its HTTP surface, grows the chain, and prints the same
columns: call latency at increasing `R`, the four read endpoints, payload sensitivity, write
throughput, and the on-disk bytes per receipt. Numbers in this document come from that script on
one machine; the *shape* of each row — flat, linear, or bounded — is what the design depends on.
