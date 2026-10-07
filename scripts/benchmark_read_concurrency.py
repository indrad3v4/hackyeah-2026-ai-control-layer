#!/usr/bin/env python3
"""Issue #37: before/after for the blocking read inside the async answer path.

Runs two concurrent reads against one slow upstream and prints, for each:
  * wall time for the two reads (serialised ~2x latency vs overlapped ~1x), and
  * event-loop heartbeats observed while they ran (0 = the loop was frozen).

BEFORE = the pre-fix shape: a blocking ``httpx.Client`` awaited directly on the loop.
AFTER  = the fixed read: awaited ``httpx.AsyncClient`` under a bounded semaphore.

    python3 scripts/benchmark_read_concurrency.py
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from control_room import agents  # noqa: E402

SLOW_S = 0.6


class _SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        time.sleep(SLOW_S)
        body = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _measure(reader, label):
    async def main():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        beat = asyncio.create_task(heartbeat())
        start = time.perf_counter()
        await asyncio.gather(reader(), reader())
        elapsed = time.perf_counter() - start
        beat.cancel()
        return elapsed, ticks

    elapsed, ticks = asyncio.run(main())
    print(f"{label:<8} two concurrent reads of {SLOW_S:.2f}s each -> "
          f"wall {elapsed * 1000:7.1f} ms   heartbeats {ticks:4d}   "
          f"({'OVERLAPPED' if elapsed < SLOW_S * 1.7 else 'SERIALISED'}, "
          f"{'loop alive' if ticks >= 20 else 'LOOP FROZEN'})")
    return elapsed, ticks


def main() -> int:
    server, url = _start_server()
    try:
        # BEFORE: the pre-fix shape - a blocking client awaited on the event loop.
        async def legacy_reader():
            with httpx.Client(timeout=3.0) as client:
                return client.get(f"{url}/api/overview").json()

        _measure(legacy_reader, "BEFORE")

        # AFTER: the fixed read - awaited AsyncClient under a bounded semaphore.
        agents.bind_kernel(None)
        agents.CONTROL_PLANE_URL = url
        _measure(lambda: agents._read("/api/overview"), "AFTER")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
