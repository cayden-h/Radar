"""Who belongs in this house.

Standalone: no FastAPI imports and no hub imports, the way `verification/` is
standalone, so this moves into `agents/intruder` as an import change rather than
a rewrite.
"""

from hawkeye_backend.household.identity import fingerprint, hash_identifier

__all__ = ["fingerprint", "hash_identifier"]
