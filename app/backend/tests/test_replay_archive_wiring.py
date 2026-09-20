"""The archive as the hub uses it: sealed records go out, old records come back.

Driven through the real app with a fake archive substituted, so these exercise
the wiring rather than the driver. The driver has its own tests in
`test_replay_archive.py` and neither file needs a reachable cluster.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
from hawkeye_backend.models.incident import ReplayRecord
from hawkeye_backend.replay.archive import ArchivedSummary, ArchiveStatus


class FakeArchive:
    """An archive that works, and remembers what it was handed."""

    def __init__(self, *, connected: bool = True) -> None:
        self.saved: dict[str, ReplayRecord] = {}
        self.meta: dict[str, dict[str, Any]] = {}
        self.rows: list[ArchivedSummary] = []
        self._connected = connected

    async def save(self, record: ReplayRecord, *, incident_type: str, **meta: Any) -> bool:
        if not self._connected:
            return False
        self.saved[record.incident_id] = record
        self.meta[record.incident_id] = {"incident_type": incident_type, **meta}
        return True

    async def get(self, incident_id: str) -> ReplayRecord | None:
        return self.saved.get(incident_id)

    async def summaries(self, limit: int = 100) -> list[ArchivedSummary]:
        return list(self.rows)

    async def status(self) -> ArchiveStatus:
        return ArchiveStatus(
            configured=True,
            connected=self._connected,
            backend="mongodb",
            # `detail` is contracted to be a complete, self-describing sentence
            # starting "Replay archive ...": it is printed verbatim both in the
            # console banner and in the startup log line. A double that returned
            # a bare "fake" would let a regression in that contract pass.
            detail=(
                "Replay archive connected. 1 sealed record(s) stored."
                if self._connected
                else "Replay archive is configured but unreachable: fake failure."
            ),
            records=len(self.saved),
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def archive() -> FakeArchive:
    return FakeArchive()


@pytest.fixture
def client(archive: FakeArchive):
    app = create_app(Settings(_env_file=None, mode="simulated", sim_speed=0.05))
    app.state.runtime.archive = archive
    with TestClient(app) as c:
        yield c


def _run_full_incident(client: TestClient) -> str:
    """Drive the scripted incident through to a sealed record.

    `POST /v1/demo/run` returns at the simulated human tap; the call plays out
    after it and the record seals when the call ends. So this waits for the seal
    rather than assuming the POST implies it.
    """
    res = client.post("/v1/demo/run?simulate_human_tap=true&scenario=burglary")
    assert res.status_code == 200, res.text
    incident_id = res.json()["raised_incident_id"]
    assert incident_id, res.json()

    recorder = client.app.state.runtime.recorder
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        session = recorder.get(incident_id)
        if session is not None and session.sealed:
            # The archive write happens on the next emit after the seal, which
            # is how the synchronous recorder hands off to the async runtime.
            # The scripted incident always emits a resolved event after, so one
            # short settle is enough rather than a second poll loop.
            time.sleep(0.2)
            return incident_id
        time.sleep(0.05)
    raise AssertionError(f"{incident_id} never sealed")


# ----------------------------------------------------------------------- write


def test_a_sealed_record_is_written_to_the_archive(client: TestClient, archive: FakeArchive):
    """The whole point. When the call ends, the record leaves the process."""
    incident_id = _run_full_incident(client)

    assert incident_id in archive.saved
    stored = archive.saved[incident_id]
    assert stored.sealed is True
    assert stored.root_hash


def test_the_archived_record_carries_the_summary_the_index_needs(
    client: TestClient, archive: FakeArchive
):
    """The console index reads the summary, so the write must supply it.

    `incident_type`, `opened_at`, `frames_dropped` and `seal_reason` are not on
    `ReplayRecord`; they live on the session and the incident. If the runtime
    does not pass them the archived rows come back with defaults and the index
    silently shows "unknown" for every restored record.
    """
    incident_id = _run_full_incident(client)
    meta = archive.meta[incident_id]

    assert meta["incident_type"] == "burglary"
    assert meta["seal_reason"]
    assert "opened_at" in meta
    assert "frames_dropped" in meta


def test_an_unreachable_archive_does_not_break_the_incident():
    """A dead Atlas costs the archive and nothing else.

    This is the failure that actually happens on demo day: the cluster is fine,
    the credentials are fine, and the machine's IP is not on the access list.
    The incident must run to completion and the record must still be served.
    """
    app = create_app(Settings(_env_file=None, mode="simulated", sim_speed=0.05))
    app.state.runtime.archive = FakeArchive(connected=False)
    with TestClient(app) as client:
        incident_id = _run_full_incident(client)
        res = client.get(f"/v1/incident/{incident_id}/replay")

    assert res.status_code == 200
    assert res.json()["sealed"] is True


# ------------------------------------------------------------------------ read


def test_a_record_this_process_never_recorded_is_served_from_the_archive(
    client: TestClient, archive: FakeArchive
):
    """The restart case. The recorder has nothing; the archive has the record."""
    incident_id = _run_full_incident(client)
    stored = archive.saved[incident_id]

    # Forget everything in memory, as a restart would.
    client.app.state.runtime.recorder._sessions.clear()
    client.app.state.runtime.recorder._order.clear()

    res = client.get(f"/v1/incident/{incident_id}/replay")

    assert res.status_code == 200
    assert res.json()["root_hash"] == stored.root_hash


def test_the_index_lists_archived_records_the_recorder_no_longer_holds(
    client: TestClient, archive: FakeArchive
):
    incident_id = _run_full_incident(client)
    archive.rows = [
        ArchivedSummary(
            incident_id=incident_id,
            incident_type="burglary",
            address="1872 Ridgeview Lane, Blacksburg VA 24060",
            opened_at="2026-09-19T12:00:00Z",
            sealed=True,
            duration_s=42.0,
            entries=9,
            frames_dropped=0,
            verifications=4,
            discarded=1,
            root_hash="abc123",
        )
    ]
    client.app.state.runtime.recorder._sessions.clear()
    client.app.state.runtime.recorder._order.clear()

    body = client.get("/v1/replay").json()

    assert [r["incident_id"] for r in body["records"]] == [incident_id]
    assert body["records"][0]["entries"] == 9


def test_a_live_record_wins_over_the_archived_copy_of_itself(
    client: TestClient, archive: FakeArchive
):
    """One row per incident, and the in-memory one is the authority.

    Both sources hold the same incident once it seals. Listing it twice would
    put two rows with one incident id on the console, which reads as a forked
    record.
    """
    incident_id = _run_full_incident(client)
    archive.rows = [
        ArchivedSummary(
            incident_id=incident_id,
            incident_type="burglary",
            address="somewhere else entirely",
            opened_at="2026-09-19T12:00:00Z",
            sealed=True,
            duration_s=1.0,
            entries=1,
            frames_dropped=0,
            verifications=0,
            discarded=0,
            root_hash="stale",
        )
    ]

    body = client.get("/v1/replay").json()

    rows = [r for r in body["records"] if r["incident_id"] == incident_id]
    assert len(rows) == 1
    assert rows[0]["root_hash"] != "stale"


# ---------------------------------------------------------------------- status


def test_the_index_reports_whether_the_archive_is_connected(
    client: TestClient, archive: FakeArchive
):
    """The console prints this.

    An archive that is configured and unreachable looks exactly like "nothing
    has happened yet" unless the page is told the difference.
    """
    body = client.get("/v1/replay").json()

    assert body["archive"]["configured"] is True
    assert body["archive"]["connected"] is True
    assert body["archive"]["backend"] == "mongodb"


def test_an_unconfigured_hub_says_records_are_memory_only():
    app = create_app(Settings(_env_file=None, mode="simulated", sim_speed=0.05))
    with TestClient(app) as client:
        body = client.get("/v1/replay").json()

    assert body["archive"]["configured"] is False
    assert "lost on restart" in body["archive"]["detail"]


# ------------------------------------------------- verify and export, restored
#
# These two are the reason the archive exists at all. A record that survives a
# restart but cannot be exported has not survived in any way a detective cares
# about: the bundle is the deliverable, and the console's export button links
# straight at it.


def test_an_archived_record_can_still_be_exported(client: TestClient, archive: FakeArchive):
    incident_id = _run_full_incident(client)
    client.app.state.runtime.recorder._sessions.clear()
    client.app.state.runtime.recorder._order.clear()

    res = client.get(f"/v1/incident/{incident_id}/replay/export")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert incident_id in res.headers["content-disposition"]


def test_an_archived_records_chain_can_still_be_verified(
    client: TestClient, archive: FakeArchive
):
    """Server-side verify must work on a restored record too.

    The console recomputes the chain in the browser and that stays the check
    that matters, because a server that will lie about a record will also lie
    about having checked it. This endpoint is the convenient second opinion, and
    a 404 on it reads as a missing record rather than as a missing convenience.
    """
    incident_id = _run_full_incident(client)
    stored = archive.saved[incident_id]
    client.app.state.runtime.recorder._sessions.clear()
    client.app.state.runtime.recorder._order.clear()

    body = client.get(f"/v1/incident/{incident_id}/replay/verify").json()

    assert body["intact"] is True
    assert body["root_hash"] == stored.root_hash
    assert body["sealed"] is True


def test_a_genuinely_unknown_incident_is_still_a_404(client: TestClient):
    """The archive fallback must not turn every typo into an empty record."""
    assert client.get("/v1/incident/inc-nope/replay/export").status_code == 404
    assert client.get("/v1/incident/inc-nope/replay/verify").status_code == 404


# ------------------------------------------------------------ mode independence


def test_the_archive_is_wired_in_live_mode_too():
    """Archiving must not be a property of the simulated path.

    The recorder sits on `HubRuntime.emit`, which is the single path every event
    takes regardless of which `MasterClient` produced it, so a record seals and
    archives the same way in live mode. That is the intent; this is the test
    that says so, because the simulated demo is the only path anyone exercises
    by hand and a live-only regression would be found on stage.
    """
    from hawkeye_backend.models.common import utc_now
    from hawkeye_backend.models.events import IncidentEvent, IncidentPhase
    from hawkeye_backend.models.incident import (
        CallState,
        Incident,
        IncidentStatus,
        IncidentType,
        RaisedBy,
    )

    archive = FakeArchive()
    app = create_app(Settings(_env_file=None, mode="live"))
    app.state.runtime.archive = archive
    runtime = app.state.runtime

    inc = Incident(
        incident_id="inc-live-0001",
        site_id="site-demo-01",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=RaisedBy.USER,
        address="1872 Ridgeview Lane, Blacksburg VA 24060",
    )

    async def drive():
        await runtime.emit(IncidentEvent(phase=IncidentPhase.RAISED, incident=inc), inc.incident_id)
        inc.call_state = CallState.ENDED
        inc.status = IncidentStatus.RESOLVED
        inc.resolved_at = utc_now()
        await runtime.emit(
            IncidentEvent(phase=IncidentPhase.RESOLVED, incident=inc), inc.incident_id
        )
        # The hand-off happens on the emit after the seal.
        await runtime.emit(
            IncidentEvent(phase=IncidentPhase.RESOLVED, incident=inc), inc.incident_id
        )

    asyncio.run(drive())

    assert "inc-live-0001" in archive.saved
    assert archive.saved["inc-live-0001"].sealed is True


# --------------------------------------------------------------- startup line
#
# The .env for this service is explicit that a partly-configured Twilio "looks
# exactly like Twilio being slow. Check the startup log line, not the banner."
# The archive gets the same treatment: one line at boot saying whether records
# are actually going anywhere, so the answer does not depend on anyone opening
# the console.


def test_the_hub_says_at_startup_whether_records_are_being_persisted(caplog):
    archive = FakeArchive()
    app = create_app(Settings(_env_file=None, mode="simulated", sim_speed=0.05))
    app.state.runtime.archive = archive

    with caplog.at_level("INFO"):
        with TestClient(app):
            pass

    lines = [r.getMessage() for r in caplog.records]
    assert any(
        "replay archive" in line.lower() and "connected" in line.lower() for line in lines
    ), lines


def test_an_unreachable_archive_is_a_warning_at_startup_not_a_crash(caplog):
    """Boot must not depend on the cluster.

    The demo must never depend on something remote being alive. A hub that
    refuses to start because Atlas is unreachable would make a durability
    feature into a single point of failure for the whole demo.
    """
    app = create_app(Settings(_env_file=None, mode="simulated", sim_speed=0.05))
    app.state.runtime.archive = FakeArchive(connected=False)

    with caplog.at_level("INFO"):
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200

    lines = [r.getMessage() for r in caplog.records]
    assert any("replay archive" in line.lower() for line in lines), lines


# ------------------------------------------------------- import is side-effect free


def test_importing_main_does_not_build_a_hub():
    """`import hawkeye_backend.main` must not construct a runtime.

    It used to, via a module-level `app = create_app()`. That was cheap until
    the replay archive landed, and now it means importing the module opens a
    MongoDB client against whatever `.env` happens to say - in every test run,
    in a `--factory` launch that then builds a second one, and in any tool that
    imports the module to read a symbol out of it.

    `hawkeye_backend.main:app` is still the uvicorn target and still works; it
    is just built on first access rather than at import.
    """
    import hawkeye_backend.main as main

    assert "app" not in vars(main), (
        "module-level app was built at import time; it must be lazy"
    )
    assert main.app is not None
    assert main.app is main.app, "repeated access must not build a second app"
