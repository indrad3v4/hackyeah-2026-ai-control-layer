#!/usr/bin/env bash
# Rebuild docs/submission/TENET-deck.pdf from tenet-deck.html.
# The deck's fonts are bundled in ./fonts (Montserrat statics + DejaVu Sans Mono) so the
# PDF embeds real fonts instead of Skia Type3 glyph procedures — a PDF with Type3
# refs will not open in Adobe, iOS or most phone viewers.
set -eu
cd "$(dirname "$0")"
chromium --headless --no-sandbox --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=1 --allow-file-access-from-files --virtual-time-budget=9000 \
  --no-pdf-header-footer --print-to-pdf=TENET-deck.pdf "file://$PWD/tenet-deck.html"
# Verification: must print "Type3 refs: 0"
/opt/hermes/venv/bin/python3 - <<'PY'
import pymupdf, collections
d = pymupdf.open("TENET-deck.pdf")
t3 = [x for p in d for x in p.get_fonts(full=True) if x[2] == "Type3"]
print("pages:", d.page_count, "| Type3 refs:", len(t3))
print("fonts:", sorted({x[3] for p in d for x in p.get_fonts(full=True) if x[3]}))
PY
