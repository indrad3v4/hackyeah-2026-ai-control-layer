"""Issue #37: the HTTP fallback read must not stall the event loop.

Before the fix ``agents._read`` used a blocking ``httpx.Client``. Called from the async answer
path, two concurrent reads against a slow upstream serialised (about 2x latency) and the event
loop ran at ~0 heartbeats. After the fix the read is an awaited ``httpx.AsyncClient`` under a
bounded semaphore: the two reads overlap (~1x latency) and the loop keeps ticking throughout.

``test_the_old_blocking_read_serialised_and_froze_the_loop`` is the negative control - it
reproduces the exact pre-fix shape (a blocking client awaited on the loop) so the concurrency
assertion in the positive test cannot pass vacuously.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from control_room import agents

SLOW_S = 0.6


class _SlowHandler(BaseHTTPRequestHandler):
    """A real socket that takes ``SLOW_S`` seconds to answer every GET."""

    def do_GET(self):  # noqa: N802 - http.server API
        time.sleep(SLOW_S)
        body = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # keep the server's own chatter out of the test output
        pass


@pytest.fixture()
def slow_upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _two_reads(reader):
    """Run ``reader`` twice concurrently and count loop heartbeats while they run."""

    async def main():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        beat = asyncio.create_task(heartbeat())
        start = time.perf_counter()
        first, second = await asyncio.gather(reader(), reader())
        elapsed = time.perf_counter() - start
        beat.cancel()
        return first, second, elapsed, ticks

    return asyncio.run(main())


def test_two_concurrent_reads_overlap_and_keep_the_loop_alive(slow_upstream, monkeypatch):
    monkeypatch.setattr(agents, "CONTROL_PLANE_URL", slow_upstream)
    agents.bind_kernel(None)  # force the HTTP route; the app binds a kernel, a detached caller does not

    first, second, elapsed, ticks = _two_reads(lambda: agents._read("/api/overview"))

    assert first == {"ok": True, "path": "/api/overview"}
    assert second == {"ok": True, "path": "/api/overview"}
    # Concurrent, not serialised: two SLOW_S reads finish in ~SLOW_S, not ~2xSLOW_S.
    assert elapsed < SLOW_S * 1.7, f"reads serialised: {elapsed:.3f}s for two {SLOW_S}s calls"
    # The loop kept running: a blocked loop freezes the heartbeat near zero ticks.
    assert ticks >= 20, f"event loop starved: only {ticks} heartbeats in {elapsed:.3f}s"


def test_the_old_blocking_read_serialised_and_froze_the_loop(slow_upstream):
    """Negative control: the pre-fix blocking client, awaited directly on the loop."""
    url = slow_upstream

    async def legacy_reader():
        # Exactly what _read did before the fix, minus the in-process branch: a blocking GET
        # called from a coroutine, so it runs ON the event loop and stops it.
        with httpx.Client(timeout=3.0) as client:
            return client.get(f"{url}/api/overview").json()

    first, second, elapsed, ticks = _two_reads(legacy_reader)

    assert first == {"ok": True, "path": "/api/overview"}
    assert second == {"ok": True, "path": "/api/overview"}
    # Serialised: two SLOW_S reads take ~2xSLOW_S because the first blocks the second.
    assert elapsed >= SLOW_S * 1.8, f"expected the blocking control to serialise, got {elapsed:.3f}s"
    # ...and the loop was frozen while it ran.
    assert ticks <= 5, f"expected a frozen loop, saw {ticks} heartbeats"
