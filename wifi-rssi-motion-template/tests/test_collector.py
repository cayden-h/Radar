import logging

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


def test_read_failure_is_logged_once_not_every_tick(caplog):
    clock = make_fake_clock([1.0, 2.0, 3.0])
    collector = MacWifiCollector(rssi_reader=lambda: None, clock=clock)
    with caplog.at_level(logging.WARNING, logger="collector"):
        collector.poll_once()
        collector.poll_once()
        collector.poll_once()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_read_recovery_is_logged_once_after_a_failure(caplog):
    readings = iter([None, None, -60, -61])
    clock = make_fake_clock([1.0, 2.0, 3.0, 4.0])
    collector = MacWifiCollector(rssi_reader=lambda: next(readings), clock=clock)
    with caplog.at_level(logging.INFO, logger="collector"):
        collector.poll_once()  # fails
        collector.poll_once()  # fails again, no second warning
        collector.poll_once()  # recovers -> logged once
        collector.poll_once()  # still good -> no second recovery log
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1


def test_run_loop_logs_exception_failures_once_and_keeps_polling(caplog):
    calls = {"n": 0}

    def flaky_reader():
        calls["n"] += 1
        raise RuntimeError("boom")

    collector = MacWifiCollector(poll_hz=50.0, rssi_reader=flaky_reader)
    with caplog.at_level(logging.WARNING, logger="collector"):
        collector.start()
        collector._stop_event.wait(0.2)
        collector.stop()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert calls["n"] > 1  # the loop kept polling despite the exception
