"""What runs on the Pi. Capture, encode, push. Nothing else.

This module exists so the Pi never has to run a model. A Pi 4B takes roughly a
second per frame on YOLO11m and the budget in the root CLAUDE.md is three
seconds motion to wrist, so the tracker lives on the Mac and this ships it
pixels.

Run it:

    python -m hawkeye_vision.edge --hub ws://hawkeye-hub.local:8787 --token "$HAWKEYE_EDGE_TOKEN"

It dials out and keeps dialling. The hub never dials the Pi, because the Pi's
address moves every time the network changes and the only thing this box needs
to know about the world is where the hub is.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from hawkeye_backend.edge.wire import EdgeFrameHeader, EdgeHello

from hawkeye_vision.frames import FrameSource
from hawkeye_vision.narrate import encode_jpeg

logger = logging.getLogger(__name__)

#: Long edge of a pushed frame. Larger than the narration thumbnail because this
#: is what a human watches, not what a model samples at one frame per second.
EDGE_LONG_EDGE = 960
EDGE_JPEG_QUALITY = 70

#: Reconnect backoff bounds. The ceiling is low on purpose: this link coming
#: back within a few seconds of the network returning is worth more than being
#: polite to a hub that is down.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 10.0

#: Where the shutter agent listens on this same box.
DEFAULT_SHUTTER_URL = "http://127.0.0.1:8106"

#: The shutter's two A2A methods and the path they live on, from
#: `agents/shutter/agent.py` and `agents/core/transport.py`. Named here rather
#: than spelled inline so a rename upstream is one edit, not three.
METHOD_CHALLENGE = "shutter.challenge"
METHOD_OPEN = "shutter.open"
CLAIM_TARGET_PATH = "/a2a"


def open_source(kind: str, index: int, path: str | None) -> FrameSource:
    """Build the frame source named on the command line.

    `kind` is explicit rather than inferred from the path, because the whole
    point of `FrameSource.source` is that a video file must not be able to
    present itself as a camera by accident.
    """
    if kind == "camera":
        from hawkeye_vision.webcam import MacCamera

        return MacCamera(index=index)
    if kind == "fixture":
        from hawkeye_vision.fixture import FileFixture

        if not path:
            raise SystemExit("--source fixture needs --path")
        return FileFixture(path)
    raise SystemExit(f"unknown source: {kind!r}. Use 'camera' or 'fixture'.")


async def _rpc(shutter_url: str, method: str, params: dict) -> dict:
    """One JSON-RPC 2.0 call to the shutter agent on this box.

    Raises on a transport failure or a JSON-RPC error. A `result` comes back as
    a plain dict.

    **A refusal is not an error here.** `agents/shutter/agent.py` returns a
    refusal as a signed *result*, deliberately: an error frame would make a
    successful defence look like a malfunction, and would leave the reason in a
    transport envelope the sealed record never sees. So a JSON-RPC error means
    the call itself was wrong, which is our bug, not the shutter refusing.
    """
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as http:
        response = await http.post(
            f"{shutter_url}{CLAIM_TARGET_PATH}",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers={"content-type": "application/json"},
        )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        error = body["error"]
        raise RuntimeError(f"{method} failed: {error.get('code')} {error.get('message')}")
    return body.get("result") or {}


async def _answer_challenge(socket, message, shutter_url: str) -> None:  # noqa: ANN001
    """Ask the local shutter for a nonce and send it up."""
    from hawkeye_backend.edge.wire import EdgeChallenge

    try:
        result = await _rpc(shutter_url, METHOD_CHALLENGE, {})
        nonce = result.get("nonce", "")
        if not nonce:
            raise RuntimeError("the shutter returned no nonce")
        await socket.send(
            EdgeChallenge(request_id=message.request_id, nonce=nonce).model_dump_json()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("edge: could not get a challenge from the shutter")
        await socket.send(
            EdgeChallenge(
                request_id=message.request_id, failed=True, detail=str(exc)
            ).model_dump_json()
        )


async def _forward_grant(socket, message, shutter_url: str) -> None:  # noqa: ANN001
    """Hand a grant to the shutter agent on this box, byte for byte.

    Verbatim is the whole requirement. `shutter` verifies the signature over
    exactly these bytes, so this process must not parse, reformat or
    re-serialize the grant on its way through. It is a pipe, not a participant,
    and `grant` is a JSON **string** inside the params for that reason.

    That is also why relaying a grant over an untrusted link costs nothing in
    trust: the signature is what `shutter` checks, and it checks it no matter
    how the bytes arrived.
    """
    from hawkeye_backend.edge.wire import EdgeAttestation

    try:
        result = await _rpc(shutter_url, METHOD_OPEN, {"grant": message.grant_json})
    except Exception as exc:  # noqa: BLE001
        # Reported as a refusal rather than dropped. A hub waiting on an
        # attestation that never comes eventually reports the position unknown,
        # which is correct but slow; saying so immediately is better.
        logger.exception("edge: could not reach the shutter")
        await socket.send(
            EdgeAttestation(
                request_id=message.request_id,
                refused=True,
                refusal_reason=f"could not reach the shutter agent: {exc}",
            ).model_dump_json()
        )
        return

    # A refusal arrives as a result carrying `refusal`, not as an error frame.
    if result.get("refusal"):
        logger.warning(
            "edge: the shutter refused the grant (%s): %s. The lens is still covered.",
            result["refusal"],
            result.get("detail", ""),
        )
        await socket.send(
            EdgeAttestation(
                request_id=message.request_id,
                refused=True,
                refusal_reason=f"{result['refusal']}: {result.get('detail', '')}".strip(": "),
                # The shield did not move, and the shutter still knows where it
                # is. That is a true fact and worth more than `unknown`.
                position=result.get("position", ""),
                commanded_angle=result.get("commanded_angle"),
            ).model_dump_json()
        )
        return

    await socket.send(
        EdgeAttestation(
            request_id=message.request_id,
            attestation_json=result.get("attestation", ""),
            refused=False,
        ).model_dump_json()
    )


async def _receive(socket, shutter_url: str) -> None:  # noqa: ANN001
    """Handle everything the hub sends down: challenge requests, then grants.

    Runs alongside the frame pump so a grant arriving downward is never stuck
    behind the next frame going up. An unparseable message is logged and
    skipped rather than killing the loop, because this task is the only way a
    shutter grant reaches the servo.
    """
    from hawkeye_backend.edge.wire import (
        EdgeChallengeRequest,
        EdgeError,
        EdgeGrant,
        decode_edge_message,
    )

    async for raw in socket:
        if isinstance(raw, bytes):
            logger.warning("edge: the hub sent binary, which it never should. Ignored.")
            continue
        try:
            message = decode_edge_message(raw)
        except Exception:
            logger.exception("edge: the hub sent something unparseable")
            continue

        if isinstance(message, EdgeError):
            logger.error("edge: the hub refused us (%s): %s", message.code, message.message)
            continue

        if isinstance(message, EdgeChallengeRequest):
            logger.info("edge: asking the shutter at %s for a nonce", shutter_url)
            await _answer_challenge(socket, message, shutter_url)
            continue

        if not isinstance(message, EdgeGrant):
            logger.info("edge: ignoring %s, which this side does not handle", message.kind)
            continue

        logger.info("edge: forwarding a grant to the shutter at %s", shutter_url)
        await _forward_grant(socket, message, shutter_url)


async def pump(
    url: str,
    token: str,
    edge_id: str,
    source: FrameSource,
    fps: float,
    shutter_url: str = DEFAULT_SHUTTER_URL,
) -> None:
    """Dial the hub and push frames until cancelled. Reconnects forever."""
    import websockets

    backoff = BACKOFF_START_S
    interval = 1.0 / fps if fps > 0 else 0.0

    while True:
        try:
            async with websockets.connect(f"{url}/v1/edge/link?token={token}") as socket:
                logger.info("edge: connected to %s", url)
                backoff = BACKOFF_START_S

                await socket.send(
                    EdgeHello(edge_id=edge_id, source=source.source).model_dump_json()
                )

                # The receive side runs alongside the push, so a grant arriving
                # downward is not stuck behind the next frame going up.
                receiver = asyncio.create_task(_receive(socket, shutter_url))
                try:
                    for frame in source.frames():
                        jpeg = encode_jpeg(
                            frame.image,
                            long_edge=EDGE_LONG_EDGE,
                            quality=EDGE_JPEG_QUALITY,
                        )
                        header = EdgeFrameHeader(
                            index=frame.index,
                            captured_at=frame.captured_at,
                            bytes=len(jpeg),
                        )
                        await socket.send(header.model_dump_json())
                        await socket.send(jpeg)
                        if interval:
                            await asyncio.sleep(interval)
                        else:
                            # Yield to the receive task even at unlimited rate,
                            # so a grant is never starved by the frame pump.
                            await asyncio.sleep(0)
                finally:
                    receiver.cancel()

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reconnect on anything
            logger.warning("edge: link dropped (%s); retrying in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push camera frames to the Hawk Eye hub.")
    parser.add_argument(
        "--hub", default=os.environ.get("HAWKEYE_HUB_URL", "ws://hawkeye-hub.local:8787")
    )
    parser.add_argument("--token", default=os.environ.get("HAWKEYE_EDGE_TOKEN", ""))
    parser.add_argument("--edge-id", default=os.environ.get("HAWKEYE_EDGE_ID", "pi-01"))
    parser.add_argument(
        "--shutter-url", default=os.environ.get("HAWKEYE_SHUTTER_URL", DEFAULT_SHUTTER_URL)
    )
    parser.add_argument("--source", default="camera", choices=("camera", "fixture"))
    parser.add_argument("--index", type=int, default=0, help="Camera index. 0 is the Brio.")
    parser.add_argument("--path", default=None, help="Video file, for --source fixture.")
    parser.add_argument("--fps", type=float, default=10.0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    if not args.token:
        # Refusing here rather than connecting and being refused is a better
        # error: it names the missing variable instead of reporting a 4401.
        logger.error("no token. Set HAWKEYE_EDGE_TOKEN or pass --token.")
        return 2

    source = open_source(args.source, args.index, args.path)
    try:
        asyncio.run(
            pump(args.hub, args.token, args.edge_id, source, args.fps, args.shutter_url)
        )
    except KeyboardInterrupt:
        logger.info("edge: stopped")
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
