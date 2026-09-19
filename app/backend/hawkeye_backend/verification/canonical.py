"""RFC 8785 JSON Canonicalization Scheme.

`canonicalization_probe` (battery #13) requests two authority-signed mandates
where `max_amount` serializes differently, float versus int, and checks whether
the implementation handles them consistently. It is the probe most likely to bite
us as an ordinary bug rather than as an attack: five agents, and any two of them
serializing the same value differently produce signature mismatches that look
exactly like tampering.

So canonicalization is decided once, here, and every agent uses this function.
There is no second implementation anywhere in the codebase.

The rule that matters for the probe: JSON has one number type. `1` and `1.0` are
the same value and MUST canonicalize to the same bytes, or a claim signed by an
agent that emitted `1.0` fails verification at an agent that reads `1`.
"""

from __future__ import annotations

import json
from typing import Any


def _canonical_number(value: int | float) -> int | float:
    """Collapse a float that is exactly an integer onto that integer.

    RFC 8785 serializes numbers via ECMAScript `Number::toString`, under which
    `1.0` prints as `1`. Python's `json` would emit `1.0`, so the two would sign
    differently. This is exactly what battery #13 probes.
    """
    if isinstance(value, bool):  # bool is an int subclass; keep it a bool
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("NaN and Infinity are not representable in canonical JSON")
        if value.is_integer():
            return int(value)
    return value


def _normalize(value: Any) -> Any:
    """Recursively apply the number rule. Key ordering is left to `sort_keys`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _canonical_number(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def canonicalize(value: Any) -> bytes:
    """Canonical UTF-8 bytes for `value`. The only thing anything ever signs.

    Sorted keys, no insignificant whitespace, integer-valued floats collapsed.
    """
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
