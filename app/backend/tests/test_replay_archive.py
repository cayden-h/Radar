"""The sealed-record archive: what is written, what comes back, and what is said
when the archive is not there.

These tests never touch a live cluster. The document mapping is a pure function
and is tested as one; the Mongo driver is exercised against a fake collection
that records what it was asked to do. A test that needs Atlas to be reachable is
a test that goes red on demo morning because of someone else's IP allowlist.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.incident import (
    Incident,
    IncidentStatus,
    IncidentType,
    RaisedBy,
)
from hawkeye_backend.replay.archive import (
    ArchivedRecord,
    NullArchive,
    record_from_document,
    to_document,
)
from hawkeye_backend.replay.session import ReplaySession

CALLER = "ans://v1.0.0.caller.hawkeye.example"


def _incident() -> Incident:
    return Incident(
        incident_id="inc-2026-09-19-0001",
        site_id="site-demo-01",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RESOLVED,
        raised_by=RaisedBy.USER,
        address="1872 Ridgeview Lane, Blacksburg VA 24060",
        raised_at=utc_now(),
    )


def _sealed_session() -> ReplaySession:
    session = ReplaySession(_incident(), CALLER)
    session.append(
        kind="lifecycle",
        actor="resident",
        summary="Recording opened",
        detail={"opened_by": "human tap"},
        at=utc_now(),
    )
    session.append(
        kind="transcript",
        actor="911-operator",
        summary="operator: units are two minutes out",
        detail={"text": "units are two minutes out"},
        at=utc_now() + timedelta(seconds=4),
    )
    session.seal("911 call ended, incident RESOLVED")
    return session


# ------------------------------------------------------------------ mapping


def test_document_round_trip_preserves_the_hash_chain():
    """The record that comes back out must hash to what went in.

    This is the whole point of archiving it. A round trip that quietly reordered
    entries or re-serialized a timestamp would produce a record that fails its
    own verifier, which looks exactly like tampering.
    """
    session = _sealed_session()
    original = session.to_record()

    restored = record_from_document(to_document(original, incident_type="burglary"))

    assert restored.root_hash == original.root_hash
    assert [e.entry_hash for e in restored.entries] == [e.entry_hash for e in original.entries]
    assert [e.prev_hash for e in restored.entries] == [e.prev_hash for e in original.entries]


def test_document_is_keyed_by_incident_id_so_a_reseal_replaces_rather_than_duplicates():
    """One incident is one record. Two rows for one incident is a forked record."""
    record = _sealed_session().to_record()
    doc = to_document(record, incident_type="burglary")
    assert doc["_id"] == "inc-2026-09-19-0001"


def test_document_carries_the_summary_so_the_index_need_not_load_every_entry():
    """The console index must stay cheap.

    A record holds a few hundred frames and the index draws a list of rows. If
    the summary were derived at read time, listing ten records would deserialize
    thousands of entries to print ten lines.
    """
    record = _sealed_session().to_record()
    doc = to_document(record, incident_type="burglary")

    assert doc["summary"]["entries"] == 3  # two appended, plus the entry seal() writes
    assert doc["summary"]["sealed"] is True
    assert doc["summary"]["incident_type"] == "burglary"
    assert doc["summary"]["root_hash"] == record.root_hash


def test_an_archived_record_reports_that_it_came_from_the_archive():
    """The console must be able to say where a row came from.

    An in-memory record and a record read back after a restart are not the same
    claim: one was written by the process you are talking to, the other was
    written by a process that is gone. Honesty rule.
    """
    record = _sealed_session().to_record()
    archived = ArchivedRecord.from_document(to_document(record, incident_type="burglary"))

    assert archived.incident_id == "inc-2026-09-19-0001"
    assert archived.summary.entries == 3
    assert archived.record.root_hash == record.root_hash


# ------------------------------------------------------------------ null archive


@pytest.mark.asyncio
async def test_null_archive_reports_unconfigured_rather_than_pretending_to_persist():
    """No URI means no archive, and it must say so rather than silently drop.

    store.py refuses to degrade a configured Mongo to memory for exactly this
    reason. The same rule applies here: a service that claims to be persisting
    and is not is the kind of quiet lie this project is built against.
    """
    archive = NullArchive()
    status = await archive.status()

    assert status.configured is False
    assert status.connected is False
    assert "not configured" in status.detail.lower()


@pytest.mark.asyncio
async def test_null_archive_save_reports_failure_rather_than_raising():
    """A missing archive must never break an incident.

    Sealing a record is on the incident path. If archiving fails the record is
    still in memory and still served; what must not happen is an exception
    escaping into the event loop that carries the resident's stream.
    """
    archive = NullArchive()
    record = _sealed_session().to_record()

    assert await archive.save(record, incident_type="burglary") is False
    assert await archive.get("inc-2026-09-19-0001") is None
    assert await archive.summaries() == []


# ------------------------------------------------------------------ mongo archive
#
# Driven against a fake collection rather than a live cluster. What is worth
# testing here is the behaviour this service adds - upsert by incident id, fail
# soft, report honestly - not that motor can talk to Atlas.


class FakeCollection:
    """Enough of motor's collection API for this archive, and nothing else."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.docs: dict[str, dict] = {}
        self.fail = fail
        self.replace_calls: list[tuple[dict, bool]] = []

    async def replace_one(self, flt, doc, upsert=False):
        if self.fail:
            raise self.fail
        self.replace_calls.append((flt, upsert))
        self.docs[doc["_id"]] = doc
        return None

    async def find_one(self, flt):
        if self.fail:
            raise self.fail
        return self.docs.get(flt["_id"])

    async def count_documents(self, flt):
        if self.fail:
            raise self.fail
        return len(self.docs)

    def find(self, flt=None, projection=None):
        if self.fail:
            raise self.fail
        rows = list(self.docs.values())

        class _Cursor:
            def __init__(self, rows):
                self._rows = rows

            def sort(self, *a, **k):
                return self

            def limit(self, n):
                self._rows = self._rows[:n]
                return self

            def __aiter__(self):
                async def gen():
                    for r in self._rows:
                        yield r

                return gen()

        return _Cursor(rows)


