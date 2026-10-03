#!/usr/bin/env python3
"""Drive the console through a range of viewport sizes and read its own verdict.

The page computes the layout invariants itself (`index.html?qa=1` publishes them on
``#qa-report`` as data attributes). This script only supplies the viewports and collects the
answers, so there is one definition of "the layout is correct" and it lives in the page where a
reviewer can read it - not in a test that drifts away from it.

    python3 scripts/console_layout_sweep.py                       # file://index.html, default grid
    python3 scripts/console_layout_sweep.py --url http://127.0.0.1:8099/
    python3 scripts/console_layout_sweep.py --sizes 1150x700,1920x1080

Exit codes: 0 every size holds, 1 a size failed, 2 no browser available (a SKIP, never a PASS -
a sweep that cannot run must not look like a sweep that passed).

Needs Playwright:  pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The presentation size, the boundary of the responsive switch in both directions, the sizes a
# reviewer actually opens from (a VS Code panel, a laptop, a phone) and one absurdly large one.
DEFAULT_SIZES = ["400x600", "768x1024", "1024x768", "1150x700", "1262x568", "1366x768",
                 "1399x900", "1400x899", "1400x900", "1440x900", "1600x900", "1920x750",
                 "1920x1080", "2560x1440", "3840x2160"]

FIELDS = ("ok", "mode", "overlaps", "revokeOverTarget", "cut", "squeezed")


def load_page(page, url: str, width: int, height: int) -> dict:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="load")
    page.wait_for_selector("#qa-report", timeout=8000)
    report = page.eval_on_selector("#qa-report", """el => {
        const out = {};
        for (const k of ['ok','mode','overlaps','revokeOverTarget','cut','squeezed'])
            out[k] = el.dataset[k];
        out.text = el.textContent;
        return out;
    }""")
    report["viewport"] = f"{width}x{height}"
    report["ok"] = str(report.get("ok")).lower() == "true"
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--sizes", default=",".join(DEFAULT_SIZES))
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    url = args.url or (Path("index.html").resolve().as_uri() + "?qa=1&source=demo")
    if "?" not in url:
        url += "?qa=1&source=demo"
    sizes = []
    for item in args.sizes.split(","):
        w, _, h = item.strip().lower().partition("x")
        if w and h:
            sizes.append((int(w), int(h)))
    if not sizes:
        print("no sizes to sweep")
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP  no browser driver: pip install playwright && playwright install chromium")
        print(f"      {len(sizes)} sizes were not checked. This is a SKIP, not a pass.")
        return 2

    rows: list[dict] = []
    with sync_playwright() as play:
        try:
            browser = play.chromium.launch()
        except Exception as exc:                       # noqa: BLE001 - a missing binary is a SKIP
            print(f"SKIP  chromium is not installed ({str(exc)[:120]})")
            print("      run: playwright install chromium")
            return 2
        page = browser.new_page()
        for width, height in sizes:
            try:
                rows.append(load_page(page, url, width, height))
            except Exception as exc:                   # noqa: BLE001 - report, never hide
                rows.append({"viewport": f"{width}x{height}", "ok": False,
                             "text": f"the page did not answer: {type(exc).__name__}: {exc}"})
        browser.close()

    width = max(len(r["viewport"]) for r in rows)
    for row in rows:
        verdict = "OK " if row.get("ok") else "BAD"
        detail = (f"mode={row.get('mode')} overlaps={row.get('overlaps')} "
                  f"revokeOverTarget={row.get('revokeOverTarget')} unreachable={row.get('cut')} "
                  f"squeezed={row.get('squeezed')}")
        print(f"{verdict}  {row['viewport'].ljust(width)}  {detail}")
        if not row.get("ok"):
            print(f"       {str(row.get('text'))[:220]}")

    failed = [r for r in rows if not r.get("ok")]
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\n{len(rows) - len(failed)}/{len(rows)} viewports hold every layout invariant")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
