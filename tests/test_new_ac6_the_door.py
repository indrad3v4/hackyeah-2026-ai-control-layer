"""NEW-AC6 — the door (originally the corridor between two rooms; re-cut 04.10.2026 to ONE room).

Measured on both live hosts before this commit, verbatim: `curl -s <url> | grep -c 'href="'` returned
**0** for the console and **0** for the guide, on Railway and on Pages alike. Two rooms, each complete
on its own, with no way to walk from one to the other except editing the URL — the loop only closes if
a person can walk it, and a walk that needs the URL bar is not a walk.

The fix is deliberate and small: ONE plain `<a href>` in each page's markup. Not a JS listener, not a
button wired in a script block — plain markup, so it survives a text-only fetch and a `curl` sees it.

The merge then removed the corridor by removing the second room: two rooms meant two beat machines and
two copies of the character's voice engine, which is how one product ended up speaking with two voices.

Four tests, on the one room:

* the console carries the guide BY ITSELF, in the markup a text-only fetch sees - the layer, its rail
  and the character's name - and carries no link to a second surface and no second voice engine;
* `/onboarding` is a redirect (307 -> `/`), not a surface, and the file that used to serve it is gone;
* the brief's own shell check (`curl -s <url> | grep -c 'href="'`) passes on the one path on both hosts,
  and the second path is closed on both: 307 on the control plane, not-200 on a Pages-shaped host;
* the README names exactly ONE front door, that door is the console, and the page it names really does
  carry the guide - the README's claim is checked against the served bytes, not believed.
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

# What a Pages-shaped static host would serve from the repo root. /onboarding is deliberately absent:
# no file, no second path. (/observer is a different audience, read-only — not part of this merge.)
PAGES = {"/": "index.html", "/observer": "observer.html"}

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



def test_new_ac6_one_room_carries_the_guide_and_no_corridor():
    """The merge: the console IS the guide's room — the layer in markup, no link to a second surface.

    A text-only fetch must carry the guide (no JS needed to see it), and must carry no second path and
    no second voice engine. That last pair is the whole reason the corridor was removed.
    """
    console = _served(CONSOLE)
    assert CONSOLE_DOOR not in console, (
        "the console still links to a second surface: one path means the guide is not a link away")
    assert 'id="guideStrip"' in console, (
        "the console must carry the guide's layer in the markup a text-only fetch sees")
    assert "TENET · your guide" in console, "the layer must name the character, not just narrate"
    assert 'id="journeyRail"' in console, "the layer must stand on the same rail, not beside it"
    for forbidden in ("speechSynthesis", "function pickVoice", "function clipFor("):
        assert forbidden not in console, (
            "a second voice engine came back with the layer (%r): one product, one voice" % forbidden)


def test_new_ac6_the_second_path_is_a_redirect_and_the_file_is_gone():
    """/onboarding keeps working and stops being a surface: 307 -> /, and nothing on disk to serve."""
    with TestClient(create_app(seed=True)) as client:
        r = client.get(GUIDE, follow_redirects=False)
    assert r.status_code == 307, "GET %s must redirect, not serve: HTTP %s" % (GUIDE, r.status_code)
    assert r.headers.get("location") == CONSOLE, (
        "the redirect must land on the one path: %r" % (r.headers.get("location"),))
    assert not (REPO / "onboarding.html").exists(), (
        "the second page is still on disk: a file is a second path waiting to be linked again")



def test_new_ac6_the_brief_check_passes_on_the_one_path_and_the_second_path_is_closed(hosts):
    """`curl -s <url> | grep -c 'href="'` > 0 on the one path, both hosts - run verbatim.

    The old brief asked for four checks (two pages x two hosts). There is one page now, so the check
    runs twice and the second path is verified CLOSED instead of served: 307 on the control plane and
    not-200 on a Pages-shaped host (no file, nothing to link to).
    """
    live, static = hosts
    for host, url in (("the control-plane host (what Railway runs)", live + CONSOLE),
                      ("the static host (Pages-shaped, one path)", static + CONSOLE)):
        code = _http_code(url)
        assert code == 200, "%s served %s as HTTP %s" % (host, url, code)
        count = _brief_check(url)
        assert count > 0, (
            'the brief\'s check fails: `curl -s %s | grep -c \'href="\'` returned %d' % (url, count))
        print('curl -s %s | grep -c \'href="\' -> %d' % (url, count))
    assert _http_code(live + GUIDE) == 307, (
        "the control plane must redirect %s, not serve a second surface" % GUIDE)
    assert _http_code(static + GUIDE) != 200, (
        "a Pages-shaped host still serves %s: a second path is reachable again" % GUIDE)


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
    assert 'id="guideStrip"' in door_page, (
        "the README names / as the front door, so the guide must be carried BY that page, "
        "not one link away from it")
