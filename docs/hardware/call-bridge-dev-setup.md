# Call bridge dev setup: ngrok

`agents/agents/caller`'s Twilio transport server (`transport/server.py`) has to be reachable from
the public internet before Twilio will call into it — Twilio has no notion of `localhost`. In dev,
ngrok is how that reachability exists without a deployed host. This is a per-session step: a free
ngrok tunnel gets a new random subdomain every time it restarts, so everything below runs again
after any restart unless a paid static domain is in use.

## 1. Install and run ngrok

```sh
brew install ngrok
ngrok config add-authtoken <your token>   # from the ngrok dashboard, once
```

The transport server listens on its own port, separate from `caller`'s A2A server (Task 9 wired
both to run concurrently — see `agents/agents/__main__.py --transport-port`, default `8107`).
Point one tunnel at it:

```sh
ngrok http 8107
```

This single tunnel carries everything the transport server exposes: the three POST webhooks
(`/twilio/voice`, `/twilio/agent-leg`, `/twilio/status`) and the WebSocket ConversationRelay
endpoint (`/twilio/conversation-relay`). ngrok proxies WSS over the same HTTPS tunnel as the POST
routes, so a second tunnel is not needed — one multiplexed tunnel is enough on ngrok's free plan.

ngrok prints a `https://<random>.ngrok-free.app` URL. Copy it.

## 2. Set `HAWKEYE_PUBLIC_BASE_URL`

In `app/backend/.env` (or wherever `caller`'s process reads its env from — same `Settings` class,
see `app/backend/hawkeye_backend/config.py`):

```
HAWKEYE_PUBLIC_BASE_URL=https://<random>.ngrok-free.app
```

This is the value every webhook URL below is built from. `twilio_voice_configured` (in
`config.py`) will not read as `True` without it, alongside the rest of the Twilio Voice /
ElevenLabs fields from `.env.example`.

## 3. Register the webhook URLs in the Twilio console

Two places need the new ngrok URL:

- **The TwiML Application** (`HAWKEYE_TWILIO_CONFERENCE_APP_SID`, `APxxxx…`) — Voice Configuration
  → Request URL:
  ```
  https://<random>.ngrok-free.app/twilio/agent-leg
  ```
  This is the URL `add_conference_participant` dials into (Task 5/7) to bring the ConversationRelay
  leg into the conference.

- **The Twilio phone number** (`HAWKEYE_TWILIO_VOICE_NUMBER`) — Phone Numbers → Manage → your
  number → Voice Configuration → "A call comes in":
  ```
  https://<random>.ngrok-free.app/twilio/voice
  ```
  Only relevant if this number is ever dialed inbound; the outbound mock-911 call
  (`create_conference_call`, Task 5) does not need this, but it's the same TwiML app style either
  way and cheap to set once.

Status callbacks (`status_callback_url`, passed per-call rather than configured statically in the
console) resolve to:

```
https://<random>.ngrok-free.app/twilio/status
```

## 4. Restart discipline

Every ngrok restart rotates the subdomain unless a reserved/static domain is purchased on ngrok. A
rotated URL invalidates all three registrations above silently — Twilio will fail closed (signature
validation in `transport/signature.py` still passes since it doesn't check the URL, but the request
never arrives) rather than erroring loudly. After any ngrok restart:

1. Update `HAWKEYE_PUBLIC_BASE_URL` in `.env`.
2. Re-paste the new URL into both console locations in step 3.
3. Restart `caller`'s process so it picks up the new `public_base_url` (it's read once at
   `Settings` construction, not polled).

A static ngrok domain (paid tier) removes steps 2–3 permanently and is worth it the moment this
setup is done more than once or twice before the event.
