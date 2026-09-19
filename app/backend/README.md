# app/backend

The app-facing edge of the Hawk Eye agent mesh.

Read the root `CLAUDE.md` and `app/CLAUDE.md` first.

## What this is

The iOS app never talks to the five agents directly.
It talks to this service, and this service talks to `agents/master`.

That split is the architecture the root `CLAUDE.md` describes, made concrete.
Agent to agent is ANS, every hop, and it all happens behind `master`.
Human to agent is plain English over a REST and websocket API, and that is this service.
Nothing crosses the human boundary that was not verified first, and the verification results cross with it so the app can show them.

```
  iOS app  ──HTTP + WS──►  app/backend (this)  ──ANS──►  agents/master  ──ANS──►  the other eight
```

## Running it

Python 3.13. `uv` is used if present, a plain venv works otherwise.

```sh
cd app/backend

# with uv
uv venv --python 3.13
uv pip install -e .
.venv/bin/python -m hawkeye_backend.main

# without uv
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m hawkeye_backend.main
```

It listens on `0.0.0.0:8787` by default.
Interactive API docs are at `http://127.0.0.1:8787/docs`.

## Tests

```sh
cd app/backend
uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

37 tests, all of them security. `tests/test_battery.py` is the local reimplementation of the
`fraud.webmesh.ai` attack battery; `tests/test_card.py` covers agent-card hardening.

## `hawkeye_backend/verification/`

The defence `agents/master` runs on every claim. A standalone package with no FastAPI or hub
imports, so it moves into `agents/master` as an import change rather than a rewrite.

| Module | What it does |
|---|---|
| `canonical.py` | RFC 8785 JCS. The only canonicalizer in the codebase, which is what battery probe #13 asks for. |
| `envelope.py` | The signed claim envelope and its possession proof. The mandate analogue. |
| `verifier.py` | The ordered pipeline, ANS-6 §7.4. Where "a valid signature is not authorization" is enforced. |
| `trust.py` | Registered agents and their profiles. Unknown key means refused, never unknown-therefore-allow. |
| `replay.py` | Single-use proofs. Bounded, fail-closed, and spent **last**. |
| `card.py` | Agent-card signing, drift fingerprinting, dispatch-address commitment. |
| `errors.py` | Rejection taxonomy, named to line up with the battery's own verdicts. |

Why it exists and what each piece defends against: `docs/fraud-13.md` and `ans/CARD.md`.

Two things in here are easy to break by accident and both are load-bearing:

- **The replay id is recorded last**, after every other check. Recording it earlier lets anyone
  submitting garbage flood a bounded cache and fail-close authentication for every legitimate
  caller, which here is a denial of service against a 911 call. `test_replay_id_not_recorded_when_verification_fails`
  is the guard.
- **Canonicalization is shared.** Sign through the pydantic model, never by assembling a dict by
  hand. Doing the latter is how the first draft of the test signer broke, and it is the exact
  drift probe #13 looks for.

### The whole demo, with nothing else running

```sh
./scripts/demo.sh              # realistic timing, about 50 seconds
SPEED=0.35 ./scripts/demo.sh   # rehearsal speed
PORT=9000 ./scripts/demo.sh
```

That boots the hub in simulated mode, curls `/v1/hub` and `/v1/state`, connects to the websocket, runs the scripted detection, waits, taps Fire the way the app would, watches the call that tap releases, posts a mid-incident context note as the resident, and then fetches the sealed replay record.

The pause in the middle is the product.
The detection raises no incident and dials nothing; the tap is what starts the call.

**There is no hardware in that path and no agent process in that path.**
No Raspberry Pi, no router, no `agents/master`, no network beyond loopback.
One environment variable is the entire difference:

```sh
HAWKEYE_MODE=simulated   # default. SimulatedMasterClient drives the scripted detection, and the call a tap releases.
HAWKEYE_MODE=live        # LiveMasterClient talks to a real agents/master.
```

Live mode does not fall back to simulated when the mesh is down.
It returns 503 and says the mesh is unavailable.
A hub that quietly invents interior state when it cannot reach the mesh is exactly the failure this project exists to prevent, so that path does not exist.

### Configuration

Every setting is an environment variable prefixed `HAWKEYE_`.

| Variable | Default | What it does |
|---|---|---|
| `HAWKEYE_MODE` | `simulated` | `simulated` or `live`. The one switch. |
| `HAWKEYE_HOST` | `0.0.0.0` | Bind address. |
| `HAWKEYE_PORT` | `8787` | Bind port. |
| `HAWKEYE_HUB_NAME` | `Hawk Eye Hub` | Shown on the Connect screen. |
| `HAWKEYE_HUB_ANSNAME` | `hub.hawkeye.invalid` | The ANSName the hub is anchored to. Placeholder; see TODOs. |
| `HAWKEYE_MASTER_ANSNAME` | `master.hawkeye.invalid` | Placeholder; see TODOs. |
| `HAWKEYE_SITE_ID` | `site-demo-01` | One resident, hardcoded. |
| `HAWKEYE_SITE_ADDRESS` | `1872 Ridgeview Lane, Blacksburg VA 24060` | What `caller` reads to the dispatcher. |
| `HAWKEYE_MASTER_BASE_URL` | `http://127.0.0.1:8900` | Live mode only. Where `agents/master` is. |
| `HAWKEYE_MASTER_TIMEOUT_S` | `5.0` | Live mode only. |
| `HAWKEYE_SIM_SPEED` | `1.0` | Simulated mode only. Multiplies every scripted delay. |
| `HAWKEYE_SIM_AUTOSTART` | `false` | Simulated mode only. Run the **detection** on boot, so a demo rig comes up already showing the lost breathing signature. It cannot start a call. |
| `HAWKEYE_STORE_BACKEND` | `memory` | `memory` or `mongodb`. See the storage seam below. |
| `HAWKEYE_MONGODB_URI` | empty | MongoDB Atlas connection string, when that lands. |

