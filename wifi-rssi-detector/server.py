"""Ticks the collector -> features -> classifier pipeline and broadcasts
the result over a local WebSocket server; also serves the static frontend."""

import asyncio
import functools
import http.server
import json
import threading
import time

import websockets

from classifier import BaselineClassifier
from collector import MacWifiCollector
from features import extract_features


def build_tick_payload(snapshot, classifier, window_seconds, clock=time.time):
    features = extract_features(snapshot, window_seconds=window_seconds)
    state = classifier.classify(features["variance"], features["motion_energy"])
    latest_rssi = snapshot[-1][1] if snapshot else None
    return {
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


async def serve(host="localhost", port=8765, static_dir="static", poll_hz=3.0, window_seconds=12.0):
    collector = MacWifiCollector(poll_hz=poll_hz, buffer_seconds=window_seconds + 3.0)
    classifier = BaselineClassifier()
    collector.start()

    connections = set()

    async def handler(websocket):
        connections.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            connections.discard(websocket)

    async def broadcast_loop():
        poll_interval = 1.0 / poll_hz
        while True:
            payload = build_tick_payload(collector.snapshot(), classifier, window_seconds=window_seconds)
            message = json.dumps(payload)
            for ws in list(connections):
                try:
                    await ws.send(message)
                except websockets.exceptions.ConnectionClosed:
                    connections.discard(ws)
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
