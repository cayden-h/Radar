"""Retell settings: all-or-unconfigured, and the transport default."""

from __future__ import annotations

from hawkeye_backend.config import Settings


def test_retell_unconfigured_by_default():
    s = Settings(_env_file=None)
    assert s.retell_configured is False
    assert s.call_transport == "retell"


def test_retell_configured_when_all_present():
    s = Settings(
        _env_file=None,
        retell_api_key="key",
        retell_from_number="+15550001111",
        retell_websocket_secret="s3cr3t",
    )
    assert s.retell_configured is True


def test_retell_not_configured_when_secret_missing():
    s = Settings(_env_file=None, retell_api_key="key", retell_from_number="+15550001111")
    assert s.retell_configured is False