## Notices

An unexpected presence that holds for `HAWKEYE_NOTICE_HOLD_S` seconds raises a notice: a banner in the app, and an SMS if Twilio is configured.
A notice is information the resident acts on.
It never creates an incident and never dials.

Twilio is optional and the service runs normally without it.
All four values are required together:

```sh
export HAWKEYE_TWILIO_ACCOUNT_SID=ACxxxxxxxx
export HAWKEYE_TWILIO_AUTH_TOKEN=xxxxxxxx
export HAWKEYE_TWILIO_FROM_NUMBER=+15550001111
export HAWKEYE_TWILIO_TO_NUMBER=+15550002222    # must be verified in the Twilio console
```

On a trial account the destination number must be verified in the console, and every message arrives prefixed "Sent from your Twilio trial account".

The auth token is held as a `SecretStr`, so it does not appear in a log line, a traceback, or a `repr` of the settings object.

## Real versus simulated

The honesty rule from the root `CLAUDE.md` is enforced in the schema, not in a comment.

Every reading carries a required `provenance` object.
`provenance.source` is a closed enum, and `provenance.source_class` and `provenance.simulated` are **computed from it** rather than supplied, so a producer cannot label a simulated number as measured even by accident.

| Piece | Status today | How the API says so |
|---|---|---|
| The API surface, its models, and its contract | Real | This is the deliverable. |
| The `Store` protocol and its in-memory implementation | Real | Works, has no database behind it. |
| The `MasterClient` protocol | Real | Two implementations, one switch. |
| `LiveMasterClient` HTTP surface | Written, never exercised | `agents/master` does not exist yet. Every assumption is a `TODO(master)` in `master/live.py`. |
| Interior state, presences, positions | **Simulated** | `provenance.source = "ruview-sim"`, `source_class = "simulated"`, `simulated = true`. |
| Carbon monoxide reading | **Simulated** | `provenance.source = "demo-trigger"`, exactly the literal string the root `CLAUDE.md` requires. No gas sensor was purchased. |
| A human tap being the only thing that dials | **Real** | `assert_human_released` in `master/base.py` gates every path that can end in a call. A `SYSTEM`-raised incident raises `AutonomousDialRefused` rather than dialing. |
| The 911 call, the operator's voice, the transcript | **Simulated** | `provenance.source = "agent-inference"` for our side, `"operator-audio"` for theirs. No phone call is placed. ElevenLabs is not wired in. |
| ANS verification results | **Simulated** | The decisions follow the real `recommendedProfile` table from `agents/CLAUDE.md`, but no certificate was actually resolved and no Trust Index was actually queried. See the TODOs. |
| Trust Index scores | **Simulated, and the unimplemented dimensions are named** | `solvency`, `behavior` and `safety` come back `null`, not `0`, with `unimplemented_dimensions` listing them. Upstream hardcodes them to 0; a 0 that means "not scored" and a 0 that means "scored zero" are different facts. |
| The SCITT transparency log receipt | **Not implemented** | `replay.scitt_receipt` is always `null`. The local hash chain (`root_hash`, `entry_hash`, `prev_hash`) is real and makes tampering detectable, but it is not a transparency log receipt and is not described as one. |
| Bonjour / mDNS advertisement | Not implemented here | The iOS side discovers the hub; this service does not advertise itself yet. |

