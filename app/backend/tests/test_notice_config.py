"""Twilio configuration, and the requirement that its absence is harmless."""

from __future__ import annotations

import os

from hawkeye_backend.config import Settings


def test_twilio_is_unconfigured_by_default(monkeypatch):
    """The app must run with no Twilio account at all."""
    # Isolate from any HAWKEYE_* variables in the developer's environment.
    for key in list(os.environ.keys()):
        if key.startswith("HAWKEYE_"):
            monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.twilio_configured is False


def test_twilio_needs_all_four_values(monkeypatch):
    """Three out of four is a misconfiguration, not a partial feature."""
    for key in list(os.environ.keys()):
        if key.startswith("HAWKEYE_"):
            monkeypatch.delenv(key, raising=False)
    s = Settings(
        _env_file=None,
        twilio_account_sid="ACfake",
        twilio_auth_token="tokenfake",
        twilio_from_number="+15550001111",
    )
    assert s.twilio_configured is False


def test_twilio_configured_when_all_four_are_present(monkeypatch):
    for key in list(os.environ.keys()):
        if key.startswith("HAWKEYE_"):
            monkeypatch.delenv(key, raising=False)
    s = Settings(
        _env_file=None,
        twilio_account_sid="ACfake",
        twilio_auth_token="tokenfake",
        twilio_from_number="+15550001111",
        twilio_to_number="+15550002222",
    )
    assert s.twilio_configured is True


def test_the_site_timezone_defaults_to_the_demo_home(monkeypatch):
    for key in list(os.environ.keys()):
        if key.startswith("HAWKEYE_"):
            monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.site_timezone == "America/New_York"
