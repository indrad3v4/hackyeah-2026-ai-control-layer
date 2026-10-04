"""NEW-AC6 — the door (the corridor between the two rooms, brief 2026-10-04).

Measured on both live hosts before this commit, verbatim: `curl -s <url> | grep -c 'href="'` returned
**0** for the console and **0** for the guide, on Railway and on Pages alike. Two rooms, each complete
on its own, with no way to walk from one to the other except editing the URL — the loop only closes if
a person can walk it, and a walk that needs the URL bar is not a walk.

The fix is deliberate and small: ONE plain `<a href>` in each page's markup. Not a JS listener, not a
button wired in a script block — plain markup, so it survives a text-only fetch and a `curl` sees it.

Three tests:

* each room carries exactly one plain link to the other, in the markup (not inside a `<script>`), with
  visible text, and no `onclick` / `javascript:` anywhere near it;
* the brief's own check, run verbatim as a shell pipeline - `curl -s <url> | grep -c 'href="'` - passes
  four times: both pages on a control-plane host (what Railway runs) and both pages on a static host
  that resolves extensionless paths (what GitHub Pages does, `/onboarding` -> `onboarding.html`);
* the README names exactly ONE front door, that door is the console, and the page it names is the one
  that really carries the link onward - the README's claim is checked against the served bytes, not
  believed.
"""
from __future__ import annotations

import http.server
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
CURL = shutil.which("curl")

# The two rooms and the doors between them, named once.
CONSOLE = "/"
GUIDE = "/onboarding"
CONSOLE_DOOR = 'href="/onboarding"'
GUIDE_DOOR = 'href="/"'

PAGES = {"/": "index.html", GUIDE: "onboarding.html", "/observer": "observer.html"}

_ANCHOR = re.compile(r"<a\b[^>]*>(?:.*?)</a>", re.S)


def _markup(body: str) -> str:
    """The page with every ``<script>`` block removed - what a text-only fetch actually carries.

    A door that only exists as a string a script writes into the DOM is not a door a `curl` can walk,
    so this is the body the assertions below are made against.
    """
    return re.sub(r"<script\b.*?</script>", "", body, flags=re.S)


def _doors(body: str, href: str) -> list[str]:
    """Every anchor in the MARKUP whose href is exactly ``href``."""
    return [m.group(0) for m in _ANCHOR.finditer(_markup(body))
            if re.search(r'href="%s"' % re.escape(href), m.group(0))]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _PagesLike(http.server.BaseHTTPRequestHandler):
    """A static host that resolves extensionless paths the way GitHub Pages does."""

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        name = PAGES.get(self.path.split("?")[0])
        if name is None:
            body, code = b"not found", 404
        else:
            body, code = (REPO / name).read_bytes(), 200
        self.send_response(code)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # keep pytest output clean
        return


@pytest.fixture()
def hosts(tmp_path, monkeypatch):
    """Two real HTTP hosts: a control-plane host (what Railway runs) and a static host (Pages-shaped).

    Both are served over a real socket so the checks below are `curl` checks, not API calls.
    """
    if CURL is None:
        pytest.skip("curl is absent; the brief's check cannot be run (no pass claimed)")
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(seed=True), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    live = "http://127.0.0.1:%d" % port
    for _ in range(120):
        if _http_code(live + "/health") == 200:
            break
        time.sleep(0.25)
    else:
        pytest.fail("the control-plane host did not come up on %s" % live)
    static = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PagesLike)
    sthread = threading.Thread(target=static.serve_forever, daemon=True)
    sthread.start()
    try:
        yield live, "http://127.0.0.1:%d" % static.server_address[1]
    finally:
        server.should_exit = True
        static.shutdown()
        static.server_close()
        sthread.join(timeout=5)


