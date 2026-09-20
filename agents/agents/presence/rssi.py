"""The real motion feed: WiFi RSSI, classified, presented as `CsiFrame`s.

This is the honest swap-in behind the `CsiFeed` port for the RSSI modality. The
synthetic feed in `agents.core.dev` and the (future) nexmon capture in `sensor/`
both hand `presence` per-subcarrier channel amplitude to threshold itself. This
one does not: the standalone `wifi-rssi-motion-template/` already runs a full
collector -> features -> classifier pipeline over the MacBook's CoreWLAN RSSI and
emits a *confirmed* `"active"`/`"absent"` verdict at roughly 3 Hz, baseline,
hysteresis and all.

**We keep the port and trust the verdict.** The port stays so the source of
motion remains swappable and visible in the data (`source="wifi-rssi"`, which
`Provenance` classifies as MEASURED_LIVE). But we do not re-run `presence`'s
percentile-baseline / OCCUPIED_EXCESS math on the RSSI energy figure: that math
is tuned for per-subcarrier CSI amplitude and would be measuring an RSSI number
against a yardstick it was never scaled against. Instead each synthesized frame
carries the classifier's confirmed state in `CsiFrame.motion_state`, and
`PresenceAgent.tick` takes the verdict directly. `amplitude` still carries the
tick's `motion_energy` for one room, so the record and the feed are populated,
but it is not what decides the claim.

The pipeline is composed exactly as `wifi-rssi-motion-template/server.py`'s
`build_tick_payload` (server.py:25-36) composes it - collector.snapshot() ->
extract_features -> classifier.classify - replicated inline rather than imported,
because `server.py` pulls in `websockets` and `calibrate` at module load and this
feed needs neither the WebSocket server nor the calibration UI.

Honesty when the radio is not there: on a non-macOS host, or when CoreWLAN cannot
associate, the collector produces no samples. This feed then emits no frames at
all - `latest()` returns None and `window()` returns empty - so `presence` reports
blind rather than manufacturing a confident `"absent"` out of an empty buffer. A
system with no signal must say it has no signal.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from agents.core.ports import CsiFrame

logger = logging.getLogger(__name__)

#: The template package (`collector.py`, `features.py`, `classifier.py`) is not
#: installed and is not on `sys.path` by default: its own modules import each
#: other with bare names (`from classifier import ...`), so the directory itself
#: has to be importable. We add it here, mirroring exactly how the template
#: expects to be run, rather than restructuring vendored code we do not own.
#: rssi.py lives at <repo>/agents/agents/presence/rssi.py, so the template is
#: three parents up from the `agents` top package.
_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "wifi-rssi-motion-template"
if _TEMPLATE_DIR.is_dir():
    template_path = str(_TEMPLATE_DIR)
    if template_path not in sys.path:
        sys.path.append(template_path)


#: The room this one fixed link is watching. RSSI is a single scalar off one
#: radio - there is no spatial resolution to split rooms with - so the whole
#: modality is scoped to exactly one configured room, and every frame carries it.
DEFAULT_ROOM = "living_room"

#: How often the pipeline is ticked, and the TRUE rate reported on every frame.
#: Matches the template's own default (server.py:47). It is genuinely below
#: `presence`'s CSI rate floor (MIN_RATE_HZ = 5.0 Hz), which is exactly why the
#: RSSI verdict path skips that floor: the classifier already separated motion
#: from noise at this rate, so the floor - which exists to stop *raw* CSI being
#: thresholded too slowly - does not apply.
DEFAULT_POLL_HZ = 3.0

#: Analysis window handed to `extract_features`. Matches the template default.
DEFAULT_WINDOW_S = 4.0

#: Hysteresis: a new raw state must repeat this many consecutive ticks before the
#: classifier confirms it. Matches the template default and debounces the short
#: analysis window so a single noisy tick cannot flip the verdict.
DEFAULT_HYSTERESIS_TICKS = 2

#: How much synthesized-frame history to retain, in seconds. `presence` pulls a
#: 30 s window each tick (WINDOW_S), so this must comfortably exceed it.
HISTORY_S = 60.0


class RssiCsiFeed:
    """`CsiFeed` over the WiFi-RSSI motion pipeline, scoped to one room.

    Runs the template's collector on its own daemon thread (the collector) plus a
    second daemon thread of our own that, at the poll rate, snapshots the RSSI
    ring buffer, extracts features, classifies, and appends one synthesized
    `CsiFrame` carrying the confirmed verdict. `presence` reads it through the
    ordinary `latest()`/`window()` port methods and never learns it is RSSI
    except through `source` and `motion_state`.
    """

    def __init__(
        self,
        *,
        room: str = DEFAULT_ROOM,
        poll_hz: float = DEFAULT_POLL_HZ,
        window_seconds: float = DEFAULT_WINDOW_S,
        hysteresis_ticks: int = DEFAULT_HYSTERESIS_TICKS,
        history_s: float = HISTORY_S,
    ) -> None:
        self._room = room
        self._poll_hz = poll_hz
        self._window_seconds = window_seconds
        self._history_s = history_s

        self._frames: deque[CsiFrame] = deque(maxlen=max(1, int(poll_hz * history_s)))
        self._lock = threading.Lock()
        self._sequence = 0

        self._collector = None
        self._classifier = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._available = False

        self._start(hysteresis_ticks)

    # ------------------------------------------------------------------ startup

    def _start(self, hysteresis_ticks: int) -> None:
        """Bring the template pipeline up, or stay blind if the radio is absent.

        Every failure mode here - no macOS, no CoreWLAN, no association - is a
        reason to report nothing rather than to raise: a sensing feed that threw
        on a laptop with WiFi off would take the whole agent down, and the agent
        is supposed to keep running and say it cannot see. So this catches
        broadly, logs once, and leaves `_available` False, at which point
        `latest()`/`window()` behave exactly like a feed that has produced no
        frames yet.
        """
        try:
            # Bare imports, resolved against the template dir added to sys.path
            # above. This mirrors how the template's own modules import each
            # other; see server.py's identical `from collector import ...`.
            from classifier import BaselineClassifier  # type: ignore[import-not-found]
            from collector import MacWifiCollector  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 - a missing template is a blind feed, not a crash
            logger.warning(
                "wifi-rssi-motion-template not importable; RSSI feed is blind", exc_info=True
            )
            return

        try:
            # buffer_seconds must hold at least the analysis window plus slack.
            self._collector = MacWifiCollector(
                poll_hz=self._poll_hz, buffer_seconds=self._window_seconds + 3.0
            )
            # hysteresis_ticks debounces the short analysis window, matching how
            # server.py constructs its classifier (server.py:64).
            self._classifier = BaselineClassifier(hysteresis_ticks=hysteresis_ticks)
            self._collector.start()
        except Exception:  # noqa: BLE001 - CoreWLAN missing / no interface => blind, not dead
            logger.warning("WiFi RSSI collector failed to start; feed is blind", exc_info=True)
            self._collector = None
            self._classifier = None
            return

        self._available = True
        self._thread = threading.Thread(target=self._run, name="rssi-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the poll thread and the collector. Idempotent."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._collector is not None:
            self._collector.stop()

    # -------------------------------------------------------------- the poll loop

    def _run(self) -> None:
        poll_interval = 1.0 / self._poll_hz
        while not self._stop.is_set():
            try:
                self._tick_once()
            except Exception:  # noqa: BLE001 - one bad tick must not kill the feed
                logger.warning("RSSI feed tick failed", exc_info=True)
            self._stop.wait(poll_interval)

    def _tick_once(self) -> None:
        """One composition of collector -> features -> classifier -> `CsiFrame`.

        Only appends a frame when the collector actually has samples to reason
        over. An empty snapshot means the radio has produced nothing (WiFi off,
        disassociated, non-macOS reader raising every poll), and manufacturing an
        `"absent"` verdict from it would be a confident answer with no measurement
        behind it. We stay silent instead, and `presence` reports blind.
        """
        assert self._collector is not None and self._classifier is not None

        # Composition mirrors server.py:25-36 (build_tick_payload) exactly, minus
        # the WebSocket payload shaping we do not need.
        from features import extract_features  # type: ignore[import-not-found]

        snapshot = self._collector.snapshot()
        if len(snapshot) < 2:
            # extract_features needs at least two samples to produce a real
            # variance / motion_energy; below that the radio has told us nothing.
            return

        features = extract_features(snapshot, window_seconds=self._window_seconds)
        state = self._classifier.classify(features["variance"], features["motion_energy"])

        self._sequence += 1
        frame = CsiFrame(
            captured_at=datetime.now(UTC),
            sequence=self._sequence,
            # One room, one scalar. The RSSI path does not decide the claim off
            # this number - `motion_state` does - but the record still wants the
            # energy the verdict was drawn from.
            amplitude={self._room: float(features["motion_energy"])},
            # The TRUE poll rate, not faked to clear any floor. It is genuinely
            # below MIN_RATE_HZ, and the RSSI verdict path skips that floor.
            rate_hz=self._poll_hz,
            source="wifi-rssi",
            motion_state=state,
        )
        with self._lock:
            self._frames.append(frame)

    # ----------------------------------------------------------------- the port

    def latest(self) -> CsiFrame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def window(self, seconds: float) -> list[CsiFrame]:
        with self._lock:
            if not self._frames:
                return []
            newest = self._frames[-1].captured_at
            cutoff = newest.timestamp() - seconds
            return [f for f in self._frames if f.captured_at.timestamp() >= cutoff]
