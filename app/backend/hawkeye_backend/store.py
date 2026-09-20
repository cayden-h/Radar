"""State storage behind a protocol.

No database is required for the hackathon path. `InMemoryStore` is the whole
implementation. `MongoStore` is the seam: swapping MongoDB Atlas in later is one
class and one config value, and nothing above this file changes.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import datetime
from typing import Protocol, runtime_checkable

from hawkeye_backend.models.events import Envelope
from hawkeye_backend.models.household import HouseholdMember, ObservedDevice
from hawkeye_backend.models.incident import (
    ContextNote,
    Incident,
    Instruction,
    ReplayEntry,
    ReplayRecord,
    TranscriptLine,
)
from hawkeye_backend.models.state import InteriorState
from hawkeye_backend.models.verification import VerificationResult


@runtime_checkable
class Store(Protocol):
    """Everything the API layer needs to persist.

    Deliberately narrow. Every method is async so a network-backed
    implementation is a drop-in.
    """

    async def put_state(self, state: InteriorState) -> None: ...

    async def get_state(self) -> InteriorState | None: ...

    async def put_incident(self, incident: Incident) -> None: ...

    async def get_incident(self, incident_id: str) -> Incident | None: ...

    async def list_incidents(self) -> list[Incident]: ...

    async def get_active_incident(self) -> Incident | None: ...

    async def append_transcript(self, line: TranscriptLine) -> None: ...

    async def list_transcript(self, incident_id: str) -> list[TranscriptLine]: ...

    async def append_instruction(self, instruction: Instruction) -> None: ...

    async def list_instructions(self, incident_id: str) -> list[Instruction]: ...

    async def append_verification(self, result: VerificationResult) -> None: ...

    async def list_verifications(self, incident_id: str | None) -> list[VerificationResult]: ...

    async def append_context(self, note: ContextNote) -> None: ...

    async def list_context(self, incident_id: str) -> list[ContextNote]: ...

    async def append_event(self, envelope: Envelope) -> None: ...

    async def recent_events(self, limit: int) -> list[Envelope]: ...

    async def next_seq(self) -> int: ...

    async def put_member(self, member: HouseholdMember) -> None: ...

    async def list_members(self) -> list[HouseholdMember]: ...

    async def delete_member(self, member_id: str) -> bool: ...

    async def put_observed_device(self, device: ObservedDevice) -> None: ...

    async def list_observed_devices(self) -> list[ObservedDevice]: ...


def _hash_entry(payload: dict[str, object], prev_hash: str | None) -> str:
    """SHA-256 over canonical JSON plus the previous hash. A tamper-evident chain.

    This is a local hash chain, not a SCITT receipt. It makes reordering or
    editing an entry detectable without claiming the record has been sealed into
    a transparency log. See the TODO(ans) on ReplayRecord.scitt_receipt.
    """
    blob = json.dumps(
        {"prev": prev_hash, "entry": payload}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class InMemoryStore:
    """The hackathon path. Nothing persists across a restart, and that is fine.

    Root CLAUDE.md: prefer the boring, working path over the elegant, unproven one.
    """

    def __init__(self, event_buffer: int = 500) -> None:
        self._state: InteriorState | None = None
        self._incidents: dict[str, Incident] = {}
        self._incident_order: list[str] = []
        self._transcripts: dict[str, list[TranscriptLine]] = {}
        self._instructions: dict[str, list[Instruction]] = {}
        self._verifications: dict[str, list[VerificationResult]] = {}
        self._context: dict[str, list[ContextNote]] = {}
        self._events: deque[Envelope] = deque(maxlen=event_buffer)
        self._seq: int = 0
        self._members: dict[str, HouseholdMember] = {}
        self._observed: dict[str, ObservedDevice] = {}

    async def put_state(self, state: InteriorState) -> None:
        self._state = state

    async def get_state(self) -> InteriorState | None:
        return self._state

    async def put_incident(self, incident: Incident) -> None:
        if incident.incident_id not in self._incidents:
            self._incident_order.append(incident.incident_id)
        self._incidents[incident.incident_id] = incident

    async def get_incident(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    async def list_incidents(self) -> list[Incident]:
        return [self._incidents[i] for i in self._incident_order]

    async def get_active_incident(self) -> Incident | None:
        for incident_id in reversed(self._incident_order):
            incident = self._incidents[incident_id]
            if incident.resolved_at is None:
                return incident
        return None

    async def append_transcript(self, line: TranscriptLine) -> None:
        self._transcripts.setdefault(line.incident_id, []).append(line)

    async def list_transcript(self, incident_id: str) -> list[TranscriptLine]:
        return list(self._transcripts.get(incident_id, []))

    async def append_instruction(self, instruction: Instruction) -> None:
        self._instructions.setdefault(instruction.incident_id, []).append(instruction)

    async def list_instructions(self, incident_id: str) -> list[Instruction]:
        return list(self._instructions.get(incident_id, []))

    async def append_verification(self, result: VerificationResult) -> None:
        key = result.incident_id or "_unattached"
        self._verifications.setdefault(key, []).append(result)

    async def list_verifications(self, incident_id: str | None) -> list[VerificationResult]:
        if incident_id is None:
            out: list[VerificationResult] = []
            for group in self._verifications.values():
                out.extend(group)
            return sorted(out, key=lambda r: r.checked_at)
        return list(self._verifications.get(incident_id, []))

    async def append_context(self, note: ContextNote) -> None:
        self._context.setdefault(note.incident_id, []).append(note)

    async def list_context(self, incident_id: str) -> list[ContextNote]:
        return list(self._context.get(incident_id, []))

    async def append_event(self, envelope: Envelope) -> None:
        self._events.append(envelope)

    async def recent_events(self, limit: int) -> list[Envelope]:
        events = list(self._events)
        return events[-limit:]

    async def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def put_member(self, member: HouseholdMember) -> None:
        # dict preserves insertion order and replaces in place, so an update
        # does not reshuffle the Household list under the reader.
        self._members[member.member_id] = member

    async def list_members(self) -> list[HouseholdMember]:
        return list(self._members.values())

    async def delete_member(self, member_id: str) -> bool:
        return self._members.pop(member_id, None) is not None

    async def put_observed_device(self, device: ObservedDevice) -> None:
        # Keyed by hash rather than by device_id: the same phone seen across two
        # frames is one unclaimed device, and the router may renumber its table.
        existing = self._observed.get(device.identifier_hash)
        if existing is not None:
            return
        self._observed[device.identifier_hash] = device

    async def list_observed_devices(self) -> list[ObservedDevice]:
        return list(self._observed.values())

    async def build_replay(
        self, incident_id: str, caller_ansname: str, site_address: str
    ) -> ReplayRecord | None:
        """Assemble the post-incident record from what this store holds.

        In live mode agents/replay owns this and the hub proxies it. In simulated
        mode the hub builds it from its own buffer so the demo has something real
        to show. Either way the hash chain is computed the same way.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        rows: list[tuple[str, str, dict[str, object]]] = []
        rows.append(
            (
                "incident",
                f"{incident.incident_type.value} raised by {incident.raised_by.value}",
                incident.model_dump(mode="json"),
            )
        )
        for note in self._context.get(incident_id, []):
            rows.append(("context", f"resident: {note.text}", note.model_dump(mode="json")))
        for result in self._verifications.get(incident_id, []):
            rows.append(
                (
                    "verification",
                    f"{result.decision.value}: {result.claim.statement} ({result.agent.ansname})",
                    result.model_dump(mode="json"),
                )
            )
        for line in self._transcripts.get(incident_id, []):
            rows.append(("transcript", f"{line.speaker.value}: {line.text}", line.model_dump(mode="json")))
        for instruction in self._instructions.get(incident_id, []):
            rows.append(
                ("instruction", instruction.text, instruction.model_dump(mode="json"))
            )

        def _sort_key(row: tuple[str, str, dict[str, object]]) -> str:
            detail = row[2]
            for key in ("at", "checked_at", "raised_at"):
                value = detail.get(key)
                if isinstance(value, str):
                    return value
            return ""

        rows.sort(key=_sort_key)

        entries: list[ReplayEntry] = []
        prev_hash: str | None = None
        for seq, row in enumerate(rows, start=1):
            kind, summary, detail = row
            stamp = _sort_key(row)
            try:
                at = datetime.fromisoformat(stamp) if stamp else incident.raised_at
            except ValueError:
                at = incident.raised_at
            body: dict[str, object] = {"seq": seq, "kind": kind, "summary": summary, "detail": detail}
            entry_hash = _hash_entry(body, prev_hash)
            entries.append(
                ReplayEntry(
                    seq=seq,
                    at=at,
                    kind=kind,
                    summary=summary,
                    detail=detail,
                    entry_hash=entry_hash,
                    prev_hash=prev_hash,
                )
            )
            prev_hash = entry_hash

        return ReplayRecord(
            incident_id=incident_id,
            sealed=incident.resolved_at is not None,
            sealed_at=incident.resolved_at,
            caller_ansname=caller_ansname,
            site_address=site_address,
            entries=entries,
            verifications=self._verifications.get(incident_id, []),
            root_hash=prev_hash,
            scitt_receipt=None,
        )


