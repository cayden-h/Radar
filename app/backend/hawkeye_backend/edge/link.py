"""The websocket the Pi dials, and the state machine behind it.

Reading order for the refusals, because they are the substance of this file:

- **No token, wrong token, or no token configured** closes the connection before
  a single byte is read. Closed by default, never open by default.
- **A frame before `hello`** is refused, because until the edge says what it is
  looking through, the frame cannot be labelled, and an unlabelled frame could
  be a video file presenting as a camera.
- **A binary message with no header before it** is refused rather than stamped
  with arrival time. Arrival time is not capture time, and quietly substituting
  one for the other is how a frame starts lying about when it was taken.
- **A payload whose length contradicts its header** is refused, because the two
  disagreeing means the stream has desynchronized and every subsequent pairing
  is guesswork.

Every refusal is reported back down the link as an `EdgeError` before the
connection closes, so the Pi's log says what happened rather than just
"disconnected".
"""

from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeError,
    EdgeFrameHeader,
    EdgeHello,
    decode_edge_message,
)

logger = logging.getLogger(__name__)

#: Sent instead of an HTTP status, because a websocket handshake has no body to
#: put a reason in. Both are in the private-use range.
CLOSE_UNAUTHORIZED = 4401
CLOSE_PROTOCOL = 4400


async def run_edge_link(websocket: WebSocket, runtime, token: str | None) -> None:  # noqa: ANN001
    """Serve one edge connection for its lifetime.

    `runtime` is a `HubRuntime`, untyped here only to keep this module out of an
    import cycle: the runtime owns the camera this writes into.
    """
    configured = runtime.settings.edge_token.get_secret_value()
    if not configured:
        logger.warning(
            "edge link: refused a connection because HAWKEYE_EDGE_TOKEN is not set. "
            "An unauthenticated camera feed is worse than no camera feed."
        )
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="edge token not configured")
        return
    if token != configured:
        logger.warning("edge link: refused a connection presenting a bad token")
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="bad token")
        return

    await websocket.accept()
    runtime.edge = websocket
    hello: EdgeHello | None = None
    pending: EdgeFrameHeader | None = None
    reason = "closed"

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                reason = "edge disconnected"
                break

            payload = message.get("bytes")
            if payload is not None:
                if hello is None:
                    await _refuse(websocket, "no_hello", "a frame arrived before hello")
                    reason = "frame before hello"
                    break
                if pending is None:
                    await _refuse(
                        websocket,
                        "unpaired_payload",
                        "a binary message arrived with no frame header before it",
                    )
                    reason = "unpaired payload"
                    break
                if len(payload) != pending.bytes:
                    await _refuse(
                        websocket,
                        "length_mismatch",
                        f"header promised {pending.bytes} bytes, payload carried {len(payload)}",
                    )
                    reason = "length mismatch"
                    break

                runtime.camera.accept(
                    payload, index=pending.index, captured_at=pending.captured_at
                )
                pending = None
                continue

            raw = message.get("text")
            if raw is None:
                continue

            try:
                decoded = decode_edge_message(raw)
            except ValidationError as exc:
                await _refuse(
                    websocket, "malformed", f"unparseable message: {exc.error_count()} errors"
                )
                reason = "malformed message"
                break

            if isinstance(decoded, EdgeHello):
                hello = decoded
                runtime.camera.link_opened(edge_id=decoded.edge_id, source=decoded.source)
            elif isinstance(decoded, EdgeFrameHeader):
                if hello is None:
                    await _refuse(websocket, "no_hello", "a frame arrived before hello")
                    reason = "frame before hello"
                    break
                pending = decoded
            elif isinstance(decoded, EdgeAttestation):
                runtime.resolve_attestation(decoded)
            elif isinstance(decoded, EdgeError):
                logger.warning(
                    "edge link: the edge reported %s: %s", decoded.code, decoded.message
                )
            else:
                # EdgeGrant travels the other way. Receiving one means the far
                # end is confused about which side it is, and that is worth
                # saying rather than ignoring.
                await _refuse(
                    websocket, "wrong_direction", "that message only travels downward"
                )
                reason = "wrong direction"
                break

    except WebSocketDisconnect:
        reason = "edge disconnected"
    except Exception:
        logger.exception("edge link: unexpected failure")
        reason = "internal error"
    finally:
        runtime.edge = None
        runtime.camera.link_closed(reason)


async def _refuse(websocket: WebSocket, code: str, message: str) -> None:
    """Say why before hanging up, so the Pi's log is not just 'disconnected'."""
    logger.warning("edge link: refusing (%s) %s", code, message)
    try:
        await websocket.send_text(EdgeError(code=code, message=message).model_dump_json())
        await websocket.close(code=CLOSE_PROTOCOL, reason=code)
    except Exception:
        logger.debug("edge link: could not deliver the refusal, the socket was already gone")
