#!/usr/bin/env bash
# TENET on a container platform - the whole product in ONE process tree, two roles.
#
#   1. the real tool server (Frankfurter reference rates) on loopback - the upstream the
#      kernel is told about, and the only thing here that talks to the outside world;
#   2. the TENET control plane on $PORT - the public surface (Control Room, /api/*, /health).
#
# Why a script instead of a one-line start command: the platform starts exactly one process,
# and the enforcement demo is worthless unless the call has somewhere real to go. Starting the
# upstream here keeps the boundary honest - the control plane is pointed at it by URL
# (WARRNT_UPSTREAM) and never imports it, so the kernel still decides before a byte leaves.
#
# No upstream means no crossing: if the tool server fails to bind, the control plane comes up
# in its DEGRADED shape and /api/demo/run answers 503 rather than inventing a rate.
set -euo pipefail

UPSTREAM_PORT="${TENET_UPSTREAM_PORT:-8210}"
UPSTREAM_LOG="${TENET_UPSTREAM_LOG:-/tmp/tenet-upstream-calls.jsonl}"
PORT="${PORT:-8080}"

python -m upstream.frankfurter_server --port "$UPSTREAM_PORT" --log "$UPSTREAM_LOG" &
UPSTREAM_PID=$!
trap 'kill "$UPSTREAM_PID" 2>/dev/null || true' EXIT

# Wait for the tool server to answer before the kernel is ever told about it: a URL that is not
# listening yet would turn the first real call into a connection error, which the jury would
# read as a broken product. Bounded, so a dead upstream cannot block the platform's health check.
for _ in $(seq 1 40); do
  if python - "$UPSTREAM_PORT" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
  then break; fi
  sleep 0.25
done

export WARRNT_UPSTREAM="http://127.0.0.1:${UPSTREAM_PORT}/mcp"

# One worker: the kernel's state (warrants, receipts, chain) lives in this process, and a second
# worker would be a second authority over the same files. The app object, not an import string,
# so the lifespan that seeds the kernel runs on the process actually serving requests.
exec uvicorn control_plane.app:app --host 0.0.0.0 --port "$PORT" --workers 1
