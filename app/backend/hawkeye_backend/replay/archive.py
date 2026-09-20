"""Where a sealed record goes so it outlives the process that wrote it.

`ReplayRecorder` holds open sessions in memory, which is correct while an
incident is running and useless the moment the hub restarts. A record whose
whole purpose is to be read afterward, by a detective, cannot live only in the
RAM of a process nobody promised to keep running.

## Why this is not `MongoStore`

`store.py` has a `MongoStore` seam covering the entire `Store` protocol -
incidents, transcripts, instructions, verifications, observed devices, the
event ring. Implementing all of it would put MongoDB on the incident path,
between a motion claim and a wrist, and the timing budget in the root CLAUDE.md
has no room for a round trip to Atlas at 0.3s.

This is the narrow version instead. One collection, one document per sealed
record, written exactly once when the call ends. `HAWKEYE_STORE_BACKEND` stays
`memory` and nothing on the hot path changes.

## Three rules it inherits from the rest of the service

1. **Never break an incident.** Every method returns rather than raises. If the
   archive is down the record is still in memory and still served; an exception
   escaping here would land in the event loop carrying the resident's stream.
2. **Never claim to have persisted when it did not.** `save` returns a bool and
   `status()` is surfaced all the way to the console. `store.py` refuses to
   degrade a configured Mongo to memory for this reason and the same rule
   applies here.
3. **Say where a record came from.** A record read back after a restart was
   written by a process that is gone. The console labels it as archived rather
   than presenting it as one this hub is currently recording.

## What the document mapping must not do

Re-derive anything. The entry hashes and the root hash are stored exactly as
written, and `record_from_document` reconstructs rather than recomputes. A round
trip that re-serialized a timestamp differently would produce a record that
fails its own verifier, which is indistinguishable from tampering.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.incident import ReplayRecord

logger = logging.getLogger(__name__)

#: One collection. Named for what it holds rather than for the service, because
#: a person opening Atlas Data Explorer during a demo should not have to guess.
COLLECTION = "replays"

#: Schema tag on every document. If the shape ever changes, a reader can tell
#: which version it is looking at instead of inferring it from which keys exist.
DOCUMENT_VERSION = 1


class ArchiveStatus(BaseModel):
    """Whether the archive is there, and what to say if it is not.

    Surfaced on `GET /v1/replay` and drawn on the console. A silent archive
    failure looks exactly like "no incidents have happened yet", which is the
    same failure mode the Twilio sink's startup log line exists to prevent.
    """

    configured: bool = Field(description="Is an archive backend selected at all?")
    connected: bool = Field(description="Did the last operation actually reach it?")
    backend: str = Field(default="none", description="none | mongodb")
    detail: str = Field(description="Plain English, safe to print on a page.")
    records: int | None = Field(
        default=None, description="Archived record count, or null when unknown."
    )
    checked_at: datetime = Field(default_factory=utc_now)


class ArchivedSummary(BaseModel):
    """One row on the console index, read without loading the record's entries.

    Field for field the same shape as `api.ReplaySummary`, so the console draws
    an archived row and a live row with one code path. Keep them aligned; the
    moment they drift the index needs two renderers.
    """

    incident_id: str
    incident_type: str
    address: str
    opened_at: datetime
    sealed: bool
    sealed_at: datetime | None = None
    seal_reason: str | None = None
    duration_s: float
    entries: int
    frames_dropped: int
    verifications: int
    discarded: int
    root_hash: str | None = None


class ArchivedRecord(BaseModel):
    """A record read back out of the archive, with its cheap summary alongside."""

    incident_id: str
    summary: ArchivedSummary
    record: ReplayRecord
    archived_at: datetime | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArchivedRecord:
        return cls(
            incident_id=doc["_id"],
            summary=ArchivedSummary.model_validate(doc["summary"]),
            record=record_from_document(doc),
            archived_at=doc.get("archived_at"),
        )


# --------------------------------------------------------------------- mapping


def to_document(
    record: ReplayRecord,
    *,
    incident_type: str,
    opened_at: datetime | None = None,
    frames_dropped: int = 0,
    seal_reason: str | None = None,
    archived_at: datetime | None = None,
) -> dict[str, Any]:
    """The BSON document for one sealed record.

    Keyed by `incident_id` as `_id`, so re-archiving the same incident replaces
    rather than duplicates. Two rows for one incident is a forked record, and a
    forked record is worse than a missing one because it has to be adjudicated.

    The summary is denormalized deliberately. The index draws a list of rows and
    a record holds a few hundred frames; deriving the summary at read time would
    deserialize thousands of entries to print ten lines.
    """
    body = record.model_dump(mode="json")
    first = record.entries[0].at if record.entries else utc_now()
    opened = opened_at or first
    end = record.sealed_at or utc_now()
    discarded = sum(1 for v in record.verifications if v.decision.value == "DISCARDED")

    summary = ArchivedSummary(
        incident_id=record.incident_id,
        incident_type=incident_type,
        address=record.site_address,
        opened_at=opened,
        sealed=record.sealed,
        sealed_at=record.sealed_at,
        seal_reason=seal_reason,
        duration_s=round((end - opened).total_seconds(), 2),
        entries=len(record.entries),
        frames_dropped=frames_dropped,
        verifications=len(record.verifications),
        discarded=discarded,
        root_hash=record.root_hash,
    )

    return {
        "_id": record.incident_id,
        "schema_version": DOCUMENT_VERSION,
        "archived_at": archived_at or utc_now(),
        "summary": summary.model_dump(mode="json"),
        "record": body,
    }


def record_from_document(doc: dict[str, Any]) -> ReplayRecord:
    """Rebuild the record exactly as it was written.

    Reconstructs; never recomputes. The hashes in the document are the record's
    own claim about itself, and recomputing them here would mean the archive
    could never disagree with the archive, which is the one thing a verifier
    needs it to be able to do.
    """
    return ReplayRecord.model_validate(doc["record"])


def condense_driver_error(exc: BaseException, limit: int = 140) -> str:
    """One readable clause out of a driver error written for a log file.

    pymongo's `ServerSelectionTimeoutError` stringifies to roughly two thousand
    characters: the same TLS alert once per replica set member, then a full
    `TopologyDescription` with a nested `ServerDescription` for each. That is
    the right amount of detail for a log and the wrong amount for a status
    banner on a page a judge is looking at.

    Keeps the first clause, which is the part that names the actual failure -
    an SSL handshake alert and an authentication failure are different problems
    with different fixes, and whoever reads the banner is who has to tell them
    apart.
    """
    text = " ".join(str(exc).split())
    if not text:
        return exc.__class__.__name__

    # The topology dump is appended after the per-host errors; everything from
    # there on is machine detail with no instruction in it.
    for marker in (", Topology Description:", " Topology Description:"):
        head, sep, _ = text.partition(marker)
        if sep:
            text = head
            break

    # Repeated per-host clauses say one thing three times. Keep the first.
    first = text.split(",SSL handshake failed")[0]
    first = first.split(", Timeout:")[0].strip().rstrip(",")

    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "\u2026"
    return first or exc.__class__.__name__


def explain_driver_error(exc: BaseException) -> str:
    """What went wrong, in words the person who can fix it will recognise.

    The banner this feeds is on a page a judge may be reading, and the reader
    has to know what to do next. `TLSV1_ALERT_INTERNAL_ERROR` names the symptom
    exactly and tells them nothing.

    Two cases are worth recognising by name because they are the two that
    happen, and because they have completely different fixes:

    - **Atlas sends a TLS internal-error alert when the client IP is not on the
      project access list.** The handshake fails before authentication, so it
      looks like a certificate problem and is not one.
    - **Bad credentials** come back as an auth failure, which is a different
      page in a different part of the Atlas console.

    Anything unrecognised falls through to the driver's own first clause rather
    than to a generic apology, because a message that swallows an unknown error
    is worse than one that quotes it.
    """
    text = str(exc)
    lowered = text.lower()

    if "tlsv1_alert_internal_error" in lowered or "ssl handshake failed" in lowered:
        return (
            "the cluster refused the TLS handshake, which on Atlas almost always "
            "means this machine's IP is not on the project's IP access list"
        )
    if "authentication failed" in lowered or "bad auth" in lowered:
        return "the cluster rejected the credentials in the connection string"
    if "name or service not known" in lowered or "nodename nor servname" in lowered:
        return "the cluster hostname did not resolve"
    return condense_driver_error(exc)


# -------------------------------------------------------------------- protocol


@runtime_checkable
class ReplayArchive(Protocol):
    """Durable home for sealed records. Every method fails soft."""

    async def save(self, record: ReplayRecord, *, incident_type: str, **meta: Any) -> bool: ...

    async def get(self, incident_id: str) -> ReplayRecord | None: ...

    async def summaries(self, limit: int = 100) -> list[ArchivedSummary]: ...

    async def status(self) -> ArchiveStatus: ...

    async def close(self) -> None: ...


class NullArchive:
    """No archive configured. The default, and the hackathon path.

    Does nothing and says it does nothing. It does not pretend a save succeeded,
    because the console prints the difference and a judge may ask.
    """

    async def save(self, record: ReplayRecord, *, incident_type: str, **meta: Any) -> bool:
        return False

    async def get(self, incident_id: str) -> ReplayRecord | None:
        return None

    async def summaries(self, limit: int = 100) -> list[ArchivedSummary]:
        return []

    async def status(self) -> ArchiveStatus:
        return ArchiveStatus(
            configured=False,
            connected=False,
            backend="none",
            detail=(
                "Replay archive is not configured. Sealed records live in this "
                "process only and are lost on restart. Set HAWKEYE_REPLAY_ARCHIVE="
                "mongodb and HAWKEYE_MONGODB_URI to persist them."
            ),
            records=None,
        )

    async def close(self) -> None:
        return None


def _ca_bundle() -> str | None:
    """Path to a CA bundle, or None to let the system trust store decide.

    A python.org Python on macOS ships with no system root certificates, so a
    TLS connection to Atlas fails with `CERTIFICATE_VERIFY_FAILED: unable to get
    local issuer certificate` until someone runs Apple's
    "Install Certificates.command". The message names the symptom and reads like
    a broken cluster, and every teammate on a Mac hits it.

    certifi is already installed as a transitive dependency of httpx, so
    pointing the driver at it removes the problem rather than documenting it.
    Kept as a module-level function so the missing-certifi path is testable.
    """
    try:
        import certifi
    except ImportError:
        return None
    return certifi.where()


class MongoReplayArchive:
    """MongoDB Atlas, holding one document per sealed record.

    Every method catches broadly and returns a falsy value. That is usually a
    smell and here it is the requirement: this runs on the incident path, at the
    moment a 911 call ends, and the record is already safe in memory. Losing the
    archive must cost the archive and nothing else.

    The failure this is actually written for is not a wrong password. It is a
    reachable cluster with correct credentials that refuses the TLS handshake
    because the machine's IP is not on the Atlas project access list - which
    presents as `ServerSelectionTimeoutError` several seconds after a call that
    looked fine. Hence `serverSelectionTimeoutMS` well under the time a person
    will wait for the console to draw.
    """

    #: Fail fast rather than hang the index behind a dead cluster. The driver
    #: default is 30s, which on the console is a page that never draws.
    SERVER_SELECTION_TIMEOUT_MS = 3000

    @classmethod
    def client_kwargs(cls) -> dict[str, Any]:
        """Everything the driver is constructed with. Exposed so it is testable."""
        kwargs: dict[str, Any] = {"serverSelectionTimeoutMS": cls.SERVER_SELECTION_TIMEOUT_MS}
        ca = _ca_bundle()
        if ca is not None:
            # Harmless on a plain `mongodb://` connection with TLS off: the
            # driver only consults it once TLS is actually negotiated.
            kwargs["tlsCAFile"] = ca
        return kwargs

    def __init__(self, uri: str, database: str) -> None:
        # Imported here, not at module scope: motor is an optional dependency
        # and a hub with no archive configured must import and run without it.
        from motor.motor_asyncio import AsyncIOMotorClient

        self._uri = uri
        self._client = AsyncIOMotorClient(uri, **self.client_kwargs())
        self._collection = self._client[database][COLLECTION]

    @classmethod
    def for_collection(cls, collection: Any, *, uri: str = "") -> MongoReplayArchive:
        """Build one around an existing collection. Tests, and nothing else.

        There is no driver here to stand up and no cluster to reach, so this
        skips __init__ entirely rather than adding a branch to it that only a
        test ever takes.
        """
        archive = cls.__new__(cls)
        archive._uri = uri
        archive._client = None
        archive._collection = collection
        return archive

    async def save(self, record: ReplayRecord, *, incident_type: str, **meta: Any) -> bool:
        doc = to_document(record, incident_type=incident_type, **meta)
        try:
            await self._collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as exc:
            # Not .exception(): a dead cluster during a rehearsal would print a
            # driver traceback per incident, and the fact worth reading is the
            # one line saying the record is memory-only.
            logger.error(
                "replay archive: could not persist %s (%s). The record is served "
                "from memory and will be lost on restart.",
                record.incident_id,
                condense_driver_error(exc),
            )
            return False
        logger.info("replay archive: persisted %s (%d entries)", record.incident_id, len(record.entries))
        return True

    async def get(self, incident_id: str) -> ReplayRecord | None:
        try:
            doc = await self._collection.find_one({"_id": incident_id})
        except Exception as exc:
            logger.error(
                "replay archive: read failed for %s (%s)", incident_id, condense_driver_error(exc)
            )
            return None
        if doc is None:
            return None
        try:
            return record_from_document(doc)
        except Exception as exc:
            # A document that will not validate is a schema drift, not an
            # outage, and it must be loud: it means something wrote a shape
            # this code does not understand.
            logger.exception("replay archive: stored record for %s is unreadable (%s)", incident_id, exc)
            return None

    async def summaries(self, limit: int = 100) -> list[ArchivedSummary]:
        """Newest first, and without the entries.

        The projection is the point. A record holds a few hundred frames, the
        index prints one line per record, and pulling the whole record to build
        a list is how a console that felt fine on three records stops loading on
        thirty.
        """
        rows: list[ArchivedSummary] = []
        try:
            cursor = self._collection.find({}, {"summary": 1}).sort("summary.opened_at", -1).limit(limit)
            async for doc in cursor:
                rows.append(ArchivedSummary.model_validate(doc["summary"]))
        except Exception as exc:
            logger.error("replay archive: index read failed (%s)", condense_driver_error(exc))
            return []
        return rows

    async def status(self) -> ArchiveStatus:
        try:
            count = await self._collection.count_documents({})
        except Exception as exc:
            return ArchiveStatus(
                configured=True,
                connected=False,
                backend="mongodb",
                detail=(
                    f"Replay archive is configured but unreachable: "
                    f"{explain_driver_error(exc)}. Sealed records are served from "
                    "memory and will be lost on restart."
                ),
                records=None,
            )
        return ArchiveStatus(
            configured=True,
            connected=True,
            backend="mongodb",
            detail=f"Replay archive connected. {count} sealed record(s) stored.",
            records=count,
        )

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
