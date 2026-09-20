"""The wiring that decides whether Twilio is actually live.

Every piece below this is unit-tested in isolation: the detector, the sinks, the
config flag, the runtime hook. This file tests the seam between them, which is
the one place a mistake would survive the whole suite and show up only in
production as "the banner appears and no text ever arrives" - the same signature
as a half-configured Twilio account, and therefore indistinguishable from it.

The SMS is the only path that reaches a phone that is locked with the app
closed, so a silent break here is the highest-consequence failure in the feature.
"""

from __future__ import annotations

import httpx
import pytest

from hawkeye_backend.config import Settings
from hawkeye_backend.main import build_runtime
from hawkeye_backend.notices import StreamSink, TwilioSink


def configured() -> Settings:
    return Settings(
        _env_file=None,
        mode="simulated",
        twilio_account_sid="ACfake",
        twilio_auth_token="tokenfake",
        twilio_from_number="+15550001111",
        twilio_to_number="+15550002222",
    )


def unconfigured(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for var in (
        "HAWKEYE_TWILIO_ACCOUNT_SID",
        "HAWKEYE_TWILIO_AUTH_TOKEN",
        "HAWKEYE_TWILIO_FROM_NUMBER",
        "HAWKEYE_TWILIO_TO_NUMBER",
    ):
        monkeypatch.delenv(var, raising=False)
    return Settings(_env_file=None, mode="simulated")


def test_configured_twilio_reaches_the_runtime_as_a_sink():
    """The whole point of the feature, wired end to end at the seam."""
    runtime = build_runtime(configured())

    assert any(isinstance(s, TwilioSink) for s in runtime.notice_sinks)


def test_the_stream_sink_is_present_with_no_twilio_at_all(monkeypatch):
    """The in-app banner must never depend on Twilio being configured."""
    runtime = build_runtime(unconfigured(monkeypatch))

    assert any(isinstance(s, StreamSink) for s in runtime.notice_sinks)
    assert not any(isinstance(s, TwilioSink) for s in runtime.notice_sinks)


def test_the_secret_is_unwrapped_before_it_reaches_twilio():
    """`auth_token` is a SecretStr on Settings and a str on the wire.

    Passing the SecretStr object through unwrapped would send the literal
    "**********" to Twilio as the password, which authenticates as nothing and
    fails only at send time, long after startup logged "sms sink enabled".
    """
    runtime = build_runtime(configured())
    sink = next(s for s in runtime.notice_sinks if isinstance(s, TwilioSink))

    _, token = sink._auth
    assert token == "tokenfake"
    assert "*" not in token


def test_the_detector_is_built_from_the_configured_hold():
    """A hold read from the wrong setting would be invisible until demo day."""
    settings = configured()
    settings.notice_hold_s = 11.0
    settings.notice_forget_after_s = 4321.0

    runtime = build_runtime(settings)

    assert runtime.detector.hold_s == 11.0
    assert runtime.detector.forget_after_s == 4321.0


async def test_stopping_the_runtime_closes_a_client_the_sink_owns():
    """The runtime owns the sinks, so it is what closes them."""
    runtime = build_runtime(configured())
    sink = next(s for s in runtime.notice_sinks if isinstance(s, TwilioSink))
    assert sink._owns_client, "the sink built its own client, so it must close it"

    await runtime.stop()

    assert sink._client.is_closed


async def test_stopping_the_runtime_leaves_an_injected_client_open():
    """A client handed in from outside belongs to whoever handed it in."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201)))
    runtime = build_runtime(configured())
    runtime.notice_sinks.append(
        TwilioSink(
            account_sid="ACfake",
            auth_token="tokenfake",
            from_number="+15550001111",
            to_number="+15550002222",
            timezone="America/New_York",
            client=client,
        )
    )

    await runtime.stop()

    assert not client.is_closed
    await client.aclose()
