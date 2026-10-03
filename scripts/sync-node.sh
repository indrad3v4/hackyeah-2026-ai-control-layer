#!/usr/bin/env bash
# Regenerate node/ from the canonical repository. --check verifies the mirror byte-for-byte,
# because a check that only compares the remote head to the pin cannot see an edit made here.
set -euo pipefail
REPO="${WARRNT_REPO:-https://github.com/indrad3v4/warrnt}"
PIN="9d3eb2dc2c06cde48a6eb018d72c9d87f8f19a0c"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 "$REPO" "$TMP/src"
cd "$TMP/src"
have=$(git rev-parse HEAD)
if [ "${1:-}" = "--check" ] && [ "$have" != "$PIN" ]; then
  echo "MIRROR DRIFT: canonical head $have · pinned $PIN"; exit 1
fi
git archive "$PIN" | tar -x -C "$TMP"
rm -rf "$TMP/ref"; mkdir "$TMP/ref"; cp -r "$TMP/src/." "$TMP/ref/"; rm -rf "$TMP/ref/.git"
find "$TMP/ref" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

if [ "${1:-}" = "--check" ]; then
  # generated caches are not part of the mirror: pytest writes .pytest_cache into node/
  # when the CI runs the node tests before this step, and that is not drift.
  if ! diff -r --exclude=__pycache__ --exclude=.pytest_cache --exclude=MIRROR.md "$TMP/ref" "$HERE/node" > "$TMP/diff.txt" 2>&1; then
    echo "MIRROR DRIFT: node/ differs from $REPO@${PIN:0:12}"
    head -30 "$TMP/diff.txt"
    exit 1
  fi
  echo "pin ok: $PIN · content identical to node/"
  exit 0
fi
rm -rf "$HERE/node"; mkdir "$HERE/node"; cp -r "$TMP/ref/." "$HERE/node/"
cat > "$HERE/node/MIRROR.md" <<'MIRROR'
# This is a mirror, not the source of truth

`node/` is a verbatim copy of **https://github.com/indrad3v4/warrnt** at the commit pinned in
`scripts/sync-node.sh`. Why it is here: a reviewer should be able to read this submission — the
site, the documents **and the running code with its tests** — without leaving the package. The
mirror exists so the Python is in this repository; it does not move the source of truth.

- **Canonical repository:** https://github.com/indrad3v4/warrnt — every change lands there, each
  through a pull request.
- **Do not edit `node/` here.** An edit here is invisible to the node's own tests, and
  `scripts/sync-node.sh --check` now compares content, so it will fail the pull request.
- **Regenerate / verify:** `bash scripts/sync-node.sh` · `bash scripts/sync-node.sh --check`.

Contents: the whole node (`warrnt/` — kernel, registry, plugins, policy, receipts, anchor),
`tests/`, `scripts/` (the proof runs) and its own README.
MIRROR
echo "node/ regenerated from $REPO@${PIN:0:12} ($(find "$HERE/node" -name '*.py' | wc -l) python files)"
