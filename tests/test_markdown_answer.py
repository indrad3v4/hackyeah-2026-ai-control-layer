"""The answer block renders markdown — safely, from our own origin (AC1-AC4, 2026-10-04).

Why these tests exist: the Control Room printed the model's markdown as raw text (literal
`**bold**`, backticks, `-` bullets) because the answer was written with `textContent`. The fix
renders the answer through vendored bytes (markdown-it + DOMPurify) served same-origin, and
sanitises the result — the answer is UNTRUSTED (it can carry upstream data and prompt-injected
markup). These tests prove the parts that can be proven without a browser:

* AC1 — the ``/vendor/{name}`` route serves the two libraries as ``application/javascript`` with
  bytes whose sha256 equals the value recorded in ``vendor/SOURCES.json``, and refuses traversal
  and unknown names with 404.
* AC2 — exactly one markdown renderer exists and the answer body is no longer written with
  ``textContent``.
* AC3/AC4 — the vendored markdown-it renders/escapes correctly under node, and the real
  ``mdAnswer`` falls back to escaped text when the libraries are absent (the vendored node test).

DOMPurify's actual sanitisation needs a browser/DOM and is proven by the orchestrator, not here.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
INDEX = ROOT / "index.html"
NODE_TEST = ROOT / "tests" / "md_answer.node.test.js"


def _sources() -> dict[str, dict]:
    data = json.loads((VENDOR / "SOURCES.json").read_text(encoding="utf-8"))
    return {row["file"]: row for row in data}


def _client() -> TestClient:
    return TestClient(create_app(seed=True))


# --------------------------------------------------------------------------- AC1: the route
def test_vendor_js_served_with_the_recorded_bytes():
    """200, application/javascript, and bytes whose sha256 equals SOURCES.json's value."""
    recorded = _sources()
    with _client() as client:
        for name in ("markdown-it.umd.min.js", "purify.min.js"):
            r = client.get("/vendor/" + name)
            assert r.status_code == 200, "%s must be served (got %s)" % (name, r.status_code)
            assert r.headers["content-type"].startswith("application/javascript"), (
                "%s must be application/javascript, got %r"
                % (name, r.headers.get("content-type")))
            digest = hashlib.sha256(r.content).hexdigest()
            assert digest == recorded[name]["sha256"], (
                "%s bytes drifted: %s != recorded %s"
                % (name, digest, recorded[name]["sha256"]))


def test_sources_json_served_as_json():
    with _client() as client:
        r = client.get("/vendor/SOURCES.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()[0]["file"] == "markdown-it.umd.min.js"


def test_vendor_route_refuses_traversal_and_unknown_names():
    """A route that serves files must serve exactly three, never a path."""
    with _client() as client:
        for bad in ("../app.py", "app.py", "unknown.js", "%2e%2e%2fapp.py",
                    "purify.min.js%00.png", "SOURCES.json/x"):
            r = client.get("/vendor/" + bad)
            assert r.status_code == 404, "%r must 404 (got %s)" % (bad, r.status_code)


# --------------------------------------------------------------------------- AC2: one renderer
def test_exactly_one_markdown_renderer_and_not_textcontent():
    src = INDEX.read_text(encoding="utf-8")
    assert src.count("function mdAnswer(") == 1, "there must be exactly one mdAnswer renderer"
    # The answer body is written by mdAnswer, and the old textContent write of the answer is gone.
    assert "$(\"answerBody\").innerHTML=mdAnswer(" in src, (
        "the answer body must be written through mdAnswer, not textContent")
    assert "$(\"proposalPrefix\").textContent=aiState" in src
    assert 'id="answerBody"' in src
    # The prefix line must still be plain text on #proposalPrefix, inside the #proposalText box.
    assert "$(\"proposalPrefix\").textContent=aiState" in src, (
        "the 'aiState · tokenText' prefix must stay plain text via textContent")
    assert "$(\"proposalText\").textContent" not in src, (
        "writing textContent to #proposalText would wipe the rendered answer element")


def test_the_renderer_has_a_real_whitelist_and_a_fallback():
    src = INDEX.read_text(encoding="utf-8")
    start = src.index("function mdAnswer(")
    end = src.index("\nfunction ", start + 1)
    body = src[start:end]
    assert "html:false" in body, "the parser must not parse raw HTML (html:false)"
    assert "DOMPurify.sanitize(" in body, "the rendered HTML must be sanitised"
    assert "ALLOWED_TAGS" in body and "ALLOWED_ATTR" in body, "a real whitelist is required"
    assert '"img"' not in body and '"iframe"' not in body, "no img/iframe may be allowed"
    assert 'typeof markdownit==="undefined"' in body and 'typeof DOMPurify==="undefined"' in body, (
        "the missing-library fallback guard must be present")


# --------------------------------------------------------------------------- AC3/AC4: node
def test_markdown_render_and_fallback_under_node():
    """Run the vendored node test: markdown-it renders/escapes, and mdAnswer falls back safely."""
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not found - cannot run the markdown-it proof")
    done = subprocess.run([node, str(NODE_TEST), str(INDEX)],
                          capture_output=True, text=True)
    print(done.stdout)
    assert done.returncode == 0, "the node markdown proof failed:\n" + done.stderr
