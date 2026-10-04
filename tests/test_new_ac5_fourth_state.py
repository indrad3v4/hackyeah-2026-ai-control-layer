"""NEW-AC5 — the fourth state reaches the human (brief 2026-10-04).

``control.counts`` has counted ``expired`` all along and the console has spoken three of the four
states (allowed, not allowed, waiting). A hold that dies because its agent was halted is the FOURTH
state, and nothing on the console said so: the count lived in the API and reached no person.

The positive case is produced for real, through the control plane's own routes - a journey commits a
hold, the held agent is halted with a named person on the brake, and the kernel expires the hold - so
"expired > 0" is a fact read from ``/api/stream`` and never a state the test typed in.

Four tests:

* the kernel really produces the fourth state, and both the count and the row carry WHEN it was
  resolved (``decided_ts``, the same field a person-resolved hold carries);
* the console renders all four counts with their clocks, uses the word ``expired``, and prints the
  clock the KERNEL recorded - not a time the surface made up;
* a payload with no ``control.counts`` makes the strip say the kernel did not report them, instead
  of showing zeros it never received;
* a resolved hold offers no approve/deny control (the kernel refuses a decision on anything but a
  pending hold), while the same action, captured while it WAS pending, does offer them.
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "index.html"
NODE = shutil.which("node")
ADMIN = "test-admin-token"
OPERATOR = "Indra"


@pytest.fixture()
def fourth_state(tmp_path, monkeypatch) -> dict:
    """The kernel's own fourth state, produced live: hold -> named halt -> expired.

    Returns ``{"stream": <GET /api/stream body>, "pending": <trace while held>,
    "expired": <the same action's trace after the halt>, "action_id": ...}``.
    """
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(seed=True), headers={"X-WARRNT-Admin": ADMIN}) as client:
        assert client.post("/api/scenario/journey").status_code == 200
        pending = client.get("/api/stream?limit=20").json()["pending"]
        assert pending, "the journey commits a hold; nothing was waiting for a person"
        held = pending[0]
        action_id = held["action_id"]
        while_held = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
        assert while_held["state"] == "pending", while_held["state"]
        # The brake, through the route an operator really uses: token + a named person.
        r = client.post(f"/api/agents/{held['agent']}/revoke", json={"by": OPERATOR})
        assert r.status_code == 200, r.text
        after = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
        body = client.get("/api/stream?limit=20").json()
    assert after["state"] == "expired", after["state"]
    return {"stream": body, "pending": while_held, "expired": after, "action_id": action_id}


def _clock(ts) -> str:
    """The same clock the console prints: the row's own time, HH:MM, local."""
    return datetime.fromtimestamp(float(ts)).strftime("%H:%M")


# One harness, two real functions from index.html: the strip and the control block. Both are sliced
# out of the page and run under node against a minimal DOM, so the assertions below are behavioural
# (what the page WROTE), never a source grep.
_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) { console.error(name + ' not found in ' + process.argv[2]); process.exit(1); }
  const marks = ['\nfunction ', '\nasync function ']
    .map(m => src.indexOf(m, start + 1)).filter(i => i > 0);
  if (!marks.length) { console.error('end of ' + name + ' not found'); process.exit(1); }
  return src.slice(start, Math.min(...marks));
}
function el() { return { style: {}, innerHTML: '', dataset: {}, textContent: '', value: '', onclick: null }; }
const els = { states: el(), controlBlock: el(), operatorName: el(), controlMsg: el() };
global.$ = id => els[id] || (els[id] = el());
global.esc = s => String(s == null ? '-' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
global.fmt = n => (n == null ? '-' : Number(n).toLocaleString());
eval(slice('clockOf'));
eval(slice('renderStates'));
eval(slice('renderControl'));
const what = process.argv[3];
const payload = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
if (what === 'strip') { renderStates(payload); process.stdout.write(els.states.innerHTML); }
else { renderControl(payload); process.stdout.write(els.controlBlock.innerHTML); }
"""


def _run_page(fn: str, payload: dict) -> str:
    """Run one real console function under node and return the HTML it wrote."""
    if NODE is None:
        pytest.skip("node is absent; the console cannot be rendered (no pass claimed)")
    source = INDEX.read_text(encoding="utf-8")
    for name in ("function clockOf(", "function renderStates(", "function renderControl("):
        assert name in source, "index.html lost %r; this test would be vacuous" % name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_HARNESS)
        harness = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh)
        data = fh.name
    try:
        done = subprocess.run([NODE, harness, str(INDEX), fn, data],
                              capture_output=True, text=True, timeout=60)
    finally:
        Path(harness).unlink(missing_ok=True)
        Path(data).unlink(missing_ok=True)
    assert done.returncode == 0, "the console harness failed: %s" % (done.stderr or "")[:400]
    return html.unescape(done.stdout)


def _cell(strip: str, state: str) -> str:
    """The one cell of the strip that speaks for ``state`` (empty when the state is not rendered)."""
    i = strip.find('data-state="%s"' % state)
    if i < 0:
        return ""
    start = strip.rfind("<span", 0, i)
    nxt = strip.find('<span class="stateCell"', i)
    return strip[start:] if nxt < 0 else strip[start:nxt]


# ============================================================ the state, produced for real
def test_new_ac5_the_kernel_produces_the_fourth_state_and_the_count_carries_it(fourth_state):
    """A hold whose agent was halted is EXPIRED on the record, counted, and carries its clock."""
    body, trace = fourth_state["stream"], fourth_state["expired"]
    counts = body["counts"]
    assert counts.get("expired", 0) > 0, (
        "the console's fourth state has no count to render: %r" % counts)
    row = next(r for r in body["stream"] if r["state"] == "expired")
    assert row["action_id"] == fourth_state["action_id"]
    # A state without a time is half the fact: the row says WHEN it was resolved, in the same field a
    # person-resolved hold uses, and it is the kernel's own clock (never the interception time).
    assert row["decided_ts"], "the expired row carries no decided_ts: %r" % row
    assert float(row["decided_ts"]) >= float(row["ts"]), (
        "the resolution cannot precede the request: %r" % row)
    # The trace says the same thing, and the decision space is unchanged by the expiry (R2/A3).
    assert trace["state"] == "expired" and trace["decision"] == "human"
    assert trace["executed"] is False and trace["upstream"]["contacted"] is False
    assert trace["decided_ts"] and "decided_ts" not in trace["incomplete"]
    # A hold that is STILL waiting carries no resolution time - and is not named incomplete for it:
    # nothing has been decided yet, so there is no missing evidence (AC1b's rule cuts both ways).
    waiting = fourth_state["pending"]
    assert waiting["state"] == "pending" and waiting["decided_ts"] is None
    assert "decided_ts" not in waiting["incomplete"]


def test_new_ac5_the_console_renders_the_fourth_state_with_the_kernels_clock(fourth_state):
    """expired > 0 -> the surface renders the state AND a time, and the word is ``expired``."""
    body = fourth_state["stream"]
    counts, rows = body["counts"], body["stream"]
    strip = _run_page("strip", body)
    # All four counts of control.counts are rendered, each under its own state.
    for state in ("approved", "denied", "pending", "expired"):
        cell = _cell(strip, state)
        assert cell, "the console does not render the %s count at all: %r" % (state, strip[:300])
        assert str(counts[state]) in cell, (
            "the %s cell does not carry the kernel's count %r: %r" % (state, counts[state], cell))
    # THE CLAUSE: the fourth state, with its own word and its own clock.
    expired_row = next(r for r in rows if r["state"] == "expired")
    cell = _cell(strip, "expired")
    assert "expired" in cell.lower(), "the fourth state is not named with the word expired: %r" % cell
    assert _clock(expired_row["decided_ts"]) in cell, (
        "the expired cell does not show the clock the kernel recorded for it: %r" % cell)
    # ... and the state it replaced is not claimed for it: a resolved hold is never 'waiting'.
    assert "waiting for you" not in cell


def test_new_ac5_without_kernel_counts_the_strip_shows_no_numbers_it_did_not_receive():
    """No ``control.counts`` in the payload -> the strip says so; it never shows zeros it invented."""
    strip = _run_page("strip", {"stream": [], "pending": []})
    assert "did not report" in strip, "the strip claims counts the kernel never sent: %r" % strip
def test_new_ac5_a_resolved_hold_offers_no_control_and_a_pending_one_does(fourth_state):
    """The fourth state reaches the human: a dead hold says so, a live one still offers the decision.

    Both blocks are rendered from the SAME action's own traces - captured while it was pending and
    after the brake expired it - so the difference the page shows is the kernel's, not the test's.
    """
    expired = _run_page("control", fourth_state["expired"])
    assert "expired" in expired.lower(), (
        "the resolved hold's block does not say it expired: %r" % expired)
    at = _clock(fourth_state["expired"]["decided_ts"])
    assert at in expired, "the expired hold's block does not show the kernel's clock: %r" % expired
    for hook in ('id="approveBtn"', 'id="denyBtn"'):
        assert hook not in expired, (
            "the console offers %s on a hold the kernel has already resolved: %r" % (hook, expired))
    assert "waiting for you" not in expired.lower()
    # The contrast that makes the two assertions above meaningful: while the hold IS pending the
    # page does offer the decision.
    pending = _run_page("control", fourth_state["pending"])
    assert 'id="approveBtn"' in pending and 'id="denyBtn"' in pending, (
        "a pending hold must offer the human control: %r" % pending)
    assert "expired" not in pending.lower()
