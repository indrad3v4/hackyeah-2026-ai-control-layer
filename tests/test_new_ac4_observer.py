"""NEW-AC4 — the observer (brief 2026-10-04).

The intermediary the partner named: someone who must see what is waiting for a person and what the
kernel judged, and must not be able to decide any of it. The room is ``/observer``: a read-only view
of ``control.pending`` (who is waiting) and the last N actions (each with its class and the
taxonomy's decider line, straight from ``GET /api/stream``).

The hooks this page must NOT carry are named here, in the test, not in prose - they are the
console's own control hooks, the ids the allow/deny path is wired to in ``index.html``:

    approveBtn   the Approve button (``resolve("approve")`` -> POST /api/actions/<id>/approve)
    denyBtn      the Deny button    (``resolve("deny")``    -> POST /api/actions/<id>/deny)
    controlBlock the block that holds them
    controlMsg   the block's status line
    operatorName the field that names the human who decides
    revoke       the Stop agent control

Two tests: the served pages (source), and the RENDERED DOM of the observer under chromium with the
kernel's own ``/api/stream`` payload. When chromium is absent the render test SKIPS and claims no
pass it did not earn, exactly as ``tests/test_control_room_experience.py`` does.
"""
from __future__ import annotations

import html
import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
OBSERVER_SOURCE = (REPO_ROOT / "observer.html").read_text(encoding="utf-8")
CONSOLE_SOURCE = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
CHROMIUM = shutil.which("chromium") or (
    "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None)

# The console's control hooks, by id - the allow/deny/approve path. Named here so a rename in the
# console cannot silently make this test vacuous: the same NAMES are asserted as real ids in the
# console (``id="approveBtn"`` ...) and as absent ids in the observer's room.
CONSOLE_CONTROL_HOOKS = ("approveBtn", "denyBtn", "controlBlock", "controlMsg",
                         "operatorName", "revoke")
# And every way a page could ask for a decision: no element that submits, and no inline handler.
INTERACTIVE_MARKUP = ("<button", "<form", "<input", "<select", "<textarea", "onclick=")


@pytest.fixture()
def observer_body(tmp_path, monkeypatch) -> str:
    """The observer's room as the control plane serves it."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/observer")
    assert r.status_code == 200, "the observer's room must be served"
    return r.text


@pytest.fixture()
def stream_payload(tmp_path, monkeypatch) -> dict:
    """The kernel's OWN ``/api/stream`` body, after a real journey: real rows, a real hold."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(seed=True)) as client:
        assert client.post("/api/scenario/journey").status_code == 200
        r = client.get("/api/stream?limit=20")
        assert r.status_code == 200
        return r.json()


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the observer page and the kernel's own ``/api/stream`` body - nothing else."""

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = self.path.split("?")[0]
        if path in ("/observer", "/"):
            body = OBSERVER_SOURCE.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
        elif path == "/api/stream":
            body = json.dumps(self.server.payload).encode("utf-8")  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("content-type", "application/json")
        else:
            body = b"{}"
            self.send_response(404)
            self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # keep pytest output clean
        return


def _rendered_dom(payload: dict) -> str:
    """The DOM chromium produces after the page's own JS has run (or skip honestly)."""
    if CHROMIUM is None:
        pytest.skip("chromium is absent; the observer render cannot be performed (no pass claimed)")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.payload = payload  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/observer"
    try:
        proc = subprocess.run(
            [CHROMIUM, "--headless", "--no-sandbox", "--disable-gpu",
             "--virtual-time-budget=6000", "--dump-dom", url],
            capture_output=True, text=True, timeout=90)
        assert proc.returncode == 0, f"chromium exited {proc.returncode}: {proc.stderr[:400]}"
        return proc.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_new_ac4_the_hooks_are_named_the_console_carries_them_and_the_observer_does_not(observer_body):
    """The source, both ways: the console's control hooks exist, the observer's room has none."""
    body = observer_body
    assert "TENET · the observer" in body and "read-only" in body
    # The two things the room reads, named in the page: control.pending and the judged stream.
    assert "control.pending" in body and "/api/stream" in body
    for hook in CONSOLE_CONTROL_HOOKS:
        assert f'id="{hook}"' in CONSOLE_SOURCE, (
            f"the console no longer carries the hook id {hook!r}; this test would be vacuous - "
            "re-point CONSOLE_CONTROL_HOOKS at the ids the allow/deny path really uses")
        assert f'id="{hook}"' not in body, (
            f"the observer's room must not carry the control hook id {hook!r}")
    for markup in INTERACTIVE_MARKUP:
        assert markup not in body, f"the observer's room must not carry {markup!r}"
    # It reads with GET and nothing else: no POST, no request method, no body.
    assert '"POST"' not in body and "method:" not in body
    # The copy tells the reader the truth about the room they are in.
    assert "no control that could allow, deny or release anything" in body


def test_new_ac4_the_rendered_observer_dom_has_zero_control_hooks(stream_payload):
    """The RENDERED room, with the kernel's own /api/stream body: zero controls, real evidence."""
    payload = stream_payload
    # ... plus ONE row in the shape a tool the layer cannot classify produces (NEW-AC3's own rule):
    # the surface must show R1's sentence where a class would be, never a blank.
    unclassified = {"action_id": "A-0999", "run_id": "run-unclassified", "ts": 0,
                    "agent": "report-bot", "tool": "unknown.tool", "class": None, "decider": None,
                    "decider_text": None, "meaning": None, "decision": "deny", "state": "decided",
                    "reason": payload["refusal"], "decided_ts": 0, "decided_by": "",
                    "unclassified": True}
    payload = dict(payload, stream=[unclassified] + payload["stream"])
    dom = _rendered_dom(payload)
    for hook in CONSOLE_CONTROL_HOOKS:
        assert dom.count(f'id="{hook}"') == 0, (
            f"the rendered observer DOM carries the hook id {hook!r}")
    for markup in INTERACTIVE_MARKUP:
        assert markup not in dom, f"the rendered observer DOM carries {markup!r}"
    # The room really renders the record: the held action, its reason, its class, its decider line.
    text = html.unescape(dom)
    pending = payload["pending"][0]
    assert pending["action_id"] in text, "the held action on the record must be visible"
    assert pending["tool"] in text and pending["agent"] in text
    assert pending["reason"] in text, "the kernel's own reason string, verbatim"
    assert pending["warrant"] in text and pending["receipt"] in text, (
        "a hold shows the warrant it is held under and the receipt it will carry")
    cls = payload["stream"][-1]["class"]
    assert cls in text and payload["deciders"][cls] in text, (
        "each row carries its class and the taxonomy's own decider line, verbatim")
    assert payload["refusal"] in text, "R1's refusal sentence is on the page, not only in the API"
    assert "closed set: " + " · ".join(payload["closed_set"]) in text, (
        "the ladder order the kernel publishes is on the page, in its order")