def _archive(collection):
    from hawkeye_backend.replay.archive import MongoReplayArchive

    return MongoReplayArchive.for_collection(collection, uri="mongodb+srv://fake/")


@pytest.mark.asyncio
async def test_saving_the_same_incident_twice_replaces_rather_than_forks():
    """Re-archiving must upsert on the incident id.

    Two rows for one incident is a forked record, and a forked record has to be
    adjudicated by whoever reads it. Upsert makes that structurally impossible.
    """
    col = FakeCollection()
    archive = _archive(col)
    record = _sealed_session().to_record()

    assert await archive.save(record, incident_type="burglary") is True
    assert await archive.save(record, incident_type="burglary") is True

    assert len(col.docs) == 1
    assert all(upsert is True for _, upsert in col.replace_calls)
    assert col.replace_calls[0][0] == {"_id": "inc-2026-09-19-0001"}


@pytest.mark.asyncio
async def test_a_saved_record_reads_back_with_its_chain_intact():
    col = FakeCollection()
    archive = _archive(col)
    original = _sealed_session().to_record()
    await archive.save(original, incident_type="burglary")

    restored = await archive.get("inc-2026-09-19-0001")

    assert restored is not None
    assert restored.root_hash == original.root_hash
    assert len(restored.entries) == len(original.entries)


@pytest.mark.asyncio
async def test_a_failing_archive_reports_false_and_never_raises():
    """Sealing runs on the incident path. A dead Atlas must not reach the loop.

    This is the case that actually happens: the cluster is up, the credentials
    are right, and the demo machine's IP is not on the project access list. The
    record must still be served from memory and the console must still draw.
    """
    col = FakeCollection(fail=RuntimeError("connection refused"))
    archive = _archive(col)
    record = _sealed_session().to_record()

    assert await archive.save(record, incident_type="burglary") is False
    assert await archive.get("inc-2026-09-19-0001") is None
    assert await archive.summaries() == []


@pytest.mark.asyncio
async def test_a_failing_archive_says_so_in_its_status():
    """The console prints this. It must name the failure, not just go quiet."""
    col = FakeCollection(fail=RuntimeError("connection refused"))
    archive = _archive(col)

    status = await archive.status()

    assert status.configured is True
    assert status.connected is False
    assert status.backend == "mongodb"
    assert "connection refused" in status.detail


@pytest.mark.asyncio
async def test_a_healthy_archive_reports_connected_with_a_count():
    col = FakeCollection()
    archive = _archive(col)
    await archive.save(_sealed_session().to_record(), incident_type="burglary")

    status = await archive.status()

    assert status.configured is True
    assert status.connected is True
    assert status.records == 1


@pytest.mark.asyncio
async def test_summaries_come_back_without_deserializing_the_entries():
    """The index asks for a projection, so a few hundred frames stay on the server."""
    col = FakeCollection()
    archive = _archive(col)
    await archive.save(_sealed_session().to_record(), incident_type="burglary")

    rows = await archive.summaries()

    assert [r.incident_id for r in rows] == ["inc-2026-09-19-0001"]
    assert rows[0].entries == 3
    assert rows[0].sealed is True


# --------------------------------------------------------------- readable errors
#
# pymongo's ServerSelectionTimeoutError stringifies to roughly two thousand
# characters: the same TLS alert repeated once per replica set member, then the
# full TopologyDescription with a nested ServerDescription per member. Printing
# that verbatim on the console is how a status line becomes a wall of text.


