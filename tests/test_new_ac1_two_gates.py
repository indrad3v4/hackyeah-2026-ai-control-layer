"""NEW-AC1 .. NEW-AC7 — «surface what the kernel already knows» (brief 2026-10-04).

One test per acceptance criterion, each one failing before its change and passing after it. Every
string asserted here comes from the kernel (a receipt, ``/api/state``, ``/api/agents``, the actor or
the warrant record) or from the closed vocabulary the brief froze — no adjectives the surface
brought with it (M-method: «no adjectives you brought with you»).

Two harnesses, borrowed rather than re-invented:

  * ``_render_card`` runs the REAL ``renderActionCard`` from ``index.html`` under node against a
    minimal DOM and reads back the HTML it actually wrote (the same technique
    ``scripts/check_console.py`` uses), so a card assertion is a behavioural assertion, not a
    source grep;
  * ``_rendered_dom`` / the stdlib server render the page in chromium exactly as
    ``tests/test_act7_intent_and_control.py`` does.
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "index.html"
ONBOARDING = REPO / "onboarding.html"
NODE = shutil.which("node")


# ====================================================================== NEW-AC1 — the two gates
# The fixture is the kernel's OWN shape for the case the criterion names: the actor HOLDS the right
# (``payments.transfer``) but the agent's warrant SCOPE forbids it. The refusal sentence is verbatim
# from ``node/warrnt/policy.py:105`` — "tool '<tool>' is not covered by warrant scope" — so the test
# cannot pass on a paraphrase the surface invented.
_SCOPE_DENIED_TRACE = {
    "agent": "fin-reconcile",
    "action": {"tool": "payments.transfer", "class": "irreversible",
               "intent": "move 120,000 PLN to the vendor account",
               "args": {"amount": 120000, "to": "vendor"}},
    "decision": "deny",
    "reason": ("tool 'payments.transfer' is not covered by warrant scope · "
               "scope payments.read · ≤ 50,000 PLN · read-only"),
    "decided_by": "tenet-kernel",
    "entitlements": ["payments.read", "payments.transfer"],
    "scope": ["payments.read", "≤ 50,000 PLN", "read-only"],
    "checks": {"identity": {"ok": True, "detail": "operator-001"},
               "entitlement": {"ok": True, "right": "payments.transfer"},
               "warrant": {"id": "W-4417", "state": "active", "sig_ok": True, "ttl_remaining": 900},
               "policy": {"ok": False, "detail": "not covered by warrant scope"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "9c0ffee1",
    "action_id": "A-0101",
    "principal": "operator-001", "on_behalf_of": "operator-001",
    "timestamp": 1759420003, "origin": "agent call", "incomplete": [],
}


# Minimal DOM + stubs for the one function under test — the same contract check_console.py relies on.
_CARD_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('function renderActionCard(');
if (start < 0) { console.error('renderActionCard not found'); process.exit(1); }
const end = src.indexOf('\nfunction verdictTrace(', start);
if (end < 0) { console.error('end of renderActionCard not found'); process.exit(1); }
const fn = src.slice(start, end);
const cardEl = { style: {}, innerHTML: '' };
const els = { actionCard: cardEl, controlBlock: { style: {}, innerHTML: '' } };
global.$ = id => els[id] || { style: {}, innerHTML: '' };
global.esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
global.jsonSafe = s => { try { return JSON.stringify(s); } catch (e) { return String(s); } };
global.techRow = (label, value) => '<div class="tr"><div class="tl2">' + label +
  '</div><div class="tv">' + value + '</div></div>';
global.acRow = (label, value) => '<div class="acRow"><div class="acLabel">' + label +
  '</div><div class="acVal">' + value + '</div></div>';
global.yn = v => v === true ? 'reached' : 'not reached';
global.toolSentence = t => 'tool ' + t;
global.renderControl = () => {};
global.acHide = () => {};
/* NEW-AC5: the card prints the resolution clock with the page's own ``clockOf`` - slice the REAL one
 * rather than stub it, so a card that showed a made-up time could not pass here. */
const cstart = src.indexOf('function clockOf(');
const cend = src.indexOf('\nfunction ', cstart + 1);
if (cstart < 0 || cend < 0) { console.error('clockOf not found'); process.exit(1); }
eval(src.slice(cstart, cend));
eval(fn);
renderActionCard(JSON.parse(fs.readFileSync(process.argv[3], 'utf8')));
process.stdout.write(cardEl.innerHTML);
"""


def _render_card(trace: dict) -> str:
    """Run the REAL ``renderActionCard`` under node and return the HTML it wrote (the capture)."""
    if NODE is None:
        pytest.skip("node is absent; the action card cannot be rendered (no pass claimed)")
    source = INDEX.read_text(encoding="utf-8")
    assert "function renderActionCard(" in source, "index.html lost renderActionCard"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_CARD_HARNESS)
        harness = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(trace, fh)
        tracefile = fh.name
    try:
        done = subprocess.run([NODE, harness, str(INDEX), tracefile],
                              capture_output=True, text=True, timeout=60)
    finally:
        Path(harness).unlink(missing_ok=True)
        Path(tracefile).unlink(missing_ok=True)
    assert done.returncode == 0, "the card harness failed: %s" % (done.stderr or "")[:400]
    return html.unescape(done.stdout)


def test_new_ac1_card_names_both_gates_and_never_blames_the_person(capsys):
    """NEW-AC1 — the decision card shows the actor's entitlements AND the agent's scope, apart.

    The actor here MAY make the request; the agent's scope forbids it. So the card must carry the
    scope string (the limit the kernel refused on) and must NOT carry a sentence that lays the
    refusal at the person's door.
    """
    card = _render_card(_SCOPE_DENIED_TRACE)
    with capsys.disabled():
        print("\n--- NEW-AC1 captured card HTML ---\n" + card[:1600] + "\n--- end capture ---")
    # 1) both limits are named, on ONE card
    assert "payments.transfer" in card, "the actor's own right is not named on the card"
    assert "≤ 50,000 PLN" in card, "the agent's scope limit is not named on the card"
    assert "read-only" in card, "the agent's scope is not named in the kernel's own words"
    # 2) the two gates are SHOWN APART, each under its own label
    assert "What this person may do" in card
    assert "What this agent may do" in card
    # 3) the refusal is attributed to the SCOPE, never to the actor
    assert "warrant scope" in card, "the card does not name the gate the kernel refused on"
    lowered = card.lower()
    assert "no entitlement" not in lowered, "the card laid a scope refusal at the person's door"
    assert "not entitled" not in lowered, "the card laid a scope refusal at the person's door"

