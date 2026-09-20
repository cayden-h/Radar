# app/backend

**Pivot note, 2026-09-19.** The verification package, the replay recorder and the household roster are all unchanged and all still correct.
What is stale below: the two-scenario demo runner (Fire is cut), the CO and respiration fields in the state payload, and the three-state person classification. The state payload gains a shield state and a narration line instead.
`docs/PIVOT.md` is the record and `TASKS.md` T01 is the deletion.

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
  iOS app  ──HTTP + WS──►  app/backend (this)  ──ANS──►  agents/master  ──ANS──►  the other four
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

184 tests.

The original 37 are security: `tests/test_battery.py` is the local reimplementation of the `fraud.webmesh.ai` attack battery, and `tests/test_card.py` covers agent-card hardening.

The rest cover the sealed replay record, the two-type incident roster, and the unexpected-presence notice and household roster added 2026-09-19.
`test_notice_detector.py` is the notice trigger rule and is the one to read first, because the rule is what decides whether the feature can be trusted.
`test_notice_sinks.py` covers delivery and its failure isolation, `test_notice_models.py` the wire shape, `test_notice_runtime.py` the hook at `HubRuntime.emit`, `test_notice_config.py` the Twilio settings, and `test_notice_wiring.py` the seam in `build_runtime` where those settings become a live sink.
The `test_household_*.py` files cover the roster, the device accounting rule, the hashed device identity, and the approval path.

`test_notice_wiring.py` is worth its own sentence.
Everything below it is unit-tested in isolation, so a mistake in the wiring itself would pass every other test and surface only in production as "the banner appears and no text ever arrives" - which is also the signature of a half-configured Twilio account, and therefore indistinguishable from it.

## Household

Who the house is not surprised by.
`hawkeye_backend/household/` is standalone, with no FastAPI and no hub imports, the way `verification/` is, so it moves into `agents/intruder` as an import change.

| Route | What it does |
|---|---|
| `GET /v1/household` | The roster. |
| `GET /v1/household/unclaimed-devices` | Devices seen associated that no member claims. |
| `POST /v1/household/remember` | Name a person, optionally bind a device. 404 if the device was never observed, 409 if it already belongs to someone. |
| `DELETE /v1/household/members/{id}` | Forget a member; their devices become unclaimed. |
| `POST /v1/presences/{id}/approve` | Vouch for a presence. Session-scoped, never persisted. |

Device identifiers are stored as HMAC-SHA256 under the site salt, never in the clear.
A roster is a list of which humans were in a building and what they carry, which is exactly the file that should not be useful to whoever steals it.
`identity.py` says plainly what that does and does not buy, since the salt today is the site id and is not a secret.

`household/accounting.py` holds the surplus rule and is the only copy of it.
`agents/intruder` imports this when it exists rather than reimplementing it, because two versions of the rule that decides whether someone is an intruder will drift.

**`known_devices_present` counts members, not devices**, and that distinction is load-bearing.
The number is subtracted from a count of people, so it has to be a count of people: a resident carrying a phone and a watch is one human, and counting two would let them account for two presences, which is how an intruder reads as accounted for.

