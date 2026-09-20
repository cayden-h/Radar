import pytest
from hawkeye_backend.config import Settings, reset_settings


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


def test_twilio_voice_is_unconfigured_by_default():
    s = Settings()
    assert s.twilio_voice_configured is False


def test_twilio_voice_configured_needs_every_field(monkeypatch):
    monkeypatch.setenv("HAWKEYE_TWILIO_ACCOUNT_SID", "ACxxxx")
    monkeypatch.setenv("HAWKEYE_TWILIO_AUTH_TOKEN", "token123")
    monkeypatch.setenv("HAWKEYE_TWILIO_VOICE_NUMBER", "+15550001111")
    monkeypatch.setenv("HAWKEYE_TWILIO_CONFERENCE_APP_SID", "APxxxx")
    monkeypatch.setenv("HAWKEYE_MOCK_911_NUMBER", "+15550002222")
    monkeypatch.setenv("HAWKEYE_ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setenv("HAWKEYE_ELEVENLABS_VOICE_ID", "voice123")
    monkeypatch.setenv("HAWKEYE_PUBLIC_BASE_URL", "https://example.ngrok-free.app")
    s = Settings()
    assert s.twilio_voice_configured is True


def test_missing_one_field_reads_as_unconfigured(monkeypatch):
    monkeypatch.setenv("HAWKEYE_TWILIO_VOICE_NUMBER", "+15550001111")
    # everything else left unset
    s = Settings()
    assert s.twilio_voice_configured is False
