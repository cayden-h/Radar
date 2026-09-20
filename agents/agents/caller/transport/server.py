"""agents/agents/caller/transport/server.py

The one part of this feature that is plain HTTP, not ANS - Twilio is a
transport carrying the same human-facing boundary as the 911 operator's
phone line, and that boundary belongs to caller per the root CLAUDE.md.

Every route here that Twilio calls over HTTP validates X-Twilio-Signature
before anything else runs. That is not a nicety: once this server is public,
anyone can POST to these URLs, and the signature is the only thing that
distinguishes Twilio from an attacker. `HAWKEYE_MOCK_911_NUMBER` is bound at
`CallOrchestrator` construction time from server-side settings and is never
read out of a request here - see the root CLAUDE.md's dispatch-address
section for why a destination number must never travel as attacker-reachable
input.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from .orchestrator import CallOrchestrator
from .signature import validate_twilio_signature
from .twiml import connect_relay_twiml, dial_conference_twiml


def build_transport_app(
    orchestrator: CallOrchestrator, *, auth_token: str, elevenlabs_voice_id: str, public_base_url: str
) -> FastAPI:
    app = FastAPI()

    async def _verified_form(request: Request, path: str) -> dict[str, str]:
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        signature = request.headers.get("X-Twilio-Signature", "")
        # The public ngrok/production URL is what Twilio actually signed
        # against, not whatever internal host this process thinks it is
        # bound to (e.g. TestClient's http://testserver) - see Step 3's note
        # in the plan for why `str(request.url)` would be wrong here.
        url = f"{public_base_url}{path}"
        if not validate_twilio_signature(auth_token, url, params, signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        return params

    @app.post("/twilio/voice")
    async def voice(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/voice")
        xml = dial_conference_twiml(orchestrator.conference_name or "unassigned-conference")
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/twilio/agent-leg")
    async def agent_leg(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/agent-leg")
        ws_url = public_base_url.replace("https://", "wss://") + "/twilio/conversation-relay"
        xml = connect_relay_twiml(ws_url, elevenlabs_voice_id)
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/twilio/status")
    async def status(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/status")
        return PlainTextResponse("", media_type="application/xml")

    @app.websocket("/twilio/conversation-relay")
    async def conversation_relay(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_json()
                reply = await orchestrator.handle_relay_message(raw)
                if reply is not None:
                    await websocket.send_json(reply)
        except WebSocketDisconnect:
            return

    return app
