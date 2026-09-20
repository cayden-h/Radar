"""Ticks the collector -> features -> classifier pipeline and broadcasts
the result over a local WebSocket server; also serves the static frontend."""

import asyncio
import functools
import http.server
import json
import logging
import threading
import time

import websockets

from calibrate import summarize, suggest_thresholds
from classifier import BaselineClassifier
from collector import MacWifiCollector
from features import extract_features

logger = logging.getLogger(__name__)

CALIBRATION_PHASE_SECONDS = 20.0
CALIBRATION_GRACE_SECONDS = 5.0


def build_tick_payload(snapshot, classifier, window_seconds, clock=time.time):
    features = extract_features(snapshot, window_seconds=window_seconds)
    state = classifier.classify(features["variance"], features["motion_energy"])
    latest_rssi = snapshot[-1][1] if snapshot else None
    return {
        "type": "tick",
        "ts": clock(),
        "rssi": latest_rssi,
        "variance": features["variance"],
        "motion_energy": features["motion_energy"],
        "state": state,
    }


def _serve_static_dir(static_dir, port):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=static_dir)
    httpd = http.server.ThreadingHTTPServer(("localhost", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


async def serve(
    host="localhost",
    port=8765,
    static_dir="static",
    poll_hz=3.0,
    window_seconds=4.0,
    hysteresis_ticks=2,
):
    # Must hold a full calibration phase's samples without eviction: the
    # normal running buffer (window_seconds + 3.0) is deliberately short, but
    # a live calibration phase runs CALIBRATION_PHASE_SECONDS long and reads
    # the buffer only once, at the end of the phase.
    buffer_seconds = max(window_seconds + 3.0, CALIBRATION_PHASE_SECONDS + 5.0)
    collector = MacWifiCollector(poll_hz=poll_hz, buffer_seconds=buffer_seconds)
    # A short window reacts fast but ticks noisily; hysteresis_ticks requires
    # a new state to repeat that many consecutive ticks before it's reported,
    # so a single blip on the short window can't flip the badge on its own.
    classifier = BaselineClassifier(hysteresis_ticks=hysteresis_ticks)
    collector.start()

    connections = set()
    calibration_state = {"task": None}

    async def broadcast(payload):
        message = json.dumps(payload)
        for ws in list(connections):
            try:
                await ws.send(message)
            except Exception:
                # One misbehaving client (closed connection, protocol error,
                # anything) must not take the broadcast loop, and with it the
                # whole server, down for every other client.
                logger.warning("Dropping WebSocket client after send failure", exc_info=True)
                connections.discard(ws)

    async def run_calibration():
        try:
            # Grace period: gives the person time to physically get away from
            # the laptop/router after clicking the button, before the "still"
            # phase actually starts measuring.
            for remaining in range(int(CALIBRATION_GRACE_SECONDS), 0, -1):
                await broadcast({
                    "type": "calibration",
                    "phase": "prepare",
                    "instruction": "Get ready -- move away from the laptop and router",
                    "seconds_left": remaining,
                })
                await asyncio.sleep(1.0)

            phase_summaries = {}
            phases = (
                ("still", "Stand still, away from the laptop and router"),
                ("walk", "Walk back and forth between the laptop and the router"),
            )
            for label, instruction in phases:
                phase_start = time.time()
                for remaining in range(int(CALIBRATION_PHASE_SECONDS), 0, -1):
                    await broadcast({
                        "type": "calibration",
                        "phase": label,
                        "instruction": instruction,
                        "seconds_left": remaining,
                    })
                    await asyncio.sleep(1.0)
                phase_end = time.time()
                phase_samples = [s for s in collector.snapshot() if phase_start <= s[0] <= phase_end]
                phase_summaries[label] = summarize(phase_samples, window_seconds=window_seconds)

            thresholds = suggest_thresholds(phase_summaries["still"], phase_summaries["walk"])
            classifier.active_motion_ratio = thresholds["active_motion_ratio"]

            # suggest_thresholds() expresses its ratio relative to the still
            # phase's own measured mean, so the live EMA baseline must be
            # reset to that same number -- otherwise the new ratio is being
            # compared against whatever the baseline happened to be before
            # calibration ran (which, if the classifier had been reading
            # "active" continuously, is stuck at its untouched initial value,
            # since the baseline only adapts on "absent" ticks).
            classifier.baseline_motion_energy = max(
                phase_summaries["still"]["motion_energy"]["mean"], classifier.min_baseline_motion_energy
            )

            await broadcast({
                "type": "calibration",
                "phase": "done",
                "still": phase_summaries["still"],
                "walk": phase_summaries["walk"],
                "thresholds": thresholds,
            })
        except ValueError as exc:
            await broadcast({"type": "calibration", "phase": "error", "message": str(exc)})
        except asyncio.CancelledError:
            await broadcast({"type": "calibration", "phase": "cancelled"})
        finally:
            calibration_state["task"] = None

    async def handler(websocket):
        connections.add(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                cmd = data.get("cmd")
                if cmd == "calibrate":
                    if calibration_state["task"] is None:
                        calibration_state["task"] = asyncio.create_task(run_calibration())
                elif cmd == "cancel_calibration":
                    if calibration_state["task"] is not None:
                        calibration_state["task"].cancel()
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            connections.discard(websocket)

    async def broadcast_loop():
        poll_interval = 1.0 / poll_hz
        while True:
            payload = build_tick_payload(collector.snapshot(), classifier, window_seconds=window_seconds)
            await broadcast(payload)
            await asyncio.sleep(poll_interval)

    static_httpd = _serve_static_dir(static_dir, port + 1)
    print(f"WebSocket server on ws://{host}:{port}")
    print(f"Static frontend on http://{host}:{port + 1}/index.html")

    try:
        async with websockets.serve(handler, host, port):
            await broadcast_loop()
    finally:
        collector.stop()
        static_httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(serve())
