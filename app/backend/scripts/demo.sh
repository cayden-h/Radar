#!/usr/bin/env bash
#
# Boot the Hawk Eye hub in simulated mode and run the scripted incident end to end.
#
# Needs no Raspberry Pi, no router, no agents, and no network beyond loopback.
#
#   ./scripts/demo.sh              # realistic timing, about 50 seconds
#   SPEED=0.35 ./scripts/demo.sh   # rehearsal speed
#   PORT=9000 ./scripts/demo.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8787}"
SPEED="${SPEED:-1.0}"
HOST="127.0.0.1"
BASE="http://${HOST}:${PORT}"
LOG="$(mktemp -t hawkeye-demo)"

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v uv >/dev/null 2>&1; then
  echo "no .venv found; creating one with uv"
  uv venv --python 3.13 >/dev/null
  uv pip install -e . >/dev/null
  PY=.venv/bin/python
else
  echo "no .venv and no uv. Run: python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "== booting hub in simulated mode on ${BASE} (speed ${SPEED}x) =="
HAWKEYE_MODE=simulated \
HAWKEYE_PORT="$PORT" \
HAWKEYE_HOST="$HOST" \
HAWKEYE_SIM_SPEED="$SPEED" \
  "$PY" -m hawkeye_backend.main >"$LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.2
done
if ! curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then
  echo "hub did not come up. Server log:" >&2
  cat "$LOG" >&2
  exit 1
fi

echo
echo "== GET /v1/hub =="
curl -fsS "${BASE}/v1/hub" | "$PY" tools/summarize.py hub

echo
echo "== GET /v1/state  (idle: two confirmed people and one unconfirmed perturbation) =="
curl -fsS "${BASE}/v1/state" | "$PY" tools/summarize.py state

echo
echo "== WS /v1/stream, detection then tap =="
echo "   agents/people loses a breathing signature and nobody is dialled. It shows"
echo "   up in interior state, respiration_lost_s climbs, and the system waits."
echo "   Then a person taps Fire, which is what releases the call."
echo

WATCH_SECONDS=$("$PY" -c "print(max(26.0, 60.0 * $SPEED + 8))")
"$PY" tools/ws_probe.py --url "ws://${HOST}:${PORT}/v1/stream" --seconds "$WATCH_SECONDS" &
PROBE_PID=$!

sleep 2
curl -fsS -X POST "${BASE}/v1/demo/run" >/dev/null

# The detection lands and nothing dials. Let it sit, then press the button, which
# is the only thing that starts a call.
sleep "$("$PY" -c "print(8 * $SPEED)")"
echo
echo "   -- tapping Fire (POST /v1/incident, raised_by user) --"
curl -fsS -X POST "${BASE}/v1/incident" \
  -H 'content-type: application/json' \
  -d '{"incident_type":"fire"}' >/dev/null

# Mid-incident, the resident types into the "what is happening" box.
sleep "$("$PY" -c "print(12 * $SPEED)")"
INCIDENT_ID=$(curl -fsS "${BASE}/v1/hub" | "$PY" tools/summarize.py incident_id)
if [ -n "$INCIDENT_ID" ]; then
  curl -fsS -X POST "${BASE}/v1/incident/${INCIDENT_ID}/context" \
    -H 'content-type: application/json' \
    -d '{"text":"My mother has COPD and there is a space heater in that bedroom."}' >/dev/null
fi

wait $PROBE_PID

echo
echo "== GET /v1/incident/${INCIDENT_ID}/replay =="
curl -fsS "${BASE}/v1/incident/${INCIDENT_ID}/replay" | "$PY" tools/summarize.py replay

echo
echo "== done. Server log at ${LOG} =="
