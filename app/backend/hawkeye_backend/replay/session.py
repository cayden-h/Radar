"""One incident's record, written as it happens.

Append-only, hash-chained, sealed once. This is the thing the website reads and
the thing a detective exports.

The record that existed before this module was assembled at read time out of
whatever the store happened to still be holding. That is a reconstruction, and a
reconstruction cannot support the sentence the project rests on: an investigator
can check this afterward. A reconstruction only proves what the store contains
now. A chain written entry by entry as events occurred, and frozen when the call
ended, proves the order things happened in and that nothing was edited since.

What it still does not prove is that whoever holds it wrote it honestly. That is
the transparency log's job and the log is not wired. See ReplayRecord.scitt_receipt.
"""

from __future__ import annotations

from datetime import datetime

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.incident import (
    Incident,
    ReplayEntry,
    ReplayRecord,
)
from hawkeye_backend.models.verification import VerificationResult
from hawkeye_backend.replay.chain import entry_hash, verify_entries


class RecordSealed(RuntimeError):
    """Raised on an attempt to append to a sealed record.

    Deliberately an exception rather than a silent no-op. A record that grew
    after it was sealed is worse than no record at all, and a caller that tries
    has a bug that must be visible.
    """


class ReplaySession:
    """The recorder for one incident. Opened on a tap, sealed when the call ends."""

    def __init__(self, incident: Incident, caller_ansname: str) -> None:
        self.incident_id = incident.incident_id
        self.site_address = incident.address
        self.caller_ansname = caller_ansname
        self.opened_at: datetime = utc_now()
        self.sealed_at: datetime | None = None
        self.seal_reason: str | None = None

        self._entries: list[ReplayEntry] = []
        self._verifications: list[VerificationResult] = []
        # Frames are throttled, so the recorder needs to know when the last one
        # landed and what it showed. Held here rather than in the recorder so a
        # session is self-contained and testable on its own.
        self.last_frame_at: datetime | None = None
        self.last_presence_signature: str | None = None
        self.frames_dropped = 0
        self.frames_suspended = False

    # --------------------------------------------------------------- properties

    @property
    def sealed(self) -> bool:
        return self.sealed_at is not None

    @property
    def entries(self) -> tuple[ReplayEntry, ...]:
        return tuple(self._entries)

    @property
    def root_hash(self) -> str | None:
        return self._entries[-1].entry_hash if self._entries else None

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------ writing

    def append(
        self,
        *,
        kind: str,
        summary: str,
        detail: dict[str, object] | None = None,
        actor: str | None = None,
        at: datetime | None = None,
    ) -> ReplayEntry:
        """Chain one entry. There is no update and no delete, by construction."""
        if self.sealed:
            raise RecordSealed(
                f"{self.incident_id} was sealed at {self.sealed_at.isoformat()}; "
                f"refusing to append a {kind} entry"
            )
        prev = self.root_hash
        seq = len(self._entries) + 1
        stamp = at or utc_now()
        body: dict[str, object] = {
            "seq": seq,
            "kind": kind,
            "summary": summary,
            "detail": detail or {},
        }
        # `actor` is chained only when present, so an entry written without one
        # hashes identically to the pre-actor format the store already produces.
        if actor is not None:
            body["actor"] = actor
        entry = ReplayEntry(
            seq=seq,
            at=stamp,
            kind=kind,
            actor=actor,
            summary=summary,
            detail=detail or {},
            entry_hash=entry_hash(body, prev),
            prev_hash=prev,
        )
        self._entries.append(entry)
        return entry

    def append_verification(self, result: VerificationResult) -> ReplayEntry:
        """A verification, accepted or discarded, kept with equal weight.

        The discard log is not an error channel. "It tells you what it discarded"
        is the sentence that carries the submission, and a record holding only
        what was accepted cannot support it.
        """
        self._verifications.append(result)
        return self.append(
            kind="verification",
            actor=result.agent.ansname,
            summary=f"{result.decision.value}: {result.claim.statement}",
            detail=result.model_dump(mode="json"),
            at=result.checked_at,
        )

    def seal(self, reason: str, at: datetime | None = None) -> ReplayEntry:
        """Write the closing entry and freeze the chain. Idempotent by refusal."""
        if self.sealed:
            raise RecordSealed(f"{self.incident_id} is already sealed")
        stamp = at or utc_now()
        entry = self.append(
            kind="lifecycle",
            actor="hub",
            summary=f"Record sealed: {reason}",
            detail={
                "reason": reason,
                "entries": len(self._entries) + 1,
                "frames_dropped": self.frames_dropped,
                "duration_s": round((stamp - self.opened_at).total_seconds(), 2),
                # Stated on the record itself, not only in a README, because the
                # record travels and the README may not.
                "transparency_receipt": None,
                "seal_note": (
                    "Local hash chain only. Tamper-evident to whoever holds this record. "
                    "NOT submitted to a SCITT transparency log, so it is not yet verifiable "
                    "by a third party who does not already hold it."
                ),
            },
            at=stamp,
        )
        self.sealed_at = stamp
        self.seal_reason = reason
        return entry

    # ------------------------------------------------------------------ reading

    def verify(self) -> tuple[bool, str, int | None]:
        """Recompute every link. Returns (intact, detail, first_failed_seq).

        What an investigator runs, and what the website runs again in the browser
        so the answer does not depend on the server being honest about itself.

        Delegates to `chain.verify_entries` so a record read back out of the
        archive is checked by the same code as a live one.
        """
        return verify_entries(self._entries)

    def to_record(self, since_seq: int = 0) -> ReplayRecord:
        """The API shape. `since_seq` trims the head for the website's 1 Hz tail."""
        return ReplayRecord(
            incident_id=self.incident_id,
            sealed=self.sealed,
            sealed_at=self.sealed_at,
            caller_ansname=self.caller_ansname,
            site_address=self.site_address,
            entries=[e for e in self._entries if e.seq > since_seq],
            verifications=list(self._verifications),
            root_hash=self.root_hash,
            scitt_receipt=None,
        )
