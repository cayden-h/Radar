"""Polls WiFi RSSI via CoreWLAN into a bounded ring buffer."""

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


def _read_rssi_via_corewlan():
    import CoreWLAN

    client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
    iface = client.interface()
    if iface is None:
        return None
    value = iface.rssiValue()
    if value == 0:
        # CoreWLAN returns 0 when there's no valid reading (e.g. disassociated)
        return None
    return value


class MacWifiCollector:
    def __init__(self, poll_hz=3.0, buffer_seconds=15.0, rssi_reader=None, clock=time.time):
        self.poll_hz = poll_hz
        self.poll_interval = 1.0 / poll_hz
        self.rssi_reader = rssi_reader or _read_rssi_via_corewlan
        self.clock = clock
        maxlen = max(1, int(poll_hz * buffer_seconds))
        self._buffer = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()
        self._read_failed = False

    def poll_once(self):
        rssi = self.rssi_reader()
        if rssi is None:
            self._note_read_failure("reader returned no value (e.g. disassociated)")
            return None
        self._note_read_recovery()
        sample = (self.clock(), rssi)
        with self._lock:
            self._buffer.append(sample)
        return sample

    def snapshot(self):
        with self._lock:
            return list(self._buffer)

    def _note_read_failure(self, reason):
        # Log once when a read starts failing, not on every tick, per spec.
        if not self._read_failed:
            self._read_failed = True
            logger.warning("WiFi RSSI read failing: %s (further failures suppressed until recovery)", reason)

    def _note_read_recovery(self):
        if self._read_failed:
            self._read_failed = False
            logger.info("WiFi RSSI read recovered")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # a single failed read shouldn't kill the poll loop
                self._note_read_failure(f"exception: {exc!r}")
            self._stop_event.wait(self.poll_interval)

    def start(self):
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
