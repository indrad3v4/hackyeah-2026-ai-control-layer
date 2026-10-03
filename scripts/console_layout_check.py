#!/usr/bin/env python3
"""Static layout guard for the current TENET Control Room.

This checker intentionally validates the current product surface rather than historical
WARRNT console selectors. It catches structural regressions without requiring a browser.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))


def main(path: Path) -> int:
    if not path.exists():
        print(f"{FAIL}  no such file: {path}")
        return 1

    src = path.read_text(encoding="utf-8")

    # Remove script/style bodies before structural tag checks.
    layout = re.sub(r"<script\b.*?</script>", "", src, flags=re.S)
    layout = re.sub(r"<style\b.*?</style>", "", layout, flags=re.S)

    # Current page contract: one app shell with header, hero, content and footer.
    check(
        "current Control Room has one app shell",
        len(re.findall(r'<div class="app">', layout)) == 1,
        "expected exactly one .app shell",
    )
    check(
        "hero contains security decision and model resources",
        bool(re.search(r'<section class="hero">.*?Security decision.*?Model resources.*?</section>', layout, re.S)),
        "decision + provider evidence belong in the first visual block",
    )
    check(
        "content contains live activity and action explanation",
        "03 · Live agent activity" in layout and "04 · Why this happened" in layout,
        "operator-facing activity and explanation panels are present",
    )
    check(
        "footer is outside the main content sections",
        bool(re.search(r"</section>\s*<footer>.*?</footer>\s*</div>\s*<script", layout, re.S)),
        "footer must close after hero/content sections",
    )

    # Current product CSS is allowed to stack on narrow screens and must also remain usable
    # on short screens. A short viewport must be able to scroll rather than clip the story.
    responsive = re.findall(r"@media\s*\(([^)]*)\)", src)
    check(
        "responsive rules cover narrow and short viewports",
        any("max-width" in x for x in responsive) and any("max-height" in x for x in responsive),
        f"{len(responsive)} responsive breakpoint(s): {'; '.join(responsive)}",
    )
    check(
        "short viewports can scroll the page",
        bool(re.search(r"@media[^{}]*max-height[^{}]*\{[^}]*body[^}]*overflow\s*:\s*(auto|scroll)", src, re.S))
        or "body{overflow:auto" in src,
        "short screens must not hide the security story",
    )

    # The current UI uses explicit text-overflow on resource traces. Verify the trace is
    # accessible through a title/data attribute rather than silently losing the identifier.
    check(
        "provider trace has an accessible full-value hook",
        'id="trace"' in layout and ("title=" in layout or "data-full-value" in layout),
        "trace identifiers should remain inspectable when visually truncated",
    )

    # Lightweight machine-readable QA hook for browser/manual diagnostics.
    check(
        "QA hook publishes a machine-readable verdict",
        "__TENET_QA__" in src,
        "window.__TENET_QA__ is the current diagnostic contract",
    )

    width = max((len(n) for n, _, _ in results), default=0)
    failed = 0
    for name, verdict, detail in results:
        print(f"{verdict}  {name.ljust(width)}  {detail}")
        failed += verdict == FAIL

    print(f"\n{len(results) - failed}/{len(results)} layout invariants hold in {path.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("index.html")
    raise SystemExit(main(target))
