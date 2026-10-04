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


def wait_for_page(page, timeout_ms: int = 9000) -> None:
    """Wait for whatever this console publishes as its verdict - and carry on if it publishes
    none. The measurement below does not depend on the page's cooperation."""
    page.wait_for_load_state("load")
    try:
        page.wait_for_function(
            """() => Boolean(
                   window.__TENET_QA__ ||
                   document.querySelector('#qa-report[data-ok]') ||
                   (document.body && document.body.dataset && document.body.dataset.ok !== undefined)
               )""", timeout=timeout_ms)
    except Exception:                              # noqa: BLE001 - a silent page is measured anyway
        page.wait_for_timeout(1500)


MEASURE = """() => {
  const flow = [...document.body.children].filter(e => {
    const s = getComputedStyle(e);
    return s.position !== 'fixed' && s.display !== 'none' &&
           e.tagName !== 'SCRIPT' && e.id !== 'qa-report';
  });
  const rects = flow.map(e => e.getBoundingClientRect());
  const overlaps = [];
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const A = rects[i], B = rects[j];
    if (Math.min(A.bottom, B.bottom) - Math.max(A.top, B.top) > 4 &&
        Math.min(A.right, B.right) - Math.max(A.left, B.left) > 4)
      overlaps.push(flow[i].tagName.toLowerCase() + '/' + flow[j].tagName.toLowerCase());
  }
  const rv = document.getElementById('revoke'), tg = document.getElementById('target');
  let revokeOverTarget = false;
  if (rv && tg) {
    const a = rv.getBoundingClientRect(), c = tg.getBoundingClientRect();
    revokeOverTarget = a.top < c.bottom && a.bottom > c.top && a.left < c.right && a.right > c.left;
  }
  const cut = [...document.querySelectorAll('.tile,.taxo,footer,main,section')].filter(el => {
    const s = getComputedStyle(el);
    return (s.overflow === 'hidden' || s.overflowY === 'hidden') &&
           (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2);
  }).map(el => el.tagName.toLowerCase() + '.' + (el.className || ''));
  const squeezed = [...document.querySelectorAll('footer *,.holds *,.taxo .cell *')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 26 && r.height / Math.max(1, r.width) > 1.6 && e.children.length < 3;
  }).length;
  const de = document.documentElement;
  /* The page's own claim, in the three shapes consoles in this repo publish it. */
  const qa = window.__TENET_QA__ || null;
  const report = {viewport: innerWidth + 'x' + innerHeight,
                  mode: (qa && qa.layout) || (getComputedStyle(document.body).display),
                  overlaps: overlaps.length, overlap_list: overlaps,
                  revokeOverTarget: revokeOverTarget, cut: cut.length, cut_list: cut,
                  squeezed: squeezed,
                  page_claim: qa && typeof qa.ok === 'boolean' ? qa.ok
                              : (document.body.dataset.ok !== undefined
                                 ? document.body.dataset.ok === 'true' : null),
                  scrolls: de.scrollHeight > de.clientHeight + 2,
                  scrollH: de.scrollHeight, innerH: innerHeight};
  /* An overlap or unreadable content fails HERE, whoever the page says is fine. */
  report.ok = report.overlaps === 0 && !report.revokeOverTarget &&
              report.cut === 0 && report.squeezed === 0;
  return report;
}"""


def load_page(page, url: str, width: int, height: int) -> dict:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="load")
    wait_for_page(page)
    report = page.evaluate(MEASURE)
    report["viewport"] = f"{width}x{height}"
    report["ok"] = bool(report.get("ok"))
    # A page that claims to be fine while the geometry says otherwise is the worst outcome, not a
    # detail: the claim is what a reviewer reads in the browser.
    if report.get("page_claim") is True and not report["ok"]:
        report["contradiction"] = True
        report["text"] = (f"the page reports ok=true while the measurement finds "
                          f"{report['overlaps']} overlap(s) {report['overlap_list'][:3]}, "
                          f"{report['cut']} unreadable region(s) {report['cut_list'][:2]}")
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
        claim = {True: "page says ok", False: "page says NOT ok", None: "page publishes none"}
        detail = (f"layout={str(row.get('mode'))[:22]:22s} overlaps={row.get('overlaps')} "
                  f"revokeOverTarget={row.get('revokeOverTarget')} unreachable={row.get('cut')} "
                  f"squeezed={row.get('squeezed')}  [{claim.get(row.get('page_claim'))}]")
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
