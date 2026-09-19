# Master's hub API

Written 2026-09-19.
Closes `agents/TODO.md` item 6, the largest functional gap on the list after deployment.

## The problem

`app/backend/hawkeye_backend/master/live.py` is written against five endpoints on `agents/master`: `/v1/state`, `/v1/sensor`, `/v1/agents`, `/v1/incident` and `/v1/stream`.
Master serves none of them.
`agents/core/runtime.py` serves the two cards, `/healthz`, `/v1/observation` and `/v1/identity`, and nothing else.

So `HAWKEYE_MODE=live` cannot work, and the app has no path to the real mesh.

The gap is larger than five route handlers, and that is the finding that shapes this design.
`live.py` assumes master can produce an `InteriorState`.
It cannot.
Master's `tick()` produces an `AgentObservation`: flat, zone-scoped assertions such as `people.respiration` and `intruder.unexpected_presence`.
What the app renders is an `InteriorState`: structured `Presence` objects with positions, vitals and classes, plus a `Floorplan`.
Nothing in the repository projects one into the other.

That projection is the bulk of this work.

## Decisions taken

Four forks were settled before design, three of them the open `TODO(master)` questions in `live.py`.

| Question | Decision | Consequence |
|---|---|---|
| Where does the claims-to-`InteriorState` projection live? | In master, with the floorplan injected | `live.py` is correct as written and does not change |
| How does master push to the hub? | WebSocket on `/v1/stream` | `live.py`'s `_stream_loop` already implements the client half |
| How does `/v1/sensor` learn the frame rate? | `people` asserts it over the signed channel | The number that catches the quiet failure is itself verified |
| Must the hub present an identity to raise? | Bearer token on mutating routes only | Deployable tonight; mTLS replaces it under item 10 without touching handlers |

The projection lives in master rather than the hub because the hub must not interpret sensing data.
That line is the same one the whole architecture is built on, and the cost of holding it is that building geometry now sits inside the trust boundary agent.
That cost is accepted.

The bearer token is an honest interim and must be described as one.
It is not ANS, it proves nothing about identity, and `x-security-note` on master's card must not imply otherwise.

## Two findings that the design must handle

**`Incident.address` is required and master must never receive it.**
The hub's `Incident` model requires `address`, described as what the caller reads to the dispatcher.
Master's own docstring says the dispatch address "is not here and must never be".
These reconcile exactly one way: the address is injected into master's configuration, bound at registration and sealed, and never arrives in a claim or a request body.
`site_id` is injected the same way.
An agent that can change where a response is sent is a swatting tool no matter how well the claims upstream verify.

**`DEMO_ZONES` and the floorplan disagree.**
`agents/__main__.py` feeds a zone called `entry`.
`build_floorplan` has no `entry`, and does have a `dining_room` the synthetic feed never produces.
A presence in `entry` projects to a zone with no polygon and no centroid.
Zones must be derived from the floorplan rather than listed a second time.

## Components

### `agents/master/projection.py`, new

Groups admitted claims by `zone_scope` and builds one `Presence` per occupied zone.

```
people.personhood            -> vitals.person_confidence, and the state decision
people.respiration           -> RespirationStatus
people.breathing_bpm         -> vitals.breathing_bpm, null outside 6-30
people.heart_bpm             -> vitals.heart_bpm
people.moving                -> moving
people.presence_class        -> PresenceClass, with class_basis
people.still_down_s          -> still_down_s
intruder.unexpected_presence -> expected, inverted
master.co_ppm, co_elevated   -> EnvironmentReading
people.frame_rate_hz         -> Calibration and SensorLiveness
people.baseline_age_s        -> Calibration.baseline_age_s
```

Three rules are structural rather than conventional.

**Only admitted claims become presences.**
A discarded claim must never render as a person.
That is the entire refusal story, and projecting a discard would undo it silently.

**`UNKNOWN` is not `UNCONFIRMED`.**
A presence whose respiration has not resolved sits in `UNKNOWN`.
Absence of respiration is not proof of absence of a person, and `models/state.py` already says so.