What to say on stage, in one line:
the agents, their identities, their cards and their contracts are the real part;
the radio, the gas sensor and the phone line are stubbed behind interfaces that already exist, and swapping each one in is a driver change with nothing above it moving.

### The one-line switch when real capture lands

`hawkeye_backend/master/simulated.py` has a single constant:

```python
SIM_SENSOR_SOURCE = Source.RUVIEW_SIM
```

When `sensor/` produces a real capture at the house, flip it to `Source.REPLAY_CSI` and every label downstream changes from `simulated` to `measured-replay` at once.
It is deliberately one line so nobody has to remember a second place.

## API reference

Base path `/v1`. Everything is JSON. All timestamps are UTC, ISO 8601, with a `Z`.

Complete example payloads for every endpoint and every event kind are real files in [`schema/`](schema/).
They are generated from the live Pydantic models by `tools/gen_schema.py`, so they cannot drift from the code.
The iOS agent should match its `Codable` types against those files rather than against this README.

### `GET /v1/hub`

Hub identity and health. What the Connect screen hits after Bonjour discovery, to verify the hub before entering the main app.

`healthy` means "the app may proceed", not "every agent is up".
A tier 3 agent being unreachable does not block the app; a dead sensing pipeline does, and the app should say so rather than draw an empty house.

Full example: [`schema/hub.json`](schema/hub.json). Abridged:

```json
{
  "hub_name": "Hawk Eye Hub",
  "hub_ansname": "hub.hawkeye.invalid",
  "master_ansname": "master.hawkeye.invalid",
  "site_id": "site-demo-01",
  "site_address": "1872 Ridgeview Lane, Blacksburg VA 24060",
  "mode": "simulated",
  "version": "0.1.0",
  "healthy": true,
  "server_time": "2026-09-20T04:12:33Z",
  "uptime_s": 812.4,
  "sensor": {
    "source": "ruview-sim",
    "simulated": true,
    "live": true,
    "frame_rate_hz": 137.4,
    "min_useful_frame_rate_hz": 100.0,
    "baseline_healthy": true,
    "baseline_age_s": 612.0
  },
  "agents": [
    {
      "name": "agents/people",
      "ansname": "people.hawkeye.invalid",
      "tier": 1,
      "reachability": "reachable",
      "latency_ms": 18.4
    }
  ],
  "active_incident_id": "inc-0001",
  "stream_path": "/v1/stream"
}
```

`sensor.frame_rate_hz` against `min_useful_frame_rate_hz` is the field that catches the quiet failure named in `sensor/CLAUDE.md`: without a traffic generator you get beacons at roughly 10 Hz, which barely resolves breathing and never resolves a short motion transient, with every component reporting healthy.

`reachability` is one of `reachable`, `unreachable`, `degraded`, `simulated`.
It is not a verification result: verification is per-claim and lives on the stream, because an agent trusted ninety seconds ago may not be trusted now.

Returns 503 when the agent mesh is unreachable in live mode.

### `GET /v1/state`

Current interior state: the presences, and the floorplan they sit in.

Full example: [`schema/state.json`](schema/state.json). Abridged:

