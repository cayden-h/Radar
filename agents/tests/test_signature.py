from __future__ import annotations

import base64
import hashlib
import hmac

from agents.caller.transport.signature import validate_twilio_signature

AUTH_TOKEN = "test_auth_token"
URL = "https://example.ngrok-free.app/twilio/voice"


def _sign(url: str, params: dict[str, str]) -> str:
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def test_a_correctly_signed_request_validates():
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    sig = _sign(URL, params)
    assert validate_twilio_signature(AUTH_TOKEN, URL, params, sig) is True


def test_a_forged_signature_is_rejected():
    """This is the entire front door. A webhook that skips this check lets
    anyone who finds the ngrok URL inject fake operator speech into a live
    incident."""
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    assert validate_twilio_signature(AUTH_TOKEN, URL, params, "not-a-real-signature") is False


def test_tampering_with_one_param_after_signing_is_rejected():
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    sig = _sign(URL, params)
    tampered = {"CallSid": "CAxxxx", "From": "+15559998888"}
    assert validate_twilio_signature(AUTH_TOKEN, URL, tampered, sig) is False