One device has exactly one owner.
`remember` refuses a device another member already claims, for the same reason.

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
| `HAWKEYE_STORE_BACKEND` | `memory` | The hub's whole working state. `mongodb` is unimplemented and should stay that way. See the storage seam below. |
| `HAWKEYE_REPLAY_ARCHIVE` | `off` | `off` or `mongodb`. Where a **sealed** replay record is persisted. See the replay archive below. |
| `HAWKEYE_MONGODB_URI` | empty | Atlas connection string, used by the replay archive. Needs `motor`: `pip install -e ".[archive]"`. |
| `HAWKEYE_MONGODB_DATABASE` | `hawkeye` | Database holding the `replays` collection. |
| `HAWKEYE_NOTICE_HOLD_S` | `5` | Seconds an unexpected presence must hold before it becomes a notice. |
| `HAWKEYE_NOTICE_FORGET_AFTER_S` | `900` | Seconds of absence after which a fired notice mark lapses, so a real re-entry notifies again. |
| `HAWKEYE_TWILIO_ACCOUNT_SID` | empty | Twilio console. All four Twilio values are required together or none are used. |
| `HAWKEYE_TWILIO_AUTH_TOKEN` | empty | Twilio console. Held as a `SecretStr`, so it cannot reach a log or a repr. |
| `HAWKEYE_TWILIO_FROM_NUMBER` | empty | The Twilio number itself, E.164. |
| `HAWKEYE_TWILIO_TO_NUMBER` | empty | The resident's phone, E.164. On a trial account it must be verified in the console first. |
| `HAWKEYE_TWILIO_MIN_INTERVAL_S` | `60` | Floor between sends, so a rehearsal loop cannot burn trial credit. |
| `HAWKEYE_TWILIO_MAX_PER_INSTANCE` | `5` | Hard cap for the life of the sink. |
| `HAWKEYE_COURIER` | `off` | `off` or `resend`. Who mails a **sealed** record to the responding department. See the courier below. |
| `HAWKEYE_RESEND_API_KEY` | empty | Resend dashboard. Held as a `SecretStr`, so it cannot reach a log or a repr. |
| `HAWKEYE_COURIER_FROM` | `Hawk Eye <hawkeye@cayden.tech>` | The From address. **Its domain must be verified in Resend**, or sends are accepted and delivered nowhere. |
| `HAWKEYE_COURIER_TO` | empty | Fallback destination for the automatic send on seal, recorded as `configured`. Empty means that send is skipped. |
| `HAWKEYE_MOTION_CONSOLE_URL` | `http://localhost:8766/index.html` | Where `/motion` redirects. Empty drops the route. |
| `HAWKEYE_SITE_TIMEZONE` | `America/New_York` | Renders the local time in an SMS. |

## The replay console

A web page at **`/replay`**, served by this service from `app/web/replay/`.
Open `http://127.0.0.1:8787/replay/` once the hub is up.

It is the surface a detective reads at a desk, and it makes the opposite tradeoffs to the iOS app, which is the surface a resident holds during an emergency.
Desktop-dense, keyboard-free, and built to be exported rather than glanced at.

One self-contained HTML file plus a stylesheet and a script.
No build step, no bundler, and no CDN: venue wifi is not a dependency this demo can afford.

Two screens.
The index lists every recorded incident.
Opening one shows the floor plan with a frame scrubber, the record itself filterable by entry kind, the radio telemetry time-aligned underneath, and a chain panel.

Four things about it are deliberate.

**It replays recorded frames rather than mirroring live state.**
During an active incident the map trails the phone by up to a second, because the page polls `?since_seq=N` once a second rather than joining the websocket.
This is the record, not a second live dashboard, and one channel is one thing to debug.

**The chain is verified in the browser.**
A server that will lie about a record will also lie about having checked it, so the check that matters is the one the reader can run themselves.
The page recomputes every hash with WebCrypto over the bytes the server served.

That last point has a trap in it worth knowing, because it bit during the build.
Parsing the response and re-serializing it does not work: `JSON.stringify` writes the float `1.0` as `1` where Python writes `1.0`, and leaves non-ASCII unescaped where Python writes `\uXXXX`.
Either difference changes the hash of an entry nobody touched, and the console would then accuse an intact record of having been altered.
So the console canonicalizes from the raw text, keeping every number literal exactly as it arrived.
`tests/test_replay_console_js.py` runs that JavaScript under node and asserts it agrees with `replay/chain.py` byte for byte.
It is the only thing holding three implementations of one hash together, so do not delete it because it needs node.

**The RF strip is derived telemetry, and `raw_csi` is null.**
There is no raw Channel State Information anywhere in this service, so there is none to plot.
The strip shows capture rate against the minimum useful rate, and respiration per presence on its own axis, both labelled for what they are.
The band below the minimum useful capture rate is shaded, which puts the quiet failure named in `sensor/CLAUDE.md` on the record instead of hiding it.

