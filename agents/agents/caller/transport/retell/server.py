"""agents/agents/caller/transport/retell/server.py

The public HTTP/WS surface of the Retell transport. Two auth boundaries, both
fail-closed when unconfigured, mirroring the Twilio transport server:

- `/internal/start-call` is the trigger agents/master POSTs to after its own
  `/a2a/start-call` guards pass. Bearer-gated by HAWKEYE_INTERNAL_TRIGGER_TOKEN,
  shared out of band. An unauthenticated route that can dial a phone is a
  swatting vector as direct as an unsigned Twilio webhook.

- `/retell/llm-websocket/{secret}/{call_id}` is the Custom LLM WebSocket Retell
  connects to. Retell does not sign the WS handshake, so it is gated two ways:
  a static secret path segment (registered as part of the URL Retell connects
  to) and a check that the call_id is one this process actually initiated. An
  unconfigured deployment (no secret) refuses every connection rather than
  exposing an open LLM/dial endpoint on the public internet.
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from hawkeye_backend.models.incident import IncidentType

from .orchestrator import RetellCallOrchestrator


class _InternalStartCallBody(BaseModel):
    incident_id: str
    incident_type: str
    address: str


def build_retell_transport_app(
    orchestrator: RetellCallOrchestrator,
    *,
    websocket_secret: str | None,
    internal_trigger_token: str | None,
) -> FastAPI:
    app = FastAPI()
    internal_configured = internal_trigger_token is not None
    ws_configured = websocket_secret is not None

    def _verify_internal_token(request: Request) -> None:
        if not internal_configured:
            raise HTTPException(
                status_code=503, detail="the internal trigger route is not configured on this deployment"
            )
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {internal_trigger_token}"
        if not hmac.compare_digest(header, expected):
            raise HTTPException(status_code=403, detail="invalid internal trigger token")

    @app.post("/internal/start-call")
    async def internal_start_call(request: Request, body: _InternalStartCallBody) -> dict[str, str]:
        _verify_internal_token(request)
        incident_type = IncidentType(body.incident_type)
        call_id = await orchestrator.start_call(body.incident_id, incident_type, body.address)
        return {"call_id": call_id}

    @app.websocket("/retell/llm-websocket/{secret}/{call_id}")
    async def llm_websocket(websocket: WebSocket, secret: str, call_id: str) -> None:
        # Fail closed, wrong secret, or unknown call_id: refuse before accept so
        # nothing is ever handed to the orchestrator over an ungated socket.
        if (
            not ws_configured
            or not hmac.compare_digest(secret, websocket_secret)
            or orchestrator.call_id is None
            or not hmac.compare_digest(call_id, orchestrator.call_id)
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json(orchestrator.config_message())
        try:
            while True:
                raw = await websocket.receive_json()
                reply = await orchestrator.handle_ws_message(raw)
                if reply is not None:
                    await websocket.send_json(reply)
        except WebSocketDisconnect:
            return

    return app
