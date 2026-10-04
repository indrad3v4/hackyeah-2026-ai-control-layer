#!/usr/bin/env bash
# Run every check this submission owes a judge, in one command, with a verdict at the end.
#
#   bash scripts/run_all_checks.sh                 # everything
#   SKIP_NETWORK=1 bash scripts/run_all_checks.sh  # skip the checks that clone the node repo
#   SKIP_NODE=1 bash scripts/run_all_checks.sh     # skip the mirrored node's own tests and gates
#   PYTHON=/path/to/python bash scripts/run_all_checks.sh
#
# Exit code: 0 everything that ran passed · 1 something failed · 2 nothing could run.
#
# A SKIP is never counted as a pass. If a check cannot run here, this script says so and tells you
# the one line that would make it run - an unchecked thing must not look like a checked thing.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
ROOT="$(pwd)"

if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python; fi

PASS=0; FAIL=0; SKIP=0
ROWS=()

# seconds, portably enough for a summary table
now() { date +%s.%N 2>/dev/null || date +%s; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1fs", b-a}' 2>/dev/null || echo "-"; }

# run <name> <why-it-matters> [SKIPON=rc] [NEEDS=import] [SKIPVAR=NAME] <command...>
run() {
  local name="$1"; shift
  local why="$1"; shift
  local skipon="" needs="" skipvar=""

  # Leading KEY=VALUE arguments configure this check; the rest is the command to run. At least
  # one argument is required, so this cannot swallow the command itself.
  while [ "$#" -gt 1 ] && [[ "$1" =~ ^(SKIPON|NEEDS|SKIPVAR)= ]]; do
    case "$1" in
      SKIPON=*)  skipon="${1#*=}" ;;
      NEEDS=*)   needs="${1#*=}" ;;
      SKIPVAR=*) skipvar="${1#*=}" ;;
    esac
    shift
  done

  if [ -n "$skipvar" ] && [ -n "${!skipvar:-}" ]; then
    ROWS+=("SKIP|$name|-|$why (skipped via $skipvar)"); SKIP=$((SKIP+1)); return
  fi
  if [ -n "$needs" ] && ! "$PY" -c "import $needs" >/dev/null 2>&1; then
    ROWS+=("SKIP|$name|-|$why (needs: pip install -r node/requirements.txt)"); SKIP=$((SKIP+1)); return
  fi

  printf '  ... %s\n' "$name"
  local t0 t1 rc
  t0="$(now)"
  "$@" >/tmp/warrnt_check.out 2>&1
  rc=$?
  t1="$(now)"
  local dur; dur="$(elapsed "$t0" "$t1")"

  if [ -n "$skipon" ] && [ "$rc" = "$skipon" ]; then
    ROWS+=("SKIP|$name|$dur|$why (not available here)"); SKIP=$((SKIP+1)); return
  fi
  if [ "$rc" = "0" ]; then
    ROWS+=("PASS|$name|$dur|$why"); PASS=$((PASS+1))
  else
    ROWS+=("FAIL|$name|$dur|$why"); FAIL=$((FAIL+1))
    printf '\n     ---- %s failed (rc=%s) ----\n' "$name" "$rc"
    sed 's/^/     /' /tmp/warrnt_check.out | tail -18
    printf '\n'
  fi
}

echo "WARRNT/TENET - running every check from $ROOT"
echo

# --------------------------------------------------------------------- the console surface
run "console: inline JavaScript parses" "a syntax error blanks the whole page" \
    "$PY" scripts/check_console.py

run "console: layout invariants" "grid rows, the kill-switch floor, the responsive fallback" \
    "$PY" scripts/console_layout_check.py index.html

run "console: 15 viewports" "no overlap or clipped text at any size" SKIPON=2 \
    "$PY" scripts/console_layout_sweep.py

# --------------------------------------------------------------------- the submission contract
# Before anything runs the node: running it writes state into node/, which would then look like
# mirror drift and hide the real question - does node/ match the pinned commit?
run "mirror: matches the pinned commit" "node/ must equal the canonical repo or judges read stale code" \
    SKIPVAR=SKIP_NETWORK bash scripts/sync-node.sh --check

# --------------------------------------------------------------------- the enforcement node
HAD_STATE=0; [ -d node/state ] && HAD_STATE=1
run "node: the test suite" "positive and negative cases per control (D10)" \
    NEEDS=fastapi "$PY" -m pytest -q node/tests

run "node: proof gates" "console, security boundaries, live vector, demo path" \
    NEEDS=fastapi bash -c "cd node && $PY scripts/console_check.py >/dev/null && $PY scripts/security_boundaries.py >/dev/null && echo 'gates ok'"

# Running the node leaves its own state behind; that is not the submission's, so put it back.
if [ "$HAD_STATE" = "0" ] && [ -d node/state ] && [ -z "$(git ls-files node/state 2>/dev/null)" ]; then
  rm -rf node/state
fi

echo
echo "================ summary ================"
printf '%-6s %-38s %-7s %s\n' "STATE" "CHECK" "TIME" "WHY IT MATTERS"
for row in "${ROWS[@]}"; do
  IFS='|' read -r state name dur why <<< "$row"
  printf '%-6s %-38s %-7s %s\n' "$state" "$name" "$dur" "$why"
done
echo "------------------------------------------"
echo "passed $PASS   failed $FAIL   skipped $SKIP"

if [ "$FAIL" -gt 0 ]; then
  echo "VERDICT: FAIL - at least one check did not hold."
  exit 1
fi
if [ "$PASS" -eq 0 ]; then
  echo "VERDICT: nothing ran. Install the node's dependencies and re-run:"
  echo "  pip install -r node/requirements.txt"
  exit 2
fi
if [ "$SKIP" -gt 0 ]; then
  echo "VERDICT: PASS for everything that ran, with $SKIP skipped (each says why above)."
  exit 0
fi
echo "VERDICT: PASS - every check ran and held."
