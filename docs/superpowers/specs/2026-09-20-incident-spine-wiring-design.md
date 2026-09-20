# Incident spine wiring — design

Date: 2026-09-20
Target: merged into `main` via one PR.

Three seams close the "works together" spine across the three merged halves
(#17 courier, #18 hub/camera, #19 Retell caller). Each is implemented on its own
branch by a subagent, integrated onto `spine-wiring`, and tested **only** once
all three are wired.

## Seam 1 — caller → courier (T40/T44)

**State.** The backend endpoint `POST /v1/incident/{incident_id}/courier`
(`app/backend/hawkeye_backend/api.py`) is complete: body `{to: <email>}`,
records `operator_supplied` provenance, and chains the receipt. Nothing on the
caller side asks the operator for the email or posts it.

**Wiring** — all in `agents/agents/caller/transport/retell/`:

- A 3-state machine in `RetellCallOrchestrator`: `NORMAL → ASKED_EMAIL →
  CONFIRMED`. When an operator line trips a closing/dispatch cue (reuse the
  existing `OPERATOR_CUES` `dispatched`/`eta` intents), the caller's next turn
  asks: *"What email address should I send the sealed incident record to?"*
- The next operator line is parsed for an email address. The caller reads it
  back verbatim for confirmation.
- On confirmation, an injected `BackendCourierClient` (httpx) POSTs
  `{to: email}` to the courier endpoint for `self.incident_id`. Failure is
  logged, never raised — the chain records the outcome on the backend side.
- The email is a destination only. Never trusted as authorization.

**Files:** `retell/orchestrator.py` (state machine + POST), a new
`retell/courier_client.py` (httpx client + a simulated one for tests), and an
email-parse/readback helper. Do **not** touch `agents/core/ports.py` or
`hawkeye_backend/models/common.py`.

## Seam 2 — vision gate + `vision.description` (rest of T16)

**Rule (agents/CLAUDE.md):** `vision` emits no claim unless it holds a current,
verified, *open* attestation from `shutter`. Otherwise
`Unknown(field=..., reason="shield_closed")` via `Agent.blind()`.

**Wiring** — in `agents/agents/vision/`:

- `VisionAgent` gains two injected ports, declared **inside the vision package**
  (not `core/ports.py`, to avoid colliding with seam 3):
  - `AttestationSource.current() -> Attestation | None` — the latest shutter
    attestation.
  - `NarrationSource.latest() -> Narration | None` — the latest narration from
    `hawkeye_vision/narrate.py`.
- Per tick: an attestation is usable only when present, `position == "open"`,
  and fresh (attested within `ATTESTATION_TTL_S`). Absent/stale/closed →
  `Unknown` for both `vision.occupancy` and `vision.description`,
  `reason="shield_closed"`.
- Usable attestation → emit today's `vision.occupancy` **plus**
  `vision.description` carrying the narration text, `source: generated`,
  `zone_scope=room`. No narration yet → `Unknown(vision.description,
  reason="narrator_unreachable")` but occupancy still emits.

**Files:** `vision/agent.py`, a new `vision/attestation.py` (ports + a simple
in-process source). Do **not** touch `agents/core/ports.py`.

## Seam 3 — presence / RSSI bridge

**State.** `presence` reads a `CsiFeed`; only impl is `SyntheticCsiFeed`
(ruview-sim). The `wifi-rssi-motion-template` classifier (active/absent at ~3Hz)
is standalone and unread.

**Decision (best of verdict-bridge and port-reuse):** keep the `CsiFeed` port
so the source is swappable and visible, but trust the classifier's verdict
rather than re-running CSI noise math on a signal it wasn't tuned for.

**Wiring:**

- New `agents/agents/presence/rssi.py`: `RssiCsiFeed(CsiFeed)` runs
  collector→features→classifier (imported from `wifi-rssi-motion-template`) on a
  background thread and synthesizes `CsiFrame`s for the one configured room at
  the true poll rate, `source="wifi-rssi"`.
- `CsiFrame` (`agents/core/ports.py`) gains optional `motion_state: str | None`
  (default `None`). CSI path: always `None`, existing behavior byte-identical.
  RSSI: carries the classifier's confirmed `"active"`/`"absent"`.
- `PresenceAgent.tick`: when the newest frame carries a `motion_state`, use it
  directly for `presence.motion` and **skip** the `MIN_RATE_HZ` floor and the
  percentile baseline (the classifier already separated motion from noise).
  Otherwise the existing CSI path is unchanged.
- Add `Source.WIFI_RSSI` (`hawkeye_backend/models/common.py`), classified as a
  **real measurement** (Mac WiFi RSSI is a real radio, not a sim). Update the
  `_source` fallback in `presence/agent.py` to map `"wifi-rssi"` to it.

**Files:** `presence/rssi.py` (new), `presence/agent.py`, `core/ports.py`
(the one `CsiFrame` field), `hawkeye_backend/models/common.py` (Source enum).
Do **not** touch vision or caller.

## Integration order (minimizes conflicts)

1. seam 3 (touches `common.py` Source + `ports.py` `CsiFrame`)
2. seam 2 (vision only)
3. seam 1 (retell only)

Full test suite (`agents` + `app/backend`) runs **only** after all three land.
