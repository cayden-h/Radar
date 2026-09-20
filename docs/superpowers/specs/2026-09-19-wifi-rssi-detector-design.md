# WiFi RSSI motion/presence detector (Mac-only backup)

## Status

Design approved. New, self-contained subsystem — no dependency on the
Pi/CSI (`sensor/`) path, no changes to any existing agent or interface.
Lives entirely under `wifi-rssi-detector/` on its own branch, `wifi-rssi-detector`.

## Why

The Pi 4B + `nexmon_csi` capture path (`sensor/`) is real but has proven fragile
during bring-up. This is a backup presence/motion signal that runs entirely on
the MacBook already on the team's roster, using ordinary WiFi RSSI rather than
raw CSI, so it needs no additional hardware and no monitor-mode network
interruption. It is not wired into the agent mesh or ANS — it is a standalone
demonstration/fallback tool.

Reference approach (ported, not copied — source is Windows/`netsh`-based):
https://github.com/ruvnet/RuView/issues/36 — RSSI collector -> feature
extractor (rolling variance, motion-band energy) -> threshold classifier
(absent / present-still / active).

## Non-goals

- No integration with `agents/`, ANS, or the app backend/frontend. This is a
  freestanding tool in its own directory.
- No FFT/spectral banding unless calibration shows simple frame-to-frame
  delta energy fails to separate "still" from "walking" — start simple.
- No persistence/database. State is in-memory, broadcast live, not logged.
- No auth on the local WebSocket server — localhost-only, demo tool.

## Architecture

```
CoreWLAN (iface.rssiValue())
        │  poll ~3Hz, background loop
        ▼
MacWifiCollector          — ring buffer of (timestamp, rssi_dbm)
        │
        ▼
features.py                — sliding ~12s window:
                              rolling variance(rssi)
                              motion_energy = mean((Δrssi)^2) frame-to-frame
        │
        ▼
classifier.py               — EMA baseline of variance/motion_energy during
                               quiet periods; ratio-based thresholds:
                               absent  → variance/baseline ≈ 1 (near-zero abs. variance)
                               present-still → variance ratio above absent threshold,
                                               motion_energy ratio below motion threshold
                               active  → motion_energy ratio above motion threshold
        │
        ▼
server.py (asyncio + `websockets`)
        — runs collector/extractor/classifier tick loop
        — broadcasts {ts, rssi, variance, motion_energy, state} as JSON to
          all connected WebSocket clients, once per tick
        │
        ▼
static/index.html           — single static file, no build step
                               connects to ws://localhost:<port>
                               big colored status badge (ABSENT/PRESENT/MOTION)
                               canvas sparkline of recent RSSI samples
```

## Components

- **`collector.py` — `MacWifiCollector`**
  Wraps `CoreWLAN.CWWiFiClient.sharedWiFiClient().interface().rssiValue()`.
  Runs a poll loop (thread or asyncio task) at a configurable rate (default
  3Hz). Holds a bounded ring buffer (e.g. `collections.deque(maxlen=N)`) of
  `(timestamp, rssi_dbm)`. Exposes a way to read the current buffer snapshot.
  If `rssiValue()` is unavailable (no interface / not associated), samples
  are skipped rather than fabricated — the buffer just doesn't grow that
  tick, and downstream code tolerates short gaps.

- **`features.py`**
  Given a buffer snapshot, computes over the trailing ~12s window:
  - `variance`: population variance of RSSI values in the window
  - `motion_energy`: mean of squared consecutive differences (Δrssi²) in the
    window
  Pure functions, no state — testable by calibration script directly on
  captured sample arrays.

- **`classifier.py`**
  Maintains an EMA baseline (slow-adapting, e.g. alpha≈0.02) of `variance`
  and `motion_energy`, updated every tick *unless* the current tick is
  already classified `active` (so the baseline doesn't chase real motion).
  Classifies via ratios against baseline:
  - `variance_ratio = variance / max(baseline_variance, epsilon)`
  - `motion_ratio = motion_energy / max(baseline_motion_energy, epsilon)`
  Two thresholds (`PRESENT_VARIANCE_RATIO`, `ACTIVE_MOTION_RATIO`) start as
  named constants at the top of the file, filled in from calibration
  results — not guessed.

- **`server.py`**
  `asyncio` + `websockets` library. Single background task ticks the
  collector→features→classifier pipeline at the poll rate and broadcasts the
  JSON payload to all connected clients. Serves the static frontend file
  too (simple aiohttp/http.server alternative, or just instruct the user to
  open `static/index.html` directly as a `file://` — decide at
  implementation time based on WebSocket-from-`file://` CORS behavior;
  fallback is a two-line `python -m http.server` note in the README).

- **`static/index.html`**
  No build step, no framework. Inline `<script>` opens the WebSocket,
  updates a status badge element's text/color per `state`, and draws a
  scrolling RSSI sparkline on a `<canvas>` from the last ~60 samples kept
  client-side.

- **`calibrate.py`**
  CLI tool, run standalone (no server needed):
  `python calibrate.py --label still --seconds 10 --out still.json`
  `python calibrate.py --label walk --seconds 10 --out walk.json`
  `python calibrate.py --compare still.json walk.json`
  The `--compare` mode loads both captures, runs `features.py` over each
  using the same sliding-window logic, prints the variance and
  motion_energy distributions (min/mean/max) side by side, and prints a
  suggested threshold sitting between the two distributions. This satisfies
  "do a proper labeled calibration... don't guess at a threshold and eyeball
  it live."

## Data flow / error handling

- CoreWLAN read failures (no WiFi, permission issue, disassociated) are
  logged once (not spammed every tick) and treated as a dropped sample —
  the pipeline continues with whatever is in the buffer.
- WebSocket disconnects/reconnects are handled by the `websockets` library's
  per-connection handler; a dropped client doesn't affect others or the
  collector loop.
- No dBm values are ever hardcoded as absolute thresholds anywhere outside
  the calibration output — this was an explicit requirement ("ratio-based
  thresholds relative to a slow-adapting ambient baseline, not fixed
  absolute numbers").

## Testing plan

No unit-test framework — this is a demo/backup tool, not part of the graded
trust layer. Verification is:
1. `calibrate.py --compare` on real labeled still/walk captures, confirming
   the two distributions are visibly separable before picking thresholds.
2. Manual run: `python server.py`, open `static/index.html`, walk between
   the laptop and the router, confirm the badge transitions
   ABSENT → PRESENT → MOTION and the sparkline updates live.

## Out of scope / explicitly deferred

- FFT/Hann-window spectral analysis (only if delta-energy proves
  insufficient during calibration).
- Multi-interface / multi-AP RSSI fusion.
- Any wiring into `agents/`, `app/backend/`, or ANS.