**Discards are given equal weight to acceptances.**
The index counts them on the card, and the log tints them rather than greying them out.
What the system refused to repeat to a dispatcher is the interesting number, not the total.

`HAWKEYE_REPLAY_SITE_ENABLED=false` turns the page off without touching code, because serving a human surface is a deployment decision.

## The courier: the police email

The last step of an incident, and the only one aimed at somebody who was never on the call.
When a record seals, the bundle `replay/export.py` builds - the record, the readable chain, the standalone verifier, the README - goes to the responding department as one zip attachment, through Resend.

`hawkeye_backend/replay/courier.py`. `Courier` is a protocol with two implementations, exactly like `ReplayArchive`: `NullCourier` sends nothing and says so, `ResendCourier` sends.

**Off by default, and the default is louder here than it is for the archive.**
A missing archive costs durability. An accidental send puts an incident record in a stranger's inbox and cannot be recalled.
So every incomplete configuration - no key, no From address, `HAWKEYE_COURIER` unset - resolves to `NullCourier` at startup with a log line saying so, rather than to a courier that fails later.

### The address is reported, never trusted

`docs/fraud-13.md` makes the general argument: an agent that can change where a response is sent is a swatting tool no matter how well the claims upstream verify, which is why the dispatch address is bound at registration and sealed.

The police email is the pivot's new instance of that problem and it is handled differently on purpose, because it **cannot** be bound at registration - which department responds is not known until somebody answers the phone.
So it travels with its provenance attached and is recorded as what it is:

- **`operator_supplied`** - a 911 operator said it on the call and `caller` read it back. Supplied as `to` on the endpoint below.
- **`configured`** - `HAWKEYE_COURIER_TO`, which is what a rehearsal and the automatic send use.

Nothing downstream reads either as authorization for anything. The email body states which one it was, so the person reading it can notice if they never gave that address.

### A failed send is an event, not a silence

`Courier.send` returns a `CourierReceipt` on every path including the failures and raises only on a programming error.
A chain that says nothing about delivery is indistinguishable from one saying the email arrived, and the second is a lie a detective would act on.

Three outcomes, and `skipped` is deliberately not a failure: a hub with no courier configured is the ordinary case, and conflating the two teaches a reader to ignore failures.

| Outcome | Means |
|---|---|
| `sent` | The provider accepted it and returned a message id. |
| `failed` | It did not go. The reason is on the receipt, on the chain, and on the stream. |
| `skipped` | Nothing tried: no courier configured, or no address to send to. |

### The one entry allowed after the seal

Two requirements here are contradictory on their face.
The bundle mailed out has to be the **sealed** record, so the send cannot happen before sealing.
A send that failed has to be visible **in the chain**, so its outcome cannot live outside it.

`ReplaySession.append_courier_receipt` is the resolution and the only thing in this service permitted to append past a seal.
It **adds and never edits**: every entry up to and including the seal is unchanged, every `prev_hash` still matches, and the emailed copy is a byte-exact **prefix** of the archived one.
Both verify INTACT under the same `verify.py`, which needed no special case. The bundle's README explains the difference to whoever holds only the email.

Attempts accumulate while delivery is outstanding, because a first attempt that failed and a second that worked is exactly the history an investigator wants.
The moment one succeeds the record closes for good.

### Sending one

Automatic on seal, when a courier is configured and there is an address.
`POST /v1/incident/{id}/courier` is the manual path - the operator-supplied address is only known once somebody has answered the phone, and a failed send needs a way to be retried without replaying the incident.

```sh
curl -X POST http://127.0.0.1:8787/v1/incident/inc-0001/courier \
  -H 'content-type: application/json' \
  -d '{"to": "records@department.example.gov"}'
```

It answers **202 with the receipt on a failed send, not a 5xx**. The send is the subject of the request rather than a step inside it: a failure is a real answer that was recorded and published. 404 if there is no record, 409 if the record is not sealed yet.

### Verify the sending domain, by hand, once

