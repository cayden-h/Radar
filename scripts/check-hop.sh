#!/usr/bin/env bash
# Prove the Pi can reach the hub before anything depends on it.
#
# Run this on the Pi. It answers one question: does this network carry
# device-to-device traffic, or is client isolation on? Everything downstream is
# built on the answer being yes, and finding out at 3am is not a plan.
set -uo pipefail

HUB="${HAWKEYE_HUB_HOST:-hawkeye-hub.local}"
PORT="${HAWKEYE_HUB_PORT:-8787}"

echo "Checking the hop to ${HUB}:${PORT}"
echo

printf '1. The hub name resolves ... '
if ADDR=$(python3 -c 'import socket,sys; print(socket.gethostbyname(sys.argv[1]))' "${HUB}" 2>/dev/null); then
  echo "yes, ${ADDR}"
else
  echo "NO"
  echo
  echo "   The name ${HUB} does not resolve from this box."
  echo "   On the Mac, confirm it is advertising:  dns-sd -B _http._tcp"
  echo "   Or find the Mac's address and set it explicitly:"
  echo "     Mac:  ipconfig getifaddr en0"
  echo "     Pi:   HAWKEYE_HUB_HOST=<that address> ./scripts/check-hop.sh"
  exit 1
fi

printf '2. The hub port answers ... '
if python3 -c 'import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5).close()' "${HUB}" "${PORT}" 2>/dev/null; then
  echo "yes"
else
  echo "NO"
  echo
  echo "   The name resolves but the port does not answer. In order of likelihood:"
  echo "   a. The hub is not running. On the Mac:"
  echo "        cd app/backend && .venv/bin/python -m hawkeye_backend.main"
  echo "   b. The macOS firewall is blocking incoming connections."
  echo "        System Settings > Network > Firewall"
  echo "   c. CLIENT ISOLATION is on for this WiFi network. This is the one you"
  echo "      cannot fix from your side: the access point is refusing to carry"
  echo "      traffic between two of its own clients. Move both boxes onto a"
  echo "      phone hotspot, which has no isolation because you own it."
  exit 1
fi

printf '3. The hub answers /healthz ... '
if BODY=$(curl -fsS --max-time 5 "http://${HUB}:${PORT}/healthz" 2>/dev/null); then
  echo "yes"
  echo "   ${BODY}"
else
  echo "NO"
  echo "   The port is open but the hub did not answer. Check the hub's log."
  exit 1
fi

echo
printf '4. The camera relay has a frame ... '
if curl -fsS --max-time 5 -o /dev/null "http://${HUB}:${PORT}/v1/camera/still" 2>/dev/null; then
  echo "yes"
else
  echo "not yet, which is expected before the edge starts"
fi

echo
echo "The hop works. Start the edge:"
echo "  python -m hawkeye_vision.edge --hub ws://${HUB}:${PORT} --token \"$HAWKEYE_EDGE_TOKEN\""