def _http_code(url: str) -> int:
    if CURL is None:
        return 0
    done = subprocess.run([CURL, "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
                          capture_output=True, text=True, timeout=30)
    return int((done.stdout or "0").strip() or 0)


def _brief_check(url: str) -> int:
    """The brief's own check, verbatim: `curl -s <url> | grep -c 'href="'` - the number it prints."""
    if CURL is None:
        pytest.skip("curl is absent; the brief's check cannot be run (no pass claimed)")
    done = subprocess.run("%s -s %s | grep -c 'href=\"'" % (CURL, url), shell=True,
                          capture_output=True, text=True, timeout=30)
    return int((done.stdout or "0").strip() or 0)


def _hrefs(url: str) -> str:
    """Every href the fetched page really carries - so the check names WHICH door, not just one."""
    if CURL is None:
        pytest.skip("curl is absent; the brief's check cannot be run (no pass claimed)")
    done = subprocess.run("%s -s %s | grep -o 'href=\"[^\"]*\"'" % (CURL, url), shell=True,
                          capture_output=True, text=True, timeout=30)
    return done.stdout


def _served(path: str) -> str:
    """The page as the control plane serves it, read as bytes - never from disk, never re-rendered."""
    with TestClient(create_app(seed=True)) as client:
        r = client.get(path)
    assert r.status_code == 200, "the control plane must serve %s" % path
    return r.text


def test_new_ac6_each_room_carries_one_plain_link_to_the_other():
    """The door is markup: one anchor each way, outside every <script>, with text, no listener."""
    console, guide = _served(CONSOLE), _served(GUIDE)
    doors = _doors(console, GUIDE)
    assert len(doors) == 1, (
        "the console must carry exactly ONE plain link to the guide, found %d: %r" % (len(doors),
                                                                                      doors))
    back = _doors(guide, CONSOLE)
    assert len(back) == 1, (
        "the guide must carry exactly ONE plain link back to the console, found %d: %r" % (
            len(back), back))
    for where, door in (("console", doors[0]), ("guide", back[0])):
        low = door.lower()
        assert "onclick" not in low and "javascript:" not in low, (
            "the %s door is a JS listener, not a link: %r" % (where, door))
        assert "addlistener" not in low, "the %s door is wired by a listener: %r" % (where, door)
        text = re.sub(r"<[^>]+>", "", door).strip()
        assert text, "the %s door has no visible text: %r" % (where, door)
    # And the doors are nowhere in a script block: a text-only fetch (no JS) still carries them.
    for body, href in ((console, GUIDE), (guide, CONSOLE)):
        assert _doors(body, href), "the door is not in the markup a text-only fetch carries"
        assert re.search(r"<script\b.*?href=\"%s\"" % re.escape(href), body, re.S) is None, (
            "the door appears inside a <script> block; it would not survive a text-only fetch")


def test_new_ac6_the_four_checks_of_the_brief_pass_on_both_hosts(hosts):
    """`curl -s <url> | grep -c 'href="'` > 0: both pages, both hosts - four checks, run verbatim."""
    live, static = hosts
    checks = (
        ("the control-plane host (what Railway runs)", live + CONSOLE, GUIDE),
        ("the control-plane host (what Railway runs)", live + GUIDE, CONSOLE),
        ("the static host (Pages-shaped: /onboarding -> onboarding.html)", static + CONSOLE, GUIDE),
        ("the static host (Pages-shaped: /onboarding -> onboarding.html)", static + GUIDE, CONSOLE),
    )
    seen = []
    for host, url, want in checks:
        code = _http_code(url)
        assert code == 200, "%s served %s as HTTP %s" % (host, url, code)
        count = _brief_check(url)
        seen.append((url, count))
        assert count > 0, (
            "the brief's check fails: `curl -s %s | grep -c 'href=\"'` returned %d" % (url, count))
        assert want in _hrefs(url), (
            "%s carries an href, but not the door to the other room (%r missing)" % (url, want))
    assert len(seen) == 4, "the brief asks for FOUR checks; %d ran" % len(seen)
    # The evidence line, verbatim: the four checks and the number each one printed.
    for url, count in seen:
        print("curl -s %s | grep -c 'href=\"' -> %d" % (url, count))


def test_new_ac6_the_readme_names_one_front_door_and_it_is_the_page_that_links_onward():
    """One door named, checked against the served bytes - the README's claim is not believed."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    named = [l.strip() for l in readme.splitlines() if "front door" in l.lower()]
    assert named, "the README names no front door"
    for line in named:
        assert "Control Room" in line or "`/`" in line, (
            "the front door must be the one door that links onward (the console), this names: %r"
            % line)
        assert not re.search(r"guide|observer|onboarding", line, re.I), (
            "a second surface is named as a door: %r" % line)
    # The door the README names really is the one that carries the corridor onward.
    door_page = _served(CONSOLE)
    assert _doors(door_page, GUIDE), (
        "the README names / as the front door, but / carries no link to the guide")