**An unverified domain accepts the send, returns a message id, and delivers nothing.**
The receipt says `sent`, the chain says `sent`, and the inbox is empty. Nothing in an API response distinguishes that case, so nothing here pretends to - it is checked once by a human against a real inbox.

`cayden.tech` is verified on the project's Resend account as of 2026-09-20, which is why it is the default From domain.

## The motion detector, at `/motion`

**`GET /motion` is a redirect, not a page.**
It sends the browser to the WiFi RSSI motion detector in `wifi-rssi-motion-template/`, which runs as its own process, on its own port, with its own server and its own frontend.

This service does not embed it, proxy it, or read its output.
That detector is deliberately self-contained - it depends on nothing in `sensor/`, `agents/`, `app/` or ANS, and keeping it that way is worth more than the convenience of merging it.
So the only thing the hub owes it is a stable address, and the two consoles link to `/motion` rather than to a hardcoded `localhost:8766`.

`HAWKEYE_MOTION_CONSOLE_URL` sets where it points.
It defaults to `http://localhost:8766/index.html`, which is what `python3 server.py` prints when the detector runs on the same machine as the hub.
Set it to the detector's LAN address when it runs on the laptop nearest the router instead, and set it empty to drop the route, which makes `/motion` a 404 rather than a redirect to nowhere.

Start the detector separately; the hub does not launch it:

```sh
cd wifi-rssi-motion-template
.venv/bin/python3 server.py
```

## Notices

An unexpected presence that holds for `HAWKEYE_NOTICE_HOLD_S` seconds raises a notice: a banner in the app, and an SMS if Twilio is configured.
A notice is information the resident acts on.
It never creates an incident and never dials.

`app/backend/.env.example` lists every variable this service reads, with placeholders.
Copy it to `app/backend/.env` and fill it in; `.env` is gitignored and the example must never carry a real value.