```json
{
  "site_id": "site-demo-01",
  "captured_at": "2026-09-20T04:12:33Z",
  "sensor_identity": "sensor.hawkeye.invalid",
  "calibration": { "baseline_age_s": 612.0, "healthy": true, "note": "Rolling percentile baseline, slow adaptation." },
  "presences": [
    {
      "presence_id": "p1",
      "state": "confirmed_still",
      "position": { "zone": "main_bedroom", "x": 1.85, "y": 4.35, "zone_confidence": 0.89 },
      "moving": false,
      "confidence": 0.89,
      "vitals": { "respiration": "breathing", "breathing_bpm": 9.0, "heart_bpm": 112.0, "person_confidence": 0.92 },
      "presence_class": "adult",
      "class_basis": "respiration_rate",
      "expected": true,
      "respiration_lost_s": 96.0,
      "provenance": {
        "source": "ruview-sim",
        "producer": "sensor/",
        "ansname": "sensor.hawkeye.invalid",
        "detail": "Synthetic CSI. No capture file is wired in; these numbers were not measured.",
        "source_class": "simulated",
        "simulated": true
      }
    }
  ],
  "environment": {
    "co_ppm": 186.0,
    "smoke_detected": false,
    "confidence": 0.88,
    "provenance": { "source": "demo-trigger", "producer": "agents/master", "source_class": "simulated", "simulated": true }
  },
  "floorplan": { "site_id": "site-demo-01", "name": "Chestnut", "units": "m", "width_m": 14.8, "depth_m": 6.8, "wall_height_m": 2.5, "rooms": [] },
  "active_incident_id": "inc-0001"
}
```

**The three states `app/CLAUDE.md` requires are carried explicitly in `presence.state`**, not left for the client to infer from a pile of booleans:

| `state` | Means | What the app does with it |
|---|---|---|
| `confirmed_moving` | Moving and breathing. A person, confirmed. | Normal presence. |
| `confirmed_still` | Still but breathing. A person who has not moved. | Prominent. The radio cannot separate unconsciousness from sleep and the label must not imply it can. |
| `unconfirmed` | A perturbation with no respiration signature. | Render as a perturbation, not a person. A curtain is not an intruder. |
| `unknown` | Not resolved yet. | Absence of respiration is not proof of absence of a person; a presence that has not been resolved sits here rather than being called `unconfirmed`. |

`position.zone` is the honest answer and is what the agents reason over.
`position.x` and `position.y` are a zone centroid so the 3D view has somewhere to draw. They are not a localization claim; do not promise coordinates.

`respiration_lost_s` is the field that decides whether a dispatcher should expect an answer from a room.
It is the seconds since a breathing signature was last resolvable on a presence that **previously had one**: the transition is the signal, and a presence that never resolved a signature carries none, because shallow breathing, breath-holding and range limits are indistinguishable from an empty room.
It is never a finding that breathing has stopped. Surface it, with that limit attached.
It replaced `still_down_s` on 2026-09-19, when fall detection was cut.

Returns 503 when the agent mesh is unreachable in live mode.

### `WS /v1/stream`

The live push channel. Every frame is one JSON `Envelope`, a tagged union discriminated on `payload.kind`.

```json
{
  "seq": 1208,
  "at": "2026-09-20T04:12:45Z",
  "incident_id": "inc-0001",
  "payload": { "kind": "verification", "result": { } }
}
```

`seq` is monotonic and server-wide. A gap means the client missed a frame.

On connect the client gets, in order:

1. a `hello` frame naming the hub, its ANSName, and the mode it is running in,
2. the last interior state tick, so the 3D view has something to draw immediately,
3. everything as it happens.

Event kinds, with a complete example file for each:

| `kind` | Payload key | Example | What it is |
|---|---|---|---|
| `hello` | inline | [`event-hello.json`](schema/event-hello.json) | First frame on every connection. |
| `state` | `state` | [`event-state.json`](schema/event-state.json) | An interior state tick. Roughly 2 Hz. |
| `incident` | `phase`, `incident` | [`event-incident.json`](schema/event-incident.json) | Raised, classified, updated, resolved, or refused. |
| `transcript` | `line` | [`event-transcript.json`](schema/event-transcript.json) | One line of the caller to 911 conversation, with a speaker field. |
| `instruction` | `instruction` | [`event-instruction.json`](schema/event-instruction.json) | One instruction from `agents/caller`. |
| `verification` | `result` | [`event-verification-asserted.json`](schema/event-verification-asserted.json), [`event-verification-discarded.json`](schema/event-verification-discarded.json) | An ANS verification result. |
| `context` | `note` | [`event-context.json`](schema/event-context.json) | The resident's note, echoed back to confirm delivery. |
| `error` | `code`, `message` | [`event-error.json`](schema/event-error.json) | Something went wrong. Never a silently dropped frame. |

A slow subscriber is dropped rather than allowed to back up the publisher.
During an incident a stale frame is worthless, and blocking the mesh on a phone that went to sleep is unacceptable.

#### The verification event

This is the part the project is judged on, so it is a first-class API concept rather than a log line.