LONG_DRIVER_ERROR = (
    "SSL handshake failed: ac-x-shard-00-02.mongodb.net:27017: [SSL: "
    "TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error (_ssl.c:1028) "
    "(configured timeouts: socketTimeoutMS: 20000.0ms),SSL handshake failed: "
    "ac-x-shard-00-01.mongodb.net:27017: [SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 "
    "alert internal error (_ssl.c:1028), Timeout: 3.0s, Topology Description: "
    "<TopologyDescription id: 6aaf, topology_type: ReplicaSetNoPrimary, servers: "
    + "<ServerDescription server_type: Unknown, rtt: None, error=AutoReconnect> " * 12
)


@pytest.mark.asyncio
async def test_a_driver_error_is_condensed_to_something_a_page_can_print():
    """The status line is drawn on the console. It must stay one line.

    Root CLAUDE.md is explicit about being picky here: if something looks off,
    fix it. A two-thousand-character topology dump inside a status banner is a
    broken page, and it also buries the one sentence that tells the reader what
    to do about it.
    """
    col = FakeCollection(fail=RuntimeError(LONG_DRIVER_ERROR))
    archive = _archive(col)

    status = await archive.status()

    assert status.connected is False
    assert len(status.detail) < 320, status.detail
    assert "TopologyDescription" not in status.detail
    # The actionable half must survive the trim.
    assert "IP access list" in status.detail


def test_the_condensed_error_still_names_the_actual_failure():
    """Trimming must not turn a diagnosable failure into 'something went wrong'.

    This is what the log lines carry. The page gets `explain_driver_error`
    instead, which translates the two cases that actually happen; the log keeps
    the driver's own words because a log is read by someone who wants them.
    """
    from hawkeye_backend.replay.archive import condense_driver_error

    assert "SSL handshake failed" in condense_driver_error(RuntimeError(LONG_DRIVER_ERROR))
    assert "Authentication failed" in condense_driver_error(
        RuntimeError("bad auth : Authentication failed.")
    )


# ------------------------------------------------- errors a non-engineer can act on
#
# This banner is on a page a judge may be looking at, and the person reading it
# has to know what to do next. "TLSV1_ALERT_INTERNAL_ERROR" names the symptom
# precisely and tells them nothing. Atlas sends that exact alert when the
# client's IP is not on the project access list, which is the failure this
# project will actually hit, so the banner names the cause.


@pytest.mark.asyncio
async def test_a_tls_alert_is_explained_as_an_access_list_problem():
    col = FakeCollection(fail=RuntimeError(LONG_DRIVER_ERROR))
    status = await _archive(col).status()

    assert "IP access list" in status.detail
    assert "TLSV1_ALERT_INTERNAL_ERROR" not in status.detail
    assert len(status.detail) < 260, status.detail


@pytest.mark.asyncio
async def test_bad_credentials_are_not_reported_as_an_access_list_problem():
    """Two different fixes. Conflating them sends someone to the wrong page."""
    col = FakeCollection(fail=RuntimeError("bad auth : Authentication failed."))
    status = await _archive(col).status()

    assert "IP access list" not in status.detail
    assert "credential" in status.detail.lower()


@pytest.mark.asyncio
async def test_an_unrecognised_error_still_says_what_the_driver_said():
    """Mapping known cases must not swallow unknown ones into 'an error occurred'."""
    col = FakeCollection(fail=RuntimeError("some novel driver failure"))
    status = await _archive(col).status()

    assert "some novel driver failure" in status.detail


# ------------------------------------------------------------------ TLS trust
#
# A python.org Python on macOS ships no system root certificates, so an Atlas
# connection fails with CERTIFICATE_VERIFY_FAILED until someone runs Apple's
# "Install Certificates.command". Every teammate on a Mac hits this, and the
# error reads like a broken cluster rather than a broken local trust store.
#
# certifi is already installed as a transitive dependency of httpx, so the
# archive can just use it and the problem never appears.


def test_the_client_is_pointed_at_a_ca_bundle():
    """Otherwise Atlas fails on this machine and it looks like a server problem."""
    from hawkeye_backend.replay.archive import MongoReplayArchive

    kwargs = MongoReplayArchive.client_kwargs()

    assert "tlsCAFile" in kwargs
    assert kwargs["tlsCAFile"].endswith(".pem")


def test_the_client_fails_fast_rather_than_hanging_the_console():
    """The index waits on this. A driver default of 30s is a hung page."""
    from hawkeye_backend.replay.archive import MongoReplayArchive

    kwargs = MongoReplayArchive.client_kwargs()

    assert kwargs["serverSelectionTimeoutMS"] <= 5000


def test_a_missing_certifi_is_not_fatal():
    """certifi is a transitive dependency, not a declared one.

    If it ever goes away the archive must still build and let the system trust
    store decide, rather than failing to construct and taking the hub with it.
    """
    import hawkeye_backend.replay.archive as mod

    original = mod._ca_bundle
    mod._ca_bundle = lambda: None
    try:
        kwargs = mod.MongoReplayArchive.client_kwargs()
    finally:
        mod._ca_bundle = original

    assert "tlsCAFile" not in kwargs
    assert "serverSelectionTimeoutMS" in kwargs
