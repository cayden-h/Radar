"""agents/agents/caller/transport/signature.py

Twilio's request-signing scheme: HMAC-SHA1 over the full request URL plus
every POST param's key and value concatenated in sorted-key order, then
base64-encoded. https://www.twilio.com/docs/usage/security#validating-requests
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def validate_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature_header: str
) -> bool:
    data = url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)
