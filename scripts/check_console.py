#!/usr/bin/env python3
"""check_console.py - the console's inline JavaScript must at least parse.

A duplicated `const` in one block scope is a SyntaxError at function-parse time: the whole
QA hook dies and the page silently loses its assertion output. Nothing else in the pipeline
parses this file, so the check lives here. Exit code is non-zero when a block fails.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Every surface whose inline JavaScript must parse: the console, the mirrored node console, and the
# observer's read-only room (NEW-AC4) - a syntax error there blanks a page the partner reads.
PAGES = [ROOT / "index.html", ROOT / "node" / "warrnt" / "console.html", ROOT / "observer.html"]

# ACT-7e: the action card must render BOTH its boundary line and its "what actually happened" line
# from the EVIDENCE (the composed `upstream.contacted` / `executed` facts), never from the decision
# label. The two traces below are the exact shapes the kernel composer emits for a person-resolved
# action: one that really crossed (a human-resolved execution, decision stays "human") and one that
# did not (a person's denial). The assertions are behavioural: the real ``renderActionCard`` is run
# under node against a minimal DOM and the text it writes is read back.
_CARD_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('function renderActionCard(');
if (start < 0) { console.error('renderActionCard not found'); process.exit(1); }
const end = src.indexOf('\nfunction verdictTrace(', start);
if (end < 0) { console.error('end of renderActionCard not found'); process.exit(1); }
const fn = src.slice(start, end);
let cardEl = { style: {}, innerHTML: '' };
const els = { actionCard: cardEl, controlBlock: { style: {}, innerHTML: '' } };
global.$ = id => els[id] || { style: {}, innerHTML: '' };
global.esc = s => String(s == null ? '' : s);
global.jsonSafe = s => { try { return JSON.stringify(s); } catch (e) { return String(s); } };
global.techRow = () => '';
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
const cases = {
  approved: {decision: 'human', state: 'approved', executed: true, receipt_id: 'r', action_id: 'A-1',
    action: {tool: 'fx.read_rate', class: 'observe', args: {}},
    upstream: {contacted: true, http_status: 200, value: 1.1225}},
  denied: {decision: 'human', state: 'denied', executed: false, receipt_id: 'r', action_id: 'A-2',
    action: {tool: 'fx.read_rate', class: 'observe', args: {}},
    upstream: {contacted: false}},
  /* NEW-AC5 - the fourth state: a hold the brake expired. The card must say so, name the clock the
   * kernel recorded (decided_ts), and never print the 'waiting for you' line. */
  expired: {decision: 'human', state: 'expired', decided_ts: 1759420002, executed: false,
    receipt_id: 'r', action_id: 'A-4',
    action: {tool: 'infra.deploy', class: 'irreversible', args: {}},
    upstream: {contacted: false}}
};
const out = {};
for (const k of Object.keys(cases)) { renderActionCard(cases[k]); out[k] = els.actionCard.innerHTML; }
process.stdout.write(JSON.stringify(out));
"""


def _check_action_card() -> tuple[int, str]:
    """Run renderActionCard under node against two traces; assert on the text it actually wrote.

    Returns ``(failed, detail)``. Skips (0 failures) when node is absent - a check that cannot run
    claims no pass.
    """
    node = shutil.which("node")
    if not node:
        return 0, "node not found - SKIP (cannot run the action-card render)"
    card_source = ROOT / "index.html"
    if not card_source.exists():
        return 1, "index.html is missing; the action card cannot be checked"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_CARD_HARNESS)
        harness = fh.name
    try:
        done = subprocess.run([node, harness, str(card_source)], capture_output=True, text=True)
    finally:
        Path(harness).unlink(missing_ok=True)
    if done.returncode != 0:
        return 1, "the action-card harness failed to run: " + (done.stderr or "").strip()[:400]
    try:
        rendered = json.loads(done.stdout)
    except ValueError:
        return 1, "the action-card harness produced no readable render: " + done.stdout[:200]
    approved = html.unescape(rendered.get("approved", ""))
    denied = html.unescape(rendered.get("denied", ""))
    expired = html.unescape(rendered.get("expired", ""))
    failures = []
    # 1) the approved card proves the crossing from evidence: "Data leaves TENET" and NOT waiting.
    if "Data leaves TENET" not in approved:
        failures.append("approved card: the proven crossing is not rendered (no 'Data leaves TENET')")
    if "waiting for you" in approved:
        failures.append("approved card: still shows 'waiting for you' though the record proves a crossing")
    if "1.1225" not in approved:
        failures.append("approved card: the far side's value is not shown")
    # 2) the denied card shows the non-crossing, and never the crossing line.
    if "Nothing left TENET" not in denied:
        failures.append("denied card: the non-crossing is not rendered (no 'Nothing left TENET')")
    if "Data leaves TENET" in denied:
        failures.append("denied card: shows a crossing the record never proved")
    if "waiting for you" in denied:
        failures.append("denied card: shows the waiting line for a resolved denial")
    # 3) NEW-AC5 - the FOURTH state: a hold the brake expired says expired, with the clock the
    # kernel recorded, and never the waiting line (a dead hold is not waiting for anyone).
    if "expired" not in expired.lower():
        failures.append("expired card: the fourth state is not named (no 'expired')")
    if not _hhmm(expired):
        failures.append("expired card: the fourth state is rendered without a clock")
    if "waiting for you" in expired:
        failures.append("expired card: shows the waiting line for a hold that already died")
    if "Data leaves TENET" in expired:
        failures.append("expired card: shows a crossing an expired hold never made")
    return (1 if failures else 0), ("; ".join(failures) if failures
                                    else "approved shows the crossing, denied none, expired its clock")


_HHMM = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")


def _hhmm(text: str) -> str:
    """The HH:MM clock inside a rendered card, or '' - the surface must carry a real time."""
    m = _HHMM.search(text)
    return m.group(0) if m else ""


def main() -> int:
    pages = [(p, p.read_text(encoding="utf-8")) for p in PAGES if p.exists()]
    if len(pages) != len(PAGES):
        missing = [str(p.relative_to(ROOT)) for p in PAGES if not p.exists()]
        print("check_console: missing console surface(s): " + ", ".join(missing))
        return 1
    blocks = []
    for page, html in pages:
        page_blocks = [b for b in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
                       if b.strip()]
        blocks.extend((page, b) for b in page_blocks)
    node = shutil.which("node")
    if not node:
        print("check_console: node not found - SKIP (cannot parse JavaScript)")
        return 0
    failed = 0
    for i, (page, block) in enumerate(blocks, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(block)
            path = fh.name
        done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        status = "OK" if done.returncode == 0 else "SYNTAX ERROR"
        print(f"check_console: {page.relative_to(ROOT)} script block {i}/{len(blocks)} -> {status}")
        if done.returncode:
            failed += 1
            print((done.stderr or "").strip()[:600])
        Path(path).unlink(missing_ok=True)
    print(f"check_console: {len(blocks) - failed}/{len(blocks)} inline blocks parse across {len(pages)} surfaces")

    # ACT-7e: the action card's two evidence-driven lines, asserted on the real render.
    card_failed, card_detail = _check_action_card()
    print(f"check_console: action card index.html -> {'FAIL' if card_failed else 'OK'}")
    print(f"    {card_detail}")
    failed += card_failed
    return 1 if failed else 0



if __name__ == "__main__":
    raise SystemExit(main())
