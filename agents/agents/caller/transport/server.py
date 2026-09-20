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

`auth_token` is `None` when this deployment has no real Twilio credentials
configured (`hawkeye_backend.config.Settings.twilio_voice_configured` is
False). There is no safe non-secret to validate signatures against in that
case, so every route here fails closed rather than falling back to a known
constant - a fallback like `"test_auth_token"` is printed in this repo's own
test suite and would let anyone who read it forge signed-looking requests
against a publicly reachable but unconfigured instance.

The ConversationRelay WebSocket route (`/twilio/conversation-relay`) is a
second, separate authentication problem: Twilio does not send
`X-Twilio-Signature` on a WS handshake, so `_verified_form` cannot cover it.
It is instead gated by a one-time per-call token, minted when `/twilio/agent-leg`
builds its TwiML and embedded as a query param in the `wss://` URL Twilio is
told to connect to. A frame is never handed to the orchestrator until the
token on the connection matches the one minted for that call.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from .orchestrator import CallOrchestrator
from .signature import validate_twilio_signature
from .twiml import connect_relay_twiml, dial_conference_twiml


def build_transport_app(
    orchestrator: CallOrchestrator, *, auth_token: str | None, elevenlabs_voice_id: str, public_base_url: str
) -> FastAPI:
    app = FastAPI()
    configured = auth_token is not None

    async def _verified_form(request: Request, path: str) -> dict[str, str]:
        if not configured:
            # Fail closed: no real secret exists to validate against, so no
            # request - signed or not - is accepted. See the module docstring.
            raise HTTPException(status_code=503, detail="Twilio voice is not configured on this deployment")
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
        # Mint a fresh, per-call token and hand it to the orchestrator so the
        # WS route below can check it on accept. Random and single-purpose,
        # not a static shared secret - it authorizes exactly this call's
        # ConversationRelay leg, not any leg that will ever connect.
        token = secrets.token_urlsafe(32)
        orchestrator.relay_ws_token = token
        ws_url = public_base_url.replace("https://", "wss://") + "/twilio/conversation-relay" + f"?token={token}"
        xml = connect_relay_twiml(ws_url, elevenlabs_voice_id)
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/twilio/status")
    async def status(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/status")
        return PlainTextResponse("", media_type="application/xml")

    @app.websocket("/twilio/conversation-relay")
    async def conversation_relay(websocket: WebSocket) -> None:
        if not configured:
            # Fail closed here too, same as every HTTP route: an unconfigured
            # deployment has no per-call token to mint or check, so nothing
            # gets to speak to the orchestrator over this socket.
            await websocket.close(code=4403)
            return
        expected_token = orchestrator.relay_ws_token
        presented_token = websocket.query_params.get("token")
        if not expected_token or presented_token != expected_token:
            # Reject before accept() and before a single frame is read. This
            # is the only thing standing in for X-Twilio-Signature on this
            # route, since Twilio never sends that header on a WS handshake.
            await websocket.close(code=4401)
            return
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
