"""The incident recorder and its export.

`ReplayRecorder` is wired into `HubRuntime.emit`, the single path every event
takes to reach a phone, so a record is complete by construction. `ReplaySession`
is one incident's hash chain: opened on a human tap, sealed when the 911 call
ends, never edited.

`agents/replay` is the live-mode owner of this record. This package is the hub's
implementation of the same contract, and the two share `chain.py` so their
hashes cannot drift apart.
"""

from hawkeye_backend.replay.chain import GENESIS, canonical, entry_hash
from hawkeye_backend.replay.export import build_export
from hawkeye_backend.replay.recorder import ReplayRecorder
from hawkeye_backend.replay.session import RecordSealed, ReplaySession

__all__ = [
    "GENESIS",
    "RecordSealed",
    "ReplayRecorder",
    "ReplaySession",
    "build_export",
    "canonical",
    "entry_hash",
]
