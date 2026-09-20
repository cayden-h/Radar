"""Who belongs in this house.

Standalone: no FastAPI imports and no hub imports, the way `verification/` is
standalone, so this moves into `agents/intruder` as an import change rather than
a rewrite.
"""

from hawkeye_backend.household.accounting import unaccounted_count
from hawkeye_backend.household.identity import (
    MalformedAddress,
    fingerprint,
    hash_identifier,
)
from hawkeye_backend.household.roster import DeviceAlreadyClaimed, Roster, UnknownDevice

__all__ = [
    "DeviceAlreadyClaimed",
    "MalformedAddress",
    "Roster",
    "UnknownDevice",
    "fingerprint",
    "hash_identifier",
    "unaccounted_count",
]