**Every name is prefixed `HAWKEYE_`**, because `Settings` sets `env_prefix="HAWKEYE_"`.
A variable without that prefix is read by nothing, and nothing warns you: `TWILIO_ACCOUNT_SID` does nothing, `HAWKEYE_TWILIO_ACCOUNT_SID` works.
That is the most likely reason a correctly-credentialled Twilio account still sends no text.

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
    "provenance": { "source": "demo-trigger", "producer": "agents/master", "ansname": "master.hawkeye.invalid", "source_class": "simulated", "simulated": true }
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
It replaced the fall clock on 2026-09-19, when fall detection was cut.

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
      "field": "people.respiration",
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
        "unimplemented_dimensions": [
          "solvency",
          "behavior",
          "safety"
        ]
      },
      "recommended_profile": "UNTRUSTED"
    },
    "decision": "DISCARDED",
    "reason": "DISCARDED. The claim would have sent an armed response into a room where no sensor sees anybody. It was not relayed to the operator and it was not used in classification.",
    "checks": [
      {
        "name": "ans.resolve",
        "passed": false,
        "detail": "people.hawkeye-secure.invalid is not the ANSName registered for agents/people. The registered name is people.hawkeye.invalid."
      },
      {
        "name": "cert.version_binding",
        "passed": false,
        "detail": "Code fingerprint differs from the version-bound certificate issued at registration. The agent presenting this claim is not running the code it registered."
      },
      {
        "name": "trust_index.profile",
        "passed": false,
        "detail": "Trust Index recommendedProfile = UNTRUSTED."
      },
      {
        "name": "corroboration.sensor",
        "passed": false,
        "detail": "The corridor outside the front door is not part of the unit and is outside the sensed volume, so no agent in this mesh can see it, and no other agent reports a third occupant."
      }
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

`since_seq=N` returns only entries after that sequence, so the replay console tails an open record rather than refetching it.

Three sources answer this route, in order of authority.
The hub's own recorder holds the record it wrote entry by entry, and that is preferred whenever it exists.
`agents/replay` owns the record in live mode and is asked next.
Failing both, the store assembles one after the fact; that is a reconstruction rather than a recording, it proves less, and it stays only so incidents raised before the recorder existed still resolve.

### `GET /v1/replay`

The index of recorded incidents, newest first. One cheap summary row each: type, address, opened at, sealed, duration, entry count, verification count, discard count, root hash.

Only incidents this hub actually recorded appear.
An incident it saw mid-flight but never saw raised is deliberately absent rather than listed with a partial chain, because a record that silently omits its own beginning has the shape of a doctored one.

### `GET /v1/incident/{id}/replay/verify`

Recomputes the hash chain and returns `{intact, detail, failed_seq, entries, root_hash, sealed}`.

A pass means no entry has been edited, reordered, inserted or removed since it was written.
It does not mean the system that wrote the record wrote it honestly; that is the transparency log's job and the log is not wired.

### `GET /v1/incident/{id}/replay/export`

A zip, for handing to an investigator:

| Member | What it is |
|---|---|
| `record.json` | the full record, canonical JSON |
| `chain.txt` | one readable line per entry, needs nothing but a text editor |
| `verify.py` | dependency-free script that recomputes the chain and prints INTACT or names the altered entry |
| `README.txt` | what this proves, and plainly what it does not |

`verify.py` reimplements the canonical form rather than importing it, on purpose: a verifier that depends on the code that produced the record verifies nothing.
`tests/test_replay_session.py::test_the_shipped_verifier_agrees_with_the_server` is what keeps the two in step.

An unsealed record exports too, clearly marked as unsealed.
An investigator asking for the record mid-incident is a real scenario, and refusing would be worse than handing over something honestly labelled.

### `POST /v1/incident/{id}/courier`

Emails that same zip to the responding department. Full reasoning in the courier section above.

```json
{ "to": "records@department.example.gov" }
```

`to` is the address the 911 operator gave on the call, recorded with `operator_supplied` provenance - a human statement, never a verified binding and never authorization.
Omit it to fall back to `HAWKEYE_COURIER_TO`, recorded as `configured`.

Answers a `CourierReceipt`: `outcome` is `sent`, `failed` or `skipped`, with `to`, `provenance`, `message_id` and a one-line `detail`.

**202 even when the send failed.** The send is the subject of the request rather than a step inside it, and a failure is a real answer that was recorded on the chain and published to every surface. 404 if there is no record for that incident; 409 if the record is not sealed yet.

### `POST /v1/demo/run`

Drives the scripted detection and then stops. **Simulated mode only; 404s in live mode, deliberately.**

`?scenario=burglary|fire`, defaulting to `burglary`.

**`burglary`** is the frame the project is built around.
A perturbation appears in the living room with no respiration signature, which makes it `unconfirmed` and at that instant indistinguishable from the curtain over the dryer vent already sitting in that same room.
Respiration then resolves it into a person, and only then can `agents/intruder` ask its question: two residents on the roster, two phones associated, one body left over.
It crosses the unit, living room to dining room to the hallway outside the second bedroom, and stops there.

That stopping point is not squeamishness, it is the hardware.
A 1x1 radio has no spatial diversity, and two people within about a metre resolve as one presence.
Walking the intruder into the resident's room would draw a separation this link cannot measure, so the script stops at the doorway and the call says the limit out loud as a `CORROBORATION_ONLY` claim.

**`fire`** takes the breathing signature off the adult in the main bedroom, so `respiration_lost_s` climbs and does not reset, and the CO reading rises alongside it.
It is never a finding that breathing has stopped, here or anywhere else; it is a measurement and a clock.

`?simulate_human_tap=true` raises the incident type that matches the scenario.
A person who has just watched a stranger cross their living room does not press Fire, and a demo whose scripted tap disagrees with its scripted detection is showing a house that contradicts itself.

The default is detection only, because that is what the system does on its own.
The lost signature appears in `state`, `respiration_lost_s` climbs, CO rises, and no `incident` or `transcript` event is emitted at all.
The system notices and waits.

```sh
curl -X POST localhost:8787/v1/demo/run
# {"started":true,"detail":"scripted detection started; no incident raised, waiting on a human tap","raised_incident_id":null}
```

`?simulate_human_tap=true` additionally raises the incident type matching the scenario, exactly as `POST /v1/incident` would, with `raised_by: user`, so one curl exercises detection and call end to end.
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
    replay/
      chain.py              the one canonical SHA-256 shared by every chain here
      session.py            one incident's record: opened on a tap, sealed at the call's end
      recorder.py           routes events into sessions; wired into HubRuntime.emit
      export.py             the zip a detective is handed
      courier.py            mails that zip to the responding department, via Resend
      archive.py            where a sealed record goes so it outlives this process
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

`MongoStore` is a seam and stays unimplemented. It raises `NotImplementedError` rather than silently degrading to memory, because a service that claims to be persisting and is not is exactly the kind of quiet lie this project is built against.

**It should stay unimplemented even now that a cluster is reachable.** The store is on the incident path: motion has to reach a wrist in about three seconds, and there is no room in that budget for a round trip to Atlas. What actually needs to outlive the process is the sealed record, and that has its own narrower home.

## The replay archive

**Done, and verified against the real Atlas cluster on 2026-09-19.** This is what serves the MongoDB Atlas sponsor track.

`hawkeye_backend/replay/archive.py`. Turn it on with `HAWKEYE_REPLAY_ARCHIVE=mongodb` plus `HAWKEYE_MONGODB_URI`; `.env` already has both.

One collection, `replays`. One document per sealed record, `_id` is the `incident_id` so re-archiving replaces rather than forks, and each document carries a denormalized `summary` alongside the full `record` so the console index can draw a list without deserializing a few hundred frames per row.

| When | What happens |
|---|---|
| A record seals, i.e. the 911 call ends | `ReplayRecorder` queues the id; `HubRuntime._archive_sealed` writes it |
| `GET /v1/replay` | In-memory rows first, then archived rows the recorder no longer holds. The live row wins on conflict |
| `GET /v1/incident/{id}/replay` | Recorder, then `agents/replay`, then the archive, then the old reconstruction |
| `.../replay/verify` and `.../replay/export` | Both work on an archived record, which is the point: the export is the deliverable |

Three properties worth knowing before changing any of it:

- **The recorder never awaits a write.** It sits inside `HubRuntime.emit`, the single path every event takes to a phone, so it stays synchronous and hands off a list of sealed ids. The runtime does the writing one async frame up, after publish.
- **Hashes are stored, never recomputed on read.** A round trip that re-serialized a timestamp differently would produce a record that fails its own verifier, which is indistinguishable from tampering.
- **Every method fails soft and says so.** A record is complete in memory by the time it seals, so losing the archive costs durability and nothing else - and the moment it runs is the moment a 911 call ends, the worst possible time to raise. The failure surfaces on `GET /v1/replay`, in the startup log line, and as a banner on the console, because a configured archive that is silently unreachable is indistinguishable from a quiet night.

Rows read back are badged `ARCHIVED` on the console. A record written by a process that is gone is not the same claim as one this hub is currently holding.

### How it was verified

Against the project's own Atlas cluster, not a local stand-in: ran an incident to a sealed 32-entry record, confirmed the document in Atlas directly, **killed the hub**, restarted, and got the record back as `source: archive` with the chain `INTACT` - under the server-side check, under the standalone `verify.py` in the exported bundle, and under the in-browser verifier that never trusts the server.

### Two errors that look like a broken cluster

- **`CERTIFICATE_VERIFY_FAILED`** is a local trust store, not Atlas. A python.org Python on macOS ships no root certificates. `MongoReplayArchive.client_kwargs()` points the driver at `certifi`, so this is handled and nobody needs to run `Install Certificates.command`.
- **`TLSV1_ALERT_INTERNAL_ERROR`** means the machine's IP is not on the Atlas project's IP Access List. Atlas refuses the handshake before authentication, so it reads like a certificate problem and is not one. **Expect this again at the venue**, whose egress IP will differ from wherever you last tested.

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
