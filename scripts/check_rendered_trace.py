#!/usr/bin/env python3
"""check_rendered_trace.py - the acceptance tool for the live security trace hero (ACT-5b AC5).

A source-reading test is what let round 1 ship a hero full of dashes: the page's prose said
"LIVE SECURITY TRACE" while the rendered result showed no evidence. This script boots nothing
itself. It drives a real browser (``chromium --headless --dump-dom``) against a URL that is
already serving, extracts the ``#traceCard`` hero text from the RENDERED DOM, and asserts the
hero shows the last enforced action's real evidence:

  * the agent id, the tool and ``ALLOW`` are present;
  * the warrant id (``W-9001``) and ``HTTP 200`` are present;
  * the receipt id from ``/api/live-trace`` is present;
  * none of round 1's dash markers survive: ``Requested action —``, ``no warrant in record``,
    ``Checks ?``.

Run it against an instance that has just executed ONE self-check::

    curl -s -X POST http://127.0.0.1:8099/api/scenario/self-check >/dev/null
    python scripts/check_rendered_trace.py http://127.0.0.1:8099/

Exit 0 on success (and prints the extracted hero text), 1 on failure, 2 when chromium is absent
(the check cannot be performed - it skips cleanly rather than claiming a pass).
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request

CHROMIUM = "/usr/bin/chromium"
DEFAULT_URL = "http://127.0.0.1:8099/"
VIRTUAL_TIME_BUDGET_MS = 6000
# Round 1's dash markers. The first two are literal and unambiguous. ``Checks ?`` is the round-1
# row where EVERY check was unknown while the kernel held evidence; it is checked as "the checks
# row shows no tick", not as a naive substring - AC2 requires a single ``?`` for identity when the
# record genuinely has no identity, so a lone ``?`` is honest, not a dash.
LITERAL_DASH_MARKERS = ("Requested action —", "no warrant in record")
ROUND1_CHECK_MARKER = "? Authorized before execution"


def _api_root(url: str) -> str:
    """The API origin for a served page URL (``http://host:port/`` -> ``http://host:port``)."""
    m = re.match(r"^(https?://[^/]+)", url)
    return m.group(1) if m else url.rstrip("/")


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - operator-supplied URL
        return json.loads(resp.read().decode("utf-8"))


def _extract_hero_text(dom: str) -> str:
    """The text of ``#traceCard`` from the rendered DOM, tags stripped and whitespace collapsed."""
    card = re.search(r'<article[^>]*id="traceCard"[^>]*>(.*?)</article>', dom, re.S)
    if not card:
        return ""
    text = re.sub(r"<[^>]+>", " ", card.group(1))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    chromium = shutil.which("chromium") or (CHROMIUM if shutil.which(CHROMIUM) else None)
    if not chromium or not shutil.which(CHROMIUM):
        print(f"check_rendered_trace: SKIP - chromium not found at {CHROMIUM}; "
              "cannot render the page (exit 2)")
        return 2

    # The receipt id must come from the live payload so the check compares render to data.
    try:
        payload = _fetch_json(_api_root(url) + "/api/live-trace")
    except Exception as exc:  # noqa: BLE001 - a missing instance is a failed check, not a crash
        print(f"check_rendered_trace: FAIL - could not read {_api_root(url)}/api/live-trace: {exc}")
        return 1
    trace = payload.get("trace") or {}
    receipt_id = str(trace.get("receipt_id") or "")
    agent = str(trace.get("agent") or "")
    tool = str((trace.get("action") or {}).get("tool") or "")
    decision = str(trace.get("decision") or "")
    warrant_id = str(((trace.get("checks") or {}).get("warrant") or {}).get("id") or "")

    try:
        dom = subprocess.run(
            [chromium, "--headless", "--no-sandbox", "--disable-gpu",
             f"--virtual-time-budget={VIRTUAL_TIME_BUDGET_MS}", "--dump-dom", url],
            capture_output=True, text=True, timeout=60).stdout
    except Exception as exc:  # noqa: BLE001
        print(f"check_rendered_trace: FAIL - chromium could not render {url}: {exc}")
        return 1

    hero = _extract_hero_text(dom)
    if not hero:
        print(f"check_rendered_trace: FAIL - no #traceCard text in the rendered DOM of {url}")
        return 1

    problems: list[str] = []
    for label, needle in (("agent id", agent), ("tool", tool), ("decision ALLOW", "ALLOW"),
                          ("warrant id", warrant_id or "W-9001"), ("HTTP 200", "HTTP 200"),
                          ("receipt id", receipt_id)):
        if needle and needle not in hero:
            problems.append(f"hero omits the {label} ({needle!r})")
    for marker in LITERAL_DASH_MARKERS:
        if marker in hero:
            problems.append(f"hero still renders a dash marker ({marker!r})")
    # The round-1 checks defect: every chip unknown. AC2 allows one honest ``?`` (identity when the
    # record has none) but NOT a row with no tick at all while the kernel holds evidence.
    if ROUND1_CHECK_MARKER in hero:
        problems.append(f"hero still renders the round-1 all-unknown checks row ({ROUND1_CHECK_MARKER!r})")
    if "Checks" in hero and "✓" not in hero.split("Checks", 1)[1]:
        problems.append("hero renders no ✓ in the checks row (Checks ? - the round-1 defect)")

    print("check_rendered_trace: hero text extracted from #traceCard:")
    print(f"  {hero}")
    if problems:
        print("\ncheck_rendered_trace: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncheck_rendered_trace: OK - the hero renders the kernel's real evidence "
          f"(agent {agent}, tool {tool}, decision {decision}, warrant {warrant_id}, "
          f"receipt {receipt_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