**One presence per occupied zone.**
Two people within about a metre merge into one.
That is the documented limit of a 1x1 radio and the projection must not invent a headcount the physics does not support.

Position is the zone centroid computed from the injected floorplan polygon, which also removes the hand-maintained `ZONE_CENTROID` table.
`Presence.provenance` is carried from the originating claim, so a simulated reading stays labelled simulated all the way to the screen.

### `agents/master/stream.py`, new

A fan-out of bounded per-subscriber queues, drop-oldest, so one slow client cannot stall master.

The publisher is an async task in the app lifespan running at 2 Hz, reading `master.admitted` and `master.discarded`.
It is deliberately not a hook inside `tick()`.
`tick` runs in a worker thread via `asyncio.to_thread`, so publishing from there would need `call_soon_threadsafe`; polling from the loop side avoids the threading question entirely and mirrors `simulated.py`'s `_state_loop`.

Verification events would otherwise flood at 2 Hz, because `_local_air` mints a fresh `uuid4` for every claim on every tick.
So: every discard publishes, always, because discards are rare and they are the submission.
Admitted claims publish only when `(ansname, field, decision, will_be_spoken)` changes.

The hub renumbers `seq` on arrival, since `HubRuntime.emit` assigns from its own store.
Master's `seq` is per-connection and exists to satisfy the envelope, not to be authoritative.

### `agents/master/hub_api.py`, new

The five routes.
Bearer token from `HAWKEYE_HUB_TOKEN` on the mutating routes only; reads stay open so a judge can curl them.

`/v1/agents` requires master to retain per-peer last-seen and latency, which `_gather` computes today and discards.

`/v1/incident/{id}/replay` returns 404 `replay_not_wired` with an honest detail.
Master proxying to `agents/replay` is TODO item 7, and `live.py`'s `fetch_replay` already degrades to `None`.
A stub that says what it is beats a fabricated sealed record.

### Modified

- `agents/people/` gains three site-scoped `INFORMATIONAL` assertions: `frame_rate_hz`, `baseline_age_s`, `csi_source`.
- `agents/core/runtime.py` gains `extra_routers=()`, so master-specific routes stay in `master/`.
- `agents/__main__.py` wires floorplan, site id and address for master, and derives zones from the floorplan.
- `agents/master/agent.py` retains mesh health per peer.

The floorplan is imported from `hawkeye_backend.master.scenario.build_floorplan`, not copied.
`agents` already depends on that package, and a second definition is how two things start to disagree.

## Testing

In `agents/tests/`:

- Projection: a discarded claim never becomes a presence; unresolved respiration lands in `UNKNOWN` and not `UNCONFIRMED`; simulated provenance survives to the `Presence`.
- Routes via `TestClient`: 401 without the token on mutating routes, 200 on reads without it, a SYSTEM raise refused at `release_for_call`.
- Stream: a websocket client receives hello then state, and a discard always publishes.

## Docs to update

Each of these currently asserts something this work makes false.

| File | Stale claim |
|---|---|
| `agents/TODO.md` | Item 6 open; "Master serves none of them" |
| `agents/CLAUDE.md` | Line 708, "It serves none of the five endpoints"; line 334, "`master` does not exist yet" |
| `CLAUDE.md` | Status section, master serving no hub API |
| `app/backend/README.md` | Line 159, "Written, never exercised"; "`agents/master` does not exist yet" |
| `docs/swapping-in-real-parts.md` | The `HAWKEYE_MODE=live` row and its seam, now that live mode has something to talk to |
| `app/ios/README.md` | Check the `/v1/state` row still reads true |
| `ans/CARD.md` | Master's `x-security-note` if the bearer token is surfaced on the card |

`app/backend/schema/*.json` is generated by `tools/gen_schema.py`.
If any model shape changes it is regenerated with that tool and never hand-edited.

## Out of scope

- Wiring `replay`, `caller` release and the incident id through the transport. That is TODO item 7.
- mTLS. That is item 10 and is blocked on certificates.
- Deployment. That is item 1 and proceeds in parallel.