class MongoStore:
    """MongoDB Atlas seam. Not implemented.

    MongoDB Atlas is a listed sponsor track. **That track is already served, by
    `replay/archive.py`, and this is still not the way to serve it.**

    The archive persists a sealed record: one document, written once, when a 911
    call ends, read afterwards by the console at /replay. This class would put
    MongoDB on the incident path instead, between a motion claim and a wrist,
    and the timing budget in the root CLAUDE.md has no room for a round trip to
    Atlas at 0.3s. `HAWKEYE_STORE_BACKEND` should stay `memory` even once a
    cluster is reachable.

    If it is ever implemented anyway: every method above maps onto one
    collection, keyed by incident_id, with `events` as a capped collection.
    Nothing above store.py changes.

    Deliberately raises rather than silently degrading to memory, because a
    service that claims to be persisting and is not is exactly the kind of quiet
    lie this project is built against.
    """

    def __init__(self, uri: str, database: str) -> None:
        self._uri = uri
        self._database = database
        raise NotImplementedError(
            "MongoStore is a seam, not an implementation. Set HAWKEYE_STORE_BACKEND=memory; "
            "for MongoDB persistence of sealed records use HAWKEYE_REPLAY_ARCHIVE=mongodb, "
            "which is implemented. "
            "To implement: add motor>=3.6 to pyproject, map each Store method onto a collection "
            "keyed by incident_id, and make `events` capped at the same size as the in-memory buffer."
        )

    async def put_member(self, member: HouseholdMember) -> None: ...

    async def list_members(self) -> list[HouseholdMember]: ...

    async def delete_member(self, member_id: str) -> bool: ...

    async def put_observed_device(self, device: ObservedDevice) -> None: ...

    async def list_observed_devices(self) -> list[ObservedDevice]: ...


def build_store(backend: str, mongodb_uri: str, mongodb_database: str) -> Store:
    """Construct the configured store. The single swap point."""
    if backend == "memory":
        return InMemoryStore()
    if backend == "mongodb":
        return MongoStore(mongodb_uri, mongodb_database)  # type: ignore[return-value]
    raise ValueError(f"unknown store backend: {backend}")
