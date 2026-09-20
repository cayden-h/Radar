"""The incident recorder. What happened, in order, on whose authority.

Movement through the house, sensing claims, verification results, discards, what
the caller told the operator, what the operator said back, what guidance the
resident received. Hash-chained here, and sealed into the SCITT transparency log
where entries cannot be altered after the fact.

Two audiences, and they want different things from the same record:

- **Detectives.** After a burglary, a tamper-evident record of where the
  unaccounted presence moved through the house and when is genuinely useful
  evidence.
- **Accountability for the system itself.** If the agents got something wrong,
  the record shows which agent said what and on whose authority.

This is where non-repudiation lives. The operator cannot verify us live; an
investigator can verify the record afterward, and **swatting investigations are
entirely post-hoc.** The FBI only began systematically tracking swatting in May
2023 via the NCOP database, precisely because these calls could not be
attributed. That is the gap this agent speaks to.

**Do not claim this prevents a malicious call.** It makes one attributable,
which beats tracing a spoofed number. State it that narrowly; a judge who has
heard the swatting pitch before will check.

The hash chain is local and is not the seal. It makes tampering detectable by
anyone holding the record, which is worth having on its own, and it is what gets
submitted to the log. The log is what makes it tamper-*evident to a third party*,
and that step is not wired yet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.replay.chain import canonical
from hawkeye_backend.verification.envelope import Severity

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion

#: The first link. A chain needs somewhere to start, and a fixed constant means
#: two independent replays of the same incident produce the same root, which is
#: what makes a record comparable rather than merely internally consistent.
GENESIS = "0" * 64


@dataclass(frozen=True)
class Entry:
    """One sealed line in the record."""

    sequence: int
    at: datetime
    kind: str
    """`claim`, `discard`, `utterance`, `operator`, `instruction`, `lifecycle`."""

    actor: str
    """The agent or person responsible. `agents/people`, `911-operator`, `resident`."""

    summary: str
    detail: dict[str, object]
    previous_hash: str
    entry_hash: str

    def body(self) -> dict[str, object]:
        """Exactly what the hash covers. Everything except the hash itself."""
        return {
            "sequence": self.sequence,
            "at": self.at.isoformat(),
            "kind": self.kind,
            "actor": self.actor,
            "summary": self.summary,
            "detail": self.detail,
            "previous_hash": self.previous_hash,
        }


def _hash(body: dict[str, object]) -> str:
    """SHA-256 over the canonical serialization of one entry body.

    The serializer is `hawkeye_backend.replay.chain.canonical`, shared with the
    hub's recorder and with the `verify.py` shipped in a police export, so that
    sort order and separators cannot drift between them. Two processes
    serializing the same entry differently produce a chain that looks tampered
    with, and that is far likelier to bite as an ordinary bug than as an attack.

    **The body shape here is deliberately not the hub's.** This agent puts
    `previous_hash` inside the hashed body; the hub wraps the body as
    `{"prev": ..., "entry": ...}`. Both are chains and both detect the same
    edits, but a record written by one does not verify under the other, and
    nothing is expected to move between them: this agent's chain is what a live
    mesh produces, the hub's is what the app and the export already speak.
    Converge them only alongside a migration, never quietly.
    """
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


class ReplayAgent(Agent):
    """Append-only, hash-chained, and honest about what it does not yet do."""

    interval_s = 5.0

    def __init__(self) -> None:
        super().__init__(identity("replay"))
        self._entries: list[Entry] = []
        self._traceparent: str | None = None

    # ------------------------------------------------------------------ the job

    def tick(self) -> AgentObservation:
        provenance = Provenance(
            source=Source.AGENT_INFERENCE,
            producer=self.identity.name,
            ansname=self.identity.ansname,
        )
        return self.observe(
            assertions=(
                Assertion(
                    field="replay.entry",
                    value=str(len(self._entries)),
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=f"{len(self._entries)} entries recorded and chained.",
                    provenance=provenance,
                ),
                Assertion(
                    field="replay.seal",
                    value=self.head,
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=(
                        "Head of the local hash chain. Tampering with any earlier entry "
                        "changes this value. NOT YET a transparency-log receipt: submission "
                        "to SCITT is what makes the record verifiable by someone who does not "
                        "already have it, and that hop is not wired."
                    ),
                    provenance=provenance,
                ),
            ),
            note=f"{len(self._entries)} entries",
        )

    # ----------------------------------------------------------------- record

    def open_incident(self, incident_id: str, traceparent: str) -> Entry:
        """Start a record. The traceparent ties five services into one timeline."""
        self._traceparent = traceparent
        return self.record(
            kind="lifecycle",
            actor="agents/master",
            summary=f"Incident {incident_id} opened.",
            detail={"incident_id": incident_id, "traceparent": traceparent},
        )

    def record(
        self, *, kind: str, actor: str, summary: str, detail: dict[str, object] | None = None
    ) -> Entry:
        """Append one entry. There is no update and no delete, by construction."""
        previous = self._entries[-1].entry_hash if self._entries else GENESIS
        body = {
            "sequence": len(self._entries),
            "at": utc_now().isoformat(),
            "kind": kind,
            "actor": actor,
            "summary": summary,
            "detail": detail or {},
            "previous_hash": previous,
        }
        entry = Entry(
            sequence=body["sequence"],  # type: ignore[arg-type]
            at=datetime.fromisoformat(body["at"]),  # type: ignore[arg-type]
            kind=kind,
            actor=actor,
            summary=summary,
            detail=detail or {},
            previous_hash=previous,
            entry_hash=_hash(body),
        )
        self._entries.append(entry)
        return entry

    def record_verification(self, result: object) -> Entry:
        """A verification result, accepted or discarded, with its reason.

        Discards are recorded with exactly the same weight as acceptances. The
        discard log is not an error channel: "it tells you what it discarded" is
        the sentence that carries the submission, and a record that only keeps
        what was accepted cannot support it.
        """
        decision = getattr(result, "decision", None)
        agent = getattr(result, "agent", None)
        claim = getattr(result, "claim", None)
        return self.record(
            kind="discard" if getattr(decision, "value", "") == "DISCARDED" else "claim",
            actor=getattr(agent, "name", "unknown"),
            summary=getattr(result, "reason", ""),
            detail={
                "decision": getattr(decision, "value", None),
                "field": getattr(claim, "field", None),
                "value": getattr(claim, "value", None),
                "ansname": getattr(agent, "ansname", None),
                "will_be_spoken": getattr(result, "will_be_spoken", None),
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in getattr(result, "checks", [])
                ],
            },
        )

    # ------------------------------------------------------------------ verify

    @property
    def head(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute every link. Returns (intact, detail).

        What an investigator runs. It proves the record has not been altered
        since it was written by whoever holds it - and not, on its own, that
        whoever holds it wrote it honestly. That second property is what the
        transparency log provides and why the seal is not optional.
        """
        previous = GENESIS
        for entry in self._entries:
            if entry.previous_hash != previous:
                return False, f"entry {entry.sequence} does not follow entry {entry.sequence - 1}"
            if _hash(entry.body()) != entry.entry_hash:
                return False, f"entry {entry.sequence} has been altered since it was written"
            previous = entry.entry_hash
        return True, f"{len(self._entries)} entries, chain intact from genesis to {self.head[:12]}"

    def seal(self) -> dict[str, object]:
        """The submission the transparency log would receive.

        Returned rather than sent. Sending it is an ANS hop and the transport is
        not wired; producing the exact payload now means wiring it later is a
        POST and not a redesign.
        """
        return {
            "traceparent": self._traceparent,
            "entries": len(self._entries),
            "head": self.head,
            "algorithm": "sha256-chain",
            # TODO(ans): submit to SCITT and staple the receipt. Until that
            # happens this record is tamper-evident to whoever holds it and to
            # nobody else, and it must be described that way.
            "transparency_receipt": None,
        }