```json
{
  "kind": "verification",
  "result": {
    "verification_id": "ver-005",
    "incident_id": "inc-0001",
    "checked_at": "2026-09-20T04:12:45Z",
    "claim": {
      "claim_id": "clm-005",
      "statement": "A third adult is unresponsive in the corridor outside the front door and is not breathing.",
      "field": "biometrics.respiration",
      "value": "no respiration, building corridor",
      "presence_id": null
    },
    "agent": {
      "name": "agents/people",
      "ansname": "people.hawkeye-secure.invalid",
      "certificate_version": "v1.4.2+sha256:4d77...0e91",
      "trust_index": {
        "integrity": 0.0,
        "identity": 0.0,
        "solvency": null,
        "behavior": null,
        "safety": null,
        "unimplemented_dimensions": ["solvency", "behavior", "safety"]
      },
      "recommended_profile": "UNTRUSTED"
    },
    "decision": "DISCARDED",
    "reason": "DISCARDED. The claim would have sent an armed response into a room where no sensor sees anybody. It was not relayed to the operator and it was not used in classification.",
    "checks": [
      { "name": "ans.resolve", "passed": false, "detail": "people.hawkeye-secure.invalid is not the ANSName registered for agents/people." },
      { "name": "cert.version_binding", "passed": false, "detail": "Code fingerprint differs from the version-bound certificate issued at registration." },
      { "name": "trust_index.profile", "passed": false, "detail": "Trust Index recommendedProfile = UNTRUSTED." },
      { "name": "corroboration.sensor", "passed": false, "detail": "The corridor outside the front door is outside the sensed volume, so no agent in this mesh can see it." }
    ],
    "will_be_spoken": false
  }
}
```

The decision follows the `recommendedProfile` table from `agents/CLAUDE.md`:

| `recommended_profile` | `decision` | What it means |
|---|---|---|
| `FIDUCIARY` | `ASSERTED` | Relayed as an assertion the system stands behind. |
| `TRANSACTIONAL` | `ATTRIBUTED` | Relayed as a reported observation, attributed to the agent that made it. |
| `READ_ONLY` | `CORROBORATION_ONLY` | Corroboration only, never the sole basis for a call. |
| `UNTRUSTED` | `DISCARDED` | Discarded. Logged. Not relayed. |

**A failing check outranks a good profile.** Any failed check produces `DISCARDED` regardless of the profile, and that ordering is the point.
`checks` is what makes a discard legible on screen: "untrusted" is a verdict, "certificate fingerprint differs from the one registered" is a reason.

`will_be_spoken` tells the app whether `agents/caller` is permitted to repeat this claim to the operator.

### `POST /v1/incident`

The resident raises an incident from the app. One tap.

**This is the only path to a call.**
Hawk Eye never calls 911 on its own; settled 2026-09-19.
The agents still sense continuously, and what they find surfaces on the stream as interior state the app renders as an alert: the presence's respiration goes to no signature, `respiration_lost_s` climbs and does not reset, the CO reading rises.
An alert is information a person acts on. It is not a call.

The request carries `raised_by: user` and nothing else is accepted downstream: `assert_human_released` in `master/base.py` refuses a `SYSTEM`-raised incident on every path that can end in a phone call.
`RaisedBy.SYSTEM` stays in the enum for wire compatibility and for records raised before that decision.

What the detection buys is an informed tap rather than an autonomous one.
By the time the resident presses Fire, the hub already knows who is in the house, in which room, whether they are breathing, and how long since a signature that was resolvable there stopped being resolvable.

Request ([`schema/request-raise-incident.json`](schema/request-raise-incident.json)):

```json
{ "incident_type": "burglary", "note": "Someone is in the kitchen." }
```

`incident_type` is `burglary` or `fire`. `note` is optional and goes down the same channel as the "what is happening" box.

Response, `202 Accepted` ([`schema/response-raise-incident.json`](schema/response-raise-incident.json)):

```json
{ "incident_id": "inc-0002", "status": "raised", "accepted_at": "2026-09-20T04:12:33Z" }
```

202 rather than 201 on purpose: the hub has accepted it and forwarded it to `master`, and what happens next arrives on the stream.
The resident should not be staring at a spinner while an agent decides things.

```sh
curl -X POST localhost:8787/v1/incident \
  -H 'content-type: application/json' \
  -d '{"incident_type":"fire"}'
```

