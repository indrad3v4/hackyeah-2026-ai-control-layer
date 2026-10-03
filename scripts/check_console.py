#!/usr/bin/env python3
"""check_console.py - the console's inline JavaScript must at least parse.

A duplicated `const` in one block scope is a SyntaxError at function-parse time: the whole
QA hook dies and the page silently loses its assertion output. Nothing else in the pipeline
parses this file, so the check lives here. Exit code is non-zero when a block fails.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "index.html", ROOT / "node" / "warrnt" / "console.html"]


def main() -> int:
    html = PAGE.read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
              if b.strip()]
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
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
