#!/usr/bin/env bash
#
# Bring the whole system up on one machine, in live mode, against the real camera.
#
# The demo has seven processes that have to find each other, and until this
# existed every one of them was a remembered command line. A remembered command
# line is how you end up at a judging table with `master` holding an empty trust
# store, refusing every grant as `unregistered_issuer`, and looking exactly like
# a bug.
#
# What comes up, in dependency order:
#
#   shutter   8106   the gate. Started first: master discovers its trust card
#   presence  8101   motion, from the RSSI detector when it is up
#   vision    8105   personhood, from the camera through the hub's relay
#   intruder  8102   whether the motion has a device to account for it
#   caller    8103   the voice to the 911 operator, plus its transport on 8107
#   master    8900   the trust boundary, and the hub-facing surface
#   hub       8787   app/backend. The three surfaces talk to this and only this
#   edge      --     the camera, pushed up the edge link
#
# `caller` was missing from this list until 2026-09-20, and so was never
# started. Start Incident reached master, master had no
# HAWKEYE_CALLER_TRANSPORT_URL, and the call failed at the last hop with a 500 -
# after the human had already committed to dialling 911, which is the worst
# possible place in this system to discover a missing process.
#
# HAWKEYE_MODE=live is the point of the whole thing: the hub stops driving the
# scripted incident in master/simulated.py and starts reading what the mesh
# actually found.
#
#   ./scripts/up.sh              the Brio, live
#   ./scripts/up.sh --fixture    the recorded footage instead of a camera
#   ./scripts/up.sh --stop       stop everything this script started
#
# Logs land in .run/, one file per process. Nothing here daemonizes: this is a
# demo rig, not a deployment, and a process that dies should be visible in
# `ps` rather than quietly restarted into a state nobody chose.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.run"
PY="${PYTHON:-python3}"

# The camera. Index 0 is the Brio on this Mac, and every index opens and reports
# 1280x720, so "it works" proves nothing about which device answered. The
# identification procedure is in docs/hardware/logitech-camera.md.
CAMERA_INDEX="${HAWKEYE_CAMERA_INDEX:-0}"
FIXTURE="$ROOT/vision/tests/footage/person.mp4"

# The token the edge link authenticates with. Not optional theatre: without it
# any host on the same WiFi could inject frames into the camera feed, and the
# camera feed is the one surface a human is asked to believe.
export HAWKEYE_EDGE_TOKEN="${HAWKEYE_EDGE_TOKEN:-dev-token}"

# Peers, as the one env var that turns the wire on. With it set, claims are
# fetched over A2A, verified against the keys in the peers' own published trust
# cards, and discarded with a reason when they do not verify. Without it the
# in-process LocalMesh stands in and verifies nothing.
PEERS="presence=http://127.0.0.1:8101,intruder=http://127.0.0.1:8102,vision=http://127.0.0.1:8105,shutter=http://127.0.0.1:8106,caller=http://127.0.0.1:8103"

# Where master reaches caller's *transport* server, which is a second port
# caller serves alongside its A2A surface. Without this master logs a warning at
# startup and /a2a/start-call fails closed with a 500.
CALLER_TRANSPORT_URL="http://127.0.0.1:8107"

# The shared secret on the master -> caller trigger route, read by both
# processes straight from the environment rather than through Settings.
#
# Unset, `caller` treats /internal/start-call as unconfigured and answers 503 -
# "the internal trigger route is not configured on this deployment" - so a human
# pressing Start Incident gets a failure after they have already decided to call
# 911. Exported rather than passed per-process because master and caller must
# agree on it, and two places to set one secret is how they end up differing.
export HAWKEYE_INTERNAL_TRIGGER_TOKEN="${HAWKEYE_INTERNAL_TRIGGER_TOKEN:-dev-trigger-token}"

