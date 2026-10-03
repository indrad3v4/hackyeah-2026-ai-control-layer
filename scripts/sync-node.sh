#!/usr/bin/env bash
# Regenerate node/ from the canonical repository. --check verifies the mirror against the pinned commit.
set -euo pipefail
REPO="${WARRNT_REPO:-https://github.com/indrad3v4/warrnt}"
PIN="831b1667200e6af25b6be76bbafd95467a7e2ee8"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 "$REPO" "$TMP/src"
cd "$TMP/src"
if [ "${1:-}" = "--check" ]; then
  have=$(git rev-parse HEAD)
  if [ "$have" != "$PIN" ]; then echo "MIRROR DRIFT: canonical head $have · pinned $PIN"; exit 1; fi
  echo "pin ok: $PIN"
fi
git archive "$PIN" | tar -x -C "$TMP"
rm -rf "$HERE/node"; mkdir "$HERE/node"; cp -r "$TMP/src/." "$HERE/node/"
rm -rf "$HERE/node/.git"
find "$HERE/node" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$HERE/node/MIRROR.md" <<'MIRROR'
# This is a mirror, not the source of truth

`node/` is a verbatim copy of **https://github.com/indrad3v4/warrnt** at the commit pinned in
`scripts/sync-node.sh`. Why it is here: a reviewer should be able to read this submission — the
site, the documents **and the running code with its tests** — without leaving the package. The
mirror exists so the Python is in this repository; it does not move the source of truth.

- **Canonical repository:** https://github.com/indrad3v4/warrnt — every change lands there, each
  through a pull request that the Prelint review app comments on (`AGENTS.md` there carries the
  frozen decisions D1–D13).
- **Do not edit `node/` here.** An edit here is invisible to the node's own tests and will be
  overwritten by the next sync.
- **Regenerate / verify:** `bash scripts/sync-node.sh` · `bash scripts/sync-node.sh --check`.

Contents: the whole node (`warrnt/` — kernel, registry, plugins, policy, receipts, anchor),
`tests/` (86 tests), `scripts/` (the four proof runs) and its own README.
MIRROR
echo "node/ regenerated from $REPO@${PIN:0:12} ($(find "$HERE/node" -name '*.py' | wc -l) python files)"