### `POST /v1/incident/{id}/context`

The "what is happening" box. Free text from the resident, forwarded to `master` and on to `caller`.

Request ([`schema/request-context.json`](schema/request-context.json)):

```json
{ "text": "My mother has COPD and there is a space heater in that bedroom." }
```

Response, `202 Accepted` ([`schema/response-context.json`](schema/response-context.json)):

```json
{
  "note_id": "note-001",
  "incident_id": "inc-0001",
  "text": "My mother has COPD and there is a space heater in that bedroom.",
  "at": "2026-09-20T04:13:04Z",
  "provenance": { "source": "user-input", "producer": "app/ios", "source_class": "human", "simulated": false },
  "delivered_to_caller": true
}
```

The note carries `user-input` provenance, and `source_class` comes out `human`.
The agents know what the radio can see. They do not know the intruder had a knife or the child is asthmatic.
What the resident types is a human statement, and `caller` attributes it as one rather than asserting it as something a sensor observed.

404 if the incident id is unknown.

### `GET /v1/incident/{id}/replay`

The sealed post-incident record, from `agents/replay`.

Full example: [`schema/replay.json`](schema/replay.json). Abridged:

```json
{
  "incident_id": "inc-0001",
  "sealed": true,
  "sealed_at": "2026-09-20T04:15:33Z",
  "caller_ansname": "caller.hawkeye.invalid",
  "site_address": "1872 Ridgeview Lane, Blacksburg VA 24060",
  "entries": [
    {
      "seq": 1,
      "at": "2026-09-20T04:12:33Z",
      "kind": "incident",
      "summary": "fire raised by user",
      "detail": { },
      "entry_hash": "9a1e26430b4002eb...",
      "prev_hash": null
    }
  ],
  "verifications": [],
  "root_hash": "eaf7ca3e574f961b...",
  "scitt_receipt": null,
  "hash_algorithm": "sha256"
}
```

Every verification is in here, accepted and **discarded alike**.
The discarded ones are the point: the operator could not check us live, an investigator can check this afterward, and swatting investigations are entirely post-hoc.

`entry_hash` and `prev_hash` form a local SHA-256 hash chain over the canonical JSON of each entry, which makes reordering or editing detectable.
**That is not a SCITT receipt and is not described as one.**
`scitt_receipt` is always `null` until the submit path exists. See the TODOs.

In live mode this proxies `agents/replay`.
In simulated mode the hub assembles the record from its own buffer, in the same shape, so the demo has something real to show.

### `POST /v1/demo/run`

Drives the scripted detection and then stops. **Simulated mode only; 404s in live mode, deliberately.**

The default is detection only, because that is what the system does on its own.
The lost signature appears in `state`, `respiration_lost_s` climbs, CO rises, and no `incident` or `transcript` event is emitted at all.
The system notices and waits.

```sh
curl -X POST localhost:8787/v1/demo/run
# {"started":true,"detail":"scripted detection started; no incident raised, waiting on a human tap","raised_incident_id":null}
```

`?simulate_human_tap=true` additionally raises a Fire incident exactly as `POST /v1/incident` would, with `raised_by: user`, so one curl exercises detection and call end to end.
The parameter is named for what it is standing in for, which is a person.
Without it this endpoint cannot start a call, and with it the thing being faked is the tap, not the system's authority to dial.

```sh
curl -X POST 'localhost:8787/v1/demo/run?simulate_human_tap=true'
```

There must be no way to trigger a scripted incident against a live mesh.
A demo button that fabricates an emergency on a system wired to a phone line is not a thing this project gets to have.

### `GET /healthz`

`{"status":"ok","mode":"simulated","version":"0.1.0"}`. For a load balancer.

## Layout