# Stop, then *check*, then insist.
#
# A stop that reports success without confirming the process is gone is worse
# than no stop at all: the next `up.sh` fails to bind a port and blames itself.
# So every process gets SIGTERM, a grace period to close its sockets, and
# SIGKILL if it is still there - and anything that survives all three is named
# on stdout rather than left for someone to find with `lsof` at a judging table.
stop_all() {
    if [ ! -d "$RUN" ]; then
        echo "nothing to stop: no $RUN"
        return 0
    fi

    local pids=() names=()
    for pidfile in "$RUN"/*.pid; do
        [ -e "$pidfile" ] || continue
        local name pid
        name="$(basename "$pidfile" .pid)"
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        rm -f "$pidfile"
        [ -n "$pid" ] || continue
        if kill -0 "$pid" 2>/dev/null; then
            echo "stopping $name ($pid)"
            kill "$pid" 2>/dev/null || true
            pids+=("$pid")
            names+=("$name")
        fi
    done
    [ ${#pids[@]} -gt 0 ] || return 0

    # uvicorn closes its listener on SIGTERM well within this; the wait is for
    # the edge link, which is mid-frame more often than not.
    local waited=0
    while [ $waited -lt 50 ]; do
        local alive=0
        for pid in "${pids[@]}"; do
            kill -0 "$pid" 2>/dev/null && alive=1
        done
        [ $alive -eq 0 ] && return 0
        sleep 0.1
        waited=$((waited + 1))
    done

    local i=0
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  ${names[$i]} ($pid) ignored SIGTERM; killing"
            kill -9 "$pid" 2>/dev/null || true
        fi
        i=$((i + 1))
    done
    sleep 0.5

    i=0
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "!! ${names[$i]} ($pid) is still running. Its port is still held." >&2
        fi
        i=$((i + 1))
    done
}

# `exec` is the whole point of this function's shape, and it was missing.
#
# The obvious spelling - `( cd "$dir" && "$@" & echo $! > pidfile )` - backgrounds
# the *compound* command, so `$!` is the pid of a subshell that then forks the
# real process as a child. Stopping that pid reaps the wrapper and leaves the
# server running, still holding its port. The restart that follows then fails to
# bind and says "address already in use", which reads as a stale process nobody
# can find rather than as a bug in this script.
#
# Backgrounding the subshell and having it `exec` means the subshell is
# *replaced* by the target process: same pid, no wrapper, and the pidfile names
# the thing that holds the port.
start() {
    local name="$1"; shift
    local dir="$1"; shift
    echo "  $name"
    ( cd "$dir" && exec "$@" > "$RUN/$name.log" 2>&1 ) &
    echo $! > "$RUN/$name.pid"
}

# Wait for a port rather than sleeping a guessed number of seconds. The failure
# this avoids is master starting before shutter can serve its trust card, which
# leaves master with an empty trust store for the life of the process: it
# refuses every grant as `unregistered_issuer`, correctly, and looks like a bug
# in the gate rather than a race at startup.
wait_for() {
    local name="$1" url="$2" tries=60
    while [ $tries -gt 0 ]; do
        if curl -sf -o /dev/null "$url"; then return 0; fi
        tries=$((tries - 1))
        sleep 0.5
    done
    echo "!! $name never answered $url. See $RUN/$name.log" >&2
    return 1
}

case "${1:-}" in
    --stop)
        stop_all
        exit 0
        ;;
esac

SOURCE_ARGS=(--source camera --index "$CAMERA_INDEX")
SOURCE_LABEL="the Brio at index $CAMERA_INDEX"
if [ "${1:-}" = "--fixture" ]; then
    SOURCE_ARGS=(--source fixture --path "$FIXTURE" --fps 8 --loop)
    SOURCE_LABEL="recorded footage ($FIXTURE)"
fi

stop_all
mkdir -p "$RUN"

echo "starting the mesh:"
start shutter  "$ROOT/agents" $PY -m agents shutter  --port 8106 --host 127.0.0.1
wait_for shutter http://127.0.0.1:8106/healthz

# Everything below discovers its peers' trust cards at startup, so shutter has
# to be answering before any of them run. They can come up together after that.
HAWKEYE_PEERS="$PEERS" start presence "$ROOT/agents" $PY -m agents presence --port 8101 --host 127.0.0.1
HAWKEYE_PEERS="$PEERS" start vision   "$ROOT/agents" $PY -m agents vision   --port 8105 --host 127.0.0.1
HAWKEYE_PEERS="$PEERS" start intruder "$ROOT/agents" $PY -m agents intruder --port 8102 --host 127.0.0.1
wait_for presence http://127.0.0.1:8101/healthz
wait_for vision   http://127.0.0.1:8105/healthz
wait_for intruder http://127.0.0.1:8102/healthz

# caller after the sensing agents, and for the same reason master goes after
# everything: it builds its trust store once, at startup, from the cards its
# peers serve. Started in the batch above it wins the race against them and
# comes up having registered only shutter - then refuses every claim it is
# asked to repeat, correctly, having never been able to verify the source.
#
# That failure is invisible until the worst moment. The agent is healthy, the
# call connects, and the voice has nothing it is allowed to say.
HAWKEYE_PEERS="$PEERS" start caller "$ROOT/agents" $PY -m agents caller --port 8103 --host 127.0.0.1 --transport-port 8107
wait_for caller   http://127.0.0.1:8103/healthz

# master last of the agents, so its trust store is built from cards that are
# already being served rather than from peers that are still binding a port.
HAWKEYE_PEERS="$PEERS" HAWKEYE_CALLER_TRANSPORT_URL="$CALLER_TRANSPORT_URL" \
    start master "$ROOT/agents" $PY -m agents master --port 8900 --host 127.0.0.1
wait_for master http://127.0.0.1:8900/healthz

echo "starting the hub, live:"
HAWKEYE_MODE=live \
HAWKEYE_MASTER_BASE_URL=http://127.0.0.1:8900 \
    start hub "$ROOT/app/backend" "$ROOT/app/backend/.venv/bin/python" -m hawkeye_backend.main
wait_for hub http://127.0.0.1:8787/healthz

echo "starting the camera: $SOURCE_LABEL"
start edge "$ROOT/vision" $PY -m hawkeye_vision.edge \
    --hub ws://127.0.0.1:8787 --token "$HAWKEYE_EDGE_TOKEN" "${SOURCE_ARGS[@]}"

cat <<EOF

up. HAWKEYE_MODE=live, so every surface is reading the mesh rather than a script.

  live console    http://127.0.0.1:8787/live
  replay console  http://127.0.0.1:8787/replay
  camera          http://127.0.0.1:8787/v1/camera/live
  master's view   http://127.0.0.1:8900/v1/state
  hub status      http://127.0.0.1:8787/v1/hub

  logs            $RUN/*.log
  stop            ./scripts/up.sh --stop

The iOS and watchOS apps point at this hub. Set Config.swift to the live path
and give it this machine's LAN address, not 127.0.0.1 - the simulator shares
the Mac's loopback but a phone on the WiFi does not.
EOF
