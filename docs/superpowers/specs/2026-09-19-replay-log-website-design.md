# Replay log website, and a real recording lifecycle

Status: approved 2026-09-19.
Supersedes nothing.
Implements the "website for logs of the replay agent" ask, plus the recording lifecycle it implies.

## The problem

`agents/replay` is written and hash-chains entries, but nothing calls `open_incident`.
The hub's `GET /v1/incident/{id}/replay` assembles a record at read time from `InMemoryStore`, and stamps `sealed` from `incident.resolved_at`.
So the record is reconstructed after the fact rather than written as it happened, and there is no human surface for it outside the iOS app.

Two things follow.
The recording must actually start when the resident taps an incident and actually seal when the 911 call ends.
And the record needs a reviewing surface that is not a phone: a desktop console a detective can read, scrub, and export.

## Decisions

Taken 2026-09-19, with the reasoning, because each had a live alternative.

- **The website is a static page served by `app/backend`**, not a Next.js app on Vercel.
  No build step, no CDN, no second deploy target, same origin as the API.
  Venue wifi is not a dependency the demo can afford.
- **The recorder lives in the hub, not in `agents/replay`.**
  `HubRuntime.emit` is already the single path every event takes, which makes it the only place a record can be complete by construction.
  `agents/replay` remains the live-mode owner; wiring master to call it is a later change and does not alter this one.
- **The site replays recorded frames rather than mirroring live state.**
  During an active incident the map trails the phone by up to one second.
  That is correct: this is the record, not a second dashboard.
- **The RF trace is derived telemetry and `rf.raw_csi` stays null.**
  No raw CSI amplitude exists anywhere in the backend models.
  Plotting a fabricated subcarrier trace is exactly what the honesty rule in the root `CLAUDE.md` forbids, and the one judge most equipped to catch it is the one grading us.

## Components

### `hawkeye_backend/replay/chain.py`

The one canonical-JSON SHA-256 implementation.
`store.py` and `agents/replay` both converge on it, so three hash formats cannot drift apart and fail by luck.
Canonical form is `json.dumps(..., sort_keys=True, separators=(",", ":"))` over `{"prev": prev_hash, "entry": body}`, matching what `store.py` already does.

### `hawkeye_backend/replay/session.py`

`ReplaySession` is one incident's record: append-only, hash-chained, sealable once.

- `open(incident)` writes entry 1, kind `lifecycle`.
- `append(kind, summary, detail, at)` chains one entry.
- `seal(reason)` writes the closing `lifecycle` entry, stamps `sealed_at`, and freezes the chain.
- `append` after `seal` raises `RecordSealed`.
  A record that silently grew after sealing is worse than no record.
- `verify()` recomputes every link and returns `(intact, detail, failed_seq)`.
- `to_record()` produces the existing `ReplayRecord` model, so the iOS app and the API shape do not change.

### `hawkeye_backend/replay/recorder.py`

`ReplayRecorder` holds sessions by incident id and decides what opens, appends, and seals.

- `IncidentEvent`, phase `raised`, `raised_by == USER` opens a session.
  A `SYSTEM` raise does not: Hawk Eye never dials on its own, so there is nothing to record.
- `VerificationEvent`, `TranscriptEvent`, `InstructionEvent`, `ContextEvent`, `NoticeEvent` each append one entry.
- `StateEvent` appends a `frame` entry carrying every presence's zone, position, state, vitals and `still_down_s`, plus calibration, environment, and the `rf` block.
- `IncidentEvent` whose `call_state == ended` seals the session.

Recording is bounded.
Frames are throttled to one per `replay_frame_interval_s`, except a frame whose presence states changed is always kept.
At `replay_max_entries` the recorder stops recording frames only, keeps every claim, discard, transcript and instruction, and writes a `lifecycle` entry saying it stopped.
It degrades loudly rather than truncating quietly.

### The RF block

Built per frame from `InteriorState.calibration`, the hub's cached `SensorLiveness`, and per-presence vitals:
`frame_rate_hz`, `min_useful_frame_rate_hz`, `baseline_age_s`, `baseline_healthy`, `source`, `simulated`, and `raw_csi: null`.

`HubRuntime` gains a slow background poll (every 2s) that caches `SensorLiveness`, so the recorder never awaits an HTTP call from inside `emit`.
A failed poll leaves the cache stale and the frame records that, rather than inventing a reading.

The low-frame-rate band is shaded on the chart, which puts the quiet failure named in `sensor/CLAUDE.md` on the record instead of hiding it.

### API

```
GET /v1/replay                              index of recorded incidents
GET /v1/incident/{id}/replay                existing shape, now served from the session
GET /v1/incident/{id}/replay?since_seq=N    incremental tail
GET /v1/incident/{id}/replay/verify         chain recompute
GET /v1/incident/{id}/replay/export         the police bundle, as a zip
```

`InMemoryStore.build_replay` stays as the fallback for incidents with no session, so nothing that works today breaks.

### The website, `app/web/replay/`

One self-contained HTML file, vanilla JS, no build and no CDN, mounted at `/replay`.
While an incident is unsealed the page polls `?since_seq=N` at 1 Hz.
One channel, not a websocket: a log a human reads does not need sub-second latency, and it avoids a second client implementation to debug during the build.

Desktop-dense, an operations console rather than the phone UI.

- Index: a card per incident with type, address, raised at, duration, call state, sealed badge, entry count, root hash prefix.
- Record: floorplan as inline SVG from the room polygons, presence dots colored by `PresenceState`, a growing halo on `still_down_s`, and a scrubber that steps through recorded frames.
  The entry log sits alongside, filterable by kind, with accepted and discarded verifications split apart and the discards given equal weight.
  The RF strip chart runs underneath, time-aligned to the scrubber.
- Chain panel: recomputes every hash in the browser with WebCrypto and reports intact, or names the first altered entry.
  Verifying client side is the stronger claim, because it does not ask the server to vouch for itself.

### Export for police

`GET .../export` returns a zip:

- `record.json`, the full record in canonical JSON
- `chain.txt`, one readable line per entry, needing no tooling
- `verify.py`, a dependency-free script that recomputes the chain and prints INTACT or ALTERED
- `README.txt`, stating what this proves and plainly what it does not

There is no SCITT receipt yet, so the record is tamper-evident to whoever holds it and to nobody else.
The README says exactly that.
A print stylesheet on the record page covers save-as-PDF without a PDF library.

## Testing

`app/backend/tests/test_replay_session.py` covers:
a user tap opens a session and a SYSTEM raise does not;
one entry per event;
frames throttled but presence-state changes always kept;
`CallState.ENDED` seals;
append after seal is refused;
the chain verifies;
tampering entry 4 fails at entry 4 and not before;
the export bundle contains what it claims and `verify.py` runs.

The existing 37 security tests stay green.

## What this does not do

It does not submit to SCITT, and it does not make the record verifiable by a third party who does not already hold it.
It does not move the recorder into `agents/replay`.
It does not record raw CSI, because none exists to record.
