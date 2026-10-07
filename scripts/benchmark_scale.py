#!/usr/bin/env python3
"""Measure the node's time and space behaviour as its history grows.

This is the script behind `docs/complexity-and-scale.md`. It drives a real node through its own
HTTP surface - no mocks, no instrumentation inside the kernel - and prints four tables:

  1. call latency as the receipt chain grows      (is the write path flat in history?)
  2. the three read endpoints as the chain grows  (which reads are linear in R?)
  3. payload sensitivity                          (what does a big argument cost?)
  4. write throughput and bytes per receipt       (capacity and space)

    python3 scripts/benchmark_scale.py
    python3 scripts/benchmark_scale.py --max 5000 --repeat 7

Numbers depend on the machine; the SHAPE of each row is what the design depends on. The write path
is expected to be flat, and `/verify` and `/api/state` are expected to be linear in R.

Issue #33: this script used to also time `/api/security-events?limit=200` against the node. That
route does not exist on the node - it returned HTTP 404 `Not Found`, and the "0.66-0.90 ms flat"
row in `docs/complexity-and-scale.md` was the speed of that 404 body, not a measurement. The row
was dropped here and in the doc. `_probe` now refuses to start if any measured endpoint is not a
200, so a missing route can never again be recorded as a fast one.
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "node"))

try:
    from fastapi.testclient import TestClient            # noqa: E402
except ImportError:                                       # pragma: no cover
    print("SKIP  the node's dependencies are not installed. Run:")
    print("        pip install -r node/requirements.txt")
    raise SystemExit(2)

from warrnt.api import create_app                        # noqa: E402
from warrnt.config import Settings                       # noqa: E402


def build(tmp: pathlib.Path):
    settings = Settings(home=tmp, registry_path=tmp / "receipts.jsonl",
                        key_path=tmp / "issuer.key", anchor_path=tmp / "anchors.jsonl",
                        upstream_url="", host="127.0.0.1", port=0, dev=True,
                        admin_token="benchmark-token")
    client = TestClient(create_app(settings=settings))
    client.__enter__()
    tokens = {a["id"]: a["token"] for a in client.get("/agents").json()}
    headers = {"X-WARRNT-Agent": "support-copilot",
               "X-WARRNT-Token": tokens["support-copilot"]}
    return client, headers


def call_body(size: int = 5) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "crm.read", "arguments": {"table": "tickets", "limit": size}}}


def median_us(fn, repeat: int) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1e6)
    return statistics.median(samples)


# Paths the read table measures. `/api/security-events` is NOT here: the node does not serve it
# (issue #33), so timing it measured a 404 body. The row lives on the CONTROL PLANE's own HTTP
# surface, not the node's, and is measured there.
READ_PATHS = ("/verify", "/api/state", "/receipts")


def _probe(client) -> None:
    """Fail fast if a measured endpoint is not a 200.

    A non-200 body is not a measurement - timing it would print an error page's speed as the
    endpoint's. Issue #33 exists precisely because this check was missing.
    """
    for path in READ_PATHS:
        resp = client.get(path)
        if resp.status_code != 200:
            raise SystemExit(
                f"refusing to benchmark {path}: HTTP {resp.status_code} "
                f"{resp.text[:60]!r} - a non-200 is not a measurement")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2000, help="largest chain to build")
    ap.add_argument("--repeat", type=int, default=5, help="samples per measurement")
    args = ap.parse_args(argv)

    targets = sorted({max(10, args.max // 16), max(20, args.max // 8),
                      max(40, args.max // 4), args.max})

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        client, headers = build(tmp)
        body = call_body()
        _probe(client)  # a non-200 endpoint must fail loud, never be timed as if it were fast

        # One pass: grow the chain to each target and measure there. Growing first and measuring
        # afterwards would leave every row at the same length - and a slope fitted through
        # duplicate points is worse than no slope.
        rows = []
        for target in targets:
            while len(client.get("/receipts").json()) < target:
                client.post("/mcp", json=body, headers=headers)
            receipts = len(client.get("/receipts").json())
            rows.append((receipts,
                         median_us(lambda: client.post("/mcp", json=body, headers=headers), args.repeat),
                         median_us(lambda: client.get("/verify"), args.repeat),
                         median_us(lambda: client.get("/api/state"), args.repeat),
                         median_us(lambda: client.get("/receipts"), args.repeat)))
            print(f"   measured at {receipts} receipts")

        print("\n1. call latency (median) against chain length    [expected: flat in R]")
        print("   receipts      call latency")
        for receipts, call_us, *_ in rows:
            print(f"   {receipts:8d}      {call_us:9.0f} us")

        print("\n2. the read endpoints against chain length")
        print("   receipts      /verify   /api/state    /receipts")
        for receipts, _, verify_us, state_us, receipts_us in rows:
            print(f"   {receipts:8d}   {verify_us:9.0f}us {state_us:9.0f}us "
                  f"{receipts_us:9.0f}us")

        if len(rows) >= 2:
            first, last = rows[0], rows[-1]
            slope = (last[3] - first[3]) / max(1, last[0] - first[0])
            print(f"\n   /api/state ~= {first[3]:.0f}us + {slope:.2f}us x R "
                  f"(fitted over {first[0]}..{last[0]} receipts)")
            if slope > 0:
                print(f"   the console polls /api/state every 1.5 s -> that budget is spent at "
                      f"R ~= {1.5 / (slope / 1e6):,.0f} receipts")
        else:
            print("\n   not enough spread to fit a slope - re-run with a larger --max")

        print("\n3. payload sensitivity (the deterministic scan)")
        for size in (100, 1000, 10000, 100000):
            b = call_body()
            b["params"]["arguments"]["note"] = "x" * size
            us = median_us(lambda: client.post("/mcp", json=b, headers=headers), args.repeat)
            print(f"   payload {size:7d} chars   {us:9.0f} us")

        print("\n4. throughput and space")
        start = time.perf_counter()
        rounds = 40
        for _ in range(rounds):
            client.post("/mcp", json=body, headers=headers)
        took = time.perf_counter() - start
        receipts = client.get("/receipts").json()
        registry = tmp / "receipts.jsonl"
        per_row = registry.stat().st_size / max(1, len(receipts))
        print(f"   write throughput   {rounds / took:6.1f} calls/s sequential "
              f"({took / rounds * 1000:.1f} ms per call)")
        print(f"   chain length       {len(receipts)} receipts")
        print(f"   space              {per_row:.0f} B per receipt "
              f"-> 1M receipts ~= {per_row * 1e6 / 1e9:.2f} GB")
        print(f"   anchors            {(tmp / 'anchors.jsonl').stat().st_size / 1024:.0f} KiB "
              f"for the same run")
        client.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