```
app/backend/
  pyproject.toml            uv / pip project, Python 3.13
  requirements.txt          plain-pip fallback
  README.md                 this file
  scripts/demo.sh           boots simulated mode, runs the detection, taps Fire, watches the call
  schema/                   generated example payloads, one per endpoint and event kind
  tools/
    gen_schema.py           regenerates schema/ from the live models
    ws_probe.py             terminal websocket client, prints the event stream
    summarize.py            pretty-printer used by demo.sh
  hawkeye_backend/
    main.py                 app factory, entry point
    config.py               HAWKEYE_* settings
    api.py                  the six endpoints plus the websocket
    runtime.py              HubRuntime: sequences, persists, and fans out every event
    bus.py                  in-process pub/sub to the websockets
    store.py                Store protocol, InMemoryStore, MongoStore seam
    models/
      common.py             Provenance and the honesty rule, enforced in the schema
      state.py              interior state, presences, floorplan
      incident.py           incidents, transcript, instructions, replay
      verification.py       claims, trust profiles, decisions
      hub.py                hub identity and health
      events.py             the tagged-union stream envelope
    master/
      base.py               MasterClient protocol, EventSink protocol
      simulated.py          the scripted detection, and the scripted call a human tap releases
      live.py               HTTP client against agents/master
      scenario.py           floorplan, agent roster, ANSName map
```

### Regenerating `schema/`

```sh
.venv/bin/python tools/gen_schema.py
```

Do this after any model change. The files in `schema/` are the iOS side's contract.

### Watching the stream from a terminal

```sh
.venv/bin/python tools/ws_probe.py --url ws://127.0.0.1:8787/v1/stream --seconds 60
.venv/bin/python tools/ws_probe.py --show-state   # include the 2 Hz state ticks
```

## The storage seam

`Store` is a protocol in `store.py` with one real implementation, `InMemoryStore`.
No database is required for the hackathon path, and nothing persists across a restart, which is fine.

`MongoStore` is the seam for the MongoDB Atlas sponsor track.
It raises `NotImplementedError` rather than silently degrading to memory, because a service that claims to be persisting and is not is exactly the kind of quiet lie this project is built against.

Implementing it is one class: every `Store` method maps onto one collection keyed by `incident_id`, with `events` as a capped collection sized like the in-memory buffer.
`build_store()` in `store.py` is the single swap point, and nothing above that file changes.

## Open questions left in the code

Every one of these is a `TODO(ans)` or `TODO(master)` comment at the exact place the answer is needed.
None of them is a fabricated API detail; where the real surface is unknown, the code says so and asks the specific question.

1. **`config.py`, hub ANSName.** Is the hub itself an ANS-registered agent, or does it inherit `master`'s identity and merely quote it? The app-to-hub hop is a human-facing hop, so the working assumption is that it quotes. Confirm against `ans-registry` before printing it on stage.
2. **`master/scenario.py`, ANSName format.** All five names are placeholders on `.invalid` (reserved by RFC 2606 precisely so it can never resolve, which keeps them from being mistaken for real registrations). `agents/core/identity.py` is now the source of truth for the roster and this copy should be deleted once the hub imports from it. Replace the domain once the GoDaddy one is registered, and settle the convention: `people.hawkeye.example`, or `hawkeye.example/agents/people`? Check `agent.webmesh.ai/.well-known/agents-index.json`.
3. **`models/verification.py`, Trust Index response shape.** Are dimension scores 0-1 or 0-100? What is the JSON key for `recommendedProfile`? Is there a composite score? Does the response distinguish "unimplemented" from "scored 0"? The 0-1 range and the nullable dimensions here are this service's choice, not a verified fact, and must be reconciled against `agentnameservice/agent-trust-discovery`.
4. **`models/incident.py`, SCITT receipt.** What is the submit endpoint and receipt structure for an ANS SCITT transparency log entry (ANS-4), and is a receipt a COSE object or a JSON document? Until that is answered `scitt_receipt` stays `null`. Do not fabricate one; an unverifiable receipt is worse than none.
5. **`master/live.py`, master's HTTP surface.** Three open questions, all marked: (a) does `master` expose one merged state document or does the hub fan out to the sensing agents itself, (b) is the push channel a websocket, SSE, or an outbound webhook, (c) does `master` accept an incident from the hub directly, or must the hub present an ANS identity over mTLS (ANS-2)? Nothing here implements mTLS yet.

## Not in scope here

- **Bonjour / mDNS advertisement.** The iOS side discovers the hub; this service does not advertise itself yet.
- **Push notifications.** `app/CLAUDE.md` requires notifications when the app is backgrounded. That is APNs and belongs on the iOS side plus a push-sending path that does not exist here.
- **Authentication.** One resident, hardcoded, on a LAN. There is no auth on this API. That is a deliberate scope cut for a 36-hour build and it should be said out loud rather than discovered.
- **The ElevenLabs voice path.** The transcript is the app's view of a call `agents/caller` owns. This service relays lines; it does not synthesize or place anything.
