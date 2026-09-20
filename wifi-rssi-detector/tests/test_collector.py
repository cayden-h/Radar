import pytest
from collector import MacWifiCollector


def make_fake_clock(times):
    it = iter(times)
    return lambda: next(it)


def test_poll_once_appends_sample_and_returns_it():
    clock = make_fake_clock([100.0])
    collector = MacWifiCollector(rssi_reader=lambda: -60, clock=clock)
    result = collector.poll_once()
    assert result == (100.0, -60)
    assert collector.snapshot() == [(100.0, -60)]


def test_poll_once_skips_sample_on_read_failure():
    clock = make_fake_clock([100.0])
    collector = MacWifiCollector(rssi_reader=lambda: None, clock=clock)
    result = collector.poll_once()
    assert result is None
    assert collector.snapshot() == []


def test_buffer_is_bounded_by_poll_hz_and_buffer_seconds():
    # poll_hz=2, buffer_seconds=1 -> maxlen 2
    times = iter(float(i) for i in range(10))
    clock = lambda: next(times)
    collector = MacWifiCollector(poll_hz=2.0, buffer_seconds=1.0, rssi_reader=lambda: -60, clock=clock)
    for _ in range(5):
        collector.poll_once()
    snapshot = collector.snapshot()
    assert len(snapshot) == 2


def test_snapshot_returns_samples_oldest_first():
    times = iter([1.0, 2.0, 3.0])
    clock = lambda: next(times)
    collector = MacWifiCollector(poll_hz=10.0, buffer_seconds=100.0, rssi_reader=lambda: -60, clock=clock)
    for _ in range(3):
        collector.poll_once()
    snapshot = collector.snapshot()
    assert [ts for ts, _ in snapshot] == [1.0, 2.0, 3.0]
