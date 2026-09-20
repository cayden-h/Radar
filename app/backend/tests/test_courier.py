"""The courier: a sealed record on its way to a police department.

Three things have to be true together, and the tests are grouped that way: the
bundle goes out, the outcome lands on the chain whichever way it went, and the
emailed copy still verifies in the hands of someone who has only that copy.
"""

from __future__ import annotations

import json
import zipfile
from base64 import b64decode
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import build_courier, create_app
from hawkeye_backend.models.incident import Incident, IncidentStatus, IncidentType, RaisedBy
from hawkeye_backend.replay.chain import verify_entries
from hawkeye_backend.replay.courier import (
    CourierReceipt,
    NullCourier,
    ResendCourier,
    bundle_name,
)
from hawkeye_backend.replay.session import RecordSealed, ReplaySession

CALLER = "caller.hawkeye.example"
TO = "dispatch@example.gov"


def _sealed_session() -> ReplaySession:
    incident = Incident(
        incident_id="inc-1",
        site_id="site-1",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=RaisedBy.USER,
        address="1 Test Lane",
    )
    session = ReplaySession(incident, caller_ansname=CALLER)
    session.append(kind="lifecycle", summary="Record opened", actor="hub")
    session.seal("the call ended")
    return session


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------- the send


@pytest.mark.anyio
async def test_the_bundle_goes_out_as_a_zip_that_opens():
    """What the department receives has to be openable by someone with no
    tooling, which is the whole reason the export is a zip and not JSON."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "re_123"})

    courier = ResendCourier(
        api_key="k", from_address="Hawk Eye <a@b.test>", client=_transport(handler)
    )
    record = _sealed_session().to_record()
    receipt = await courier.send(record, to=TO, provenance="operator_supplied")

    assert receipt.outcome == "sent"
    assert receipt.message_id == "re_123"
    assert captured["to"] == [TO]

    attachment = captured["attachments"][0]
    assert attachment["filename"] == bundle_name(record)
    with zipfile.ZipFile(BytesIO(b64decode(attachment["content"]))) as bundle:
        assert set(bundle.namelist()) == {"record.json", "chain.txt", "verify.py", "README.txt"}


@pytest.mark.anyio
async def test_the_email_says_where_the_address_came_from():
    """The person reading it decides whether to act on it, and 'you gave us
    this address on the call' is the sentence that lets them notice if they
    did not."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "re_1"})

    courier = ResendCourier(api_key="k", from_address="a@b.test", client=_transport(handler))
    await courier.send(_sealed_session().to_record(), to=TO, provenance="operator_supplied")
    assert "read back to you" in captured["text"]

    await courier.send(_sealed_session().to_record(), to=TO, provenance="configured")
    assert "not supplied on the call" in captured["text"]


@pytest.mark.anyio
async def test_a_refused_send_is_a_receipt_and_never_an_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"name": "validation_error"})

    courier = ResendCourier(api_key="k", from_address="a@b.test", client=_transport(handler))
    receipt = await courier.send(_sealed_session().to_record(), to=TO, provenance="configured")

    assert receipt.outcome == "failed"
    assert "422" in receipt.detail
    assert "validation_error" in receipt.detail


@pytest.mark.anyio
async def test_an_unreachable_provider_is_a_receipt_too():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    courier = ResendCourier(api_key="k", from_address="a@b.test", client=_transport(handler))
    receipt = await courier.send(_sealed_session().to_record(), to=TO, provenance="configured")

    assert receipt.outcome == "failed"
    assert "could not reach" in receipt.detail


@pytest.mark.anyio
async def test_a_failure_detail_never_carries_the_provider_response_body():
    """Resend echoes the request back on some errors, and the request holds the
    destination address and the whole bundle."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"name": "bad", "message": TO, "echo": "secret-bundle"})

    courier = ResendCourier(api_key="k", from_address="a@b.test", client=_transport(handler))
    receipt = await courier.send(_sealed_session().to_record(), to=TO, provenance="configured")

    assert "secret-bundle" not in receipt.detail


@pytest.mark.anyio
async def test_the_null_courier_reports_skipped_rather_than_failed():
    """A hub with no courier configured is the ordinary case. Conflating it
    with a failure would train a reader to ignore failures."""
    receipt = await NullCourier().send(
        _sealed_session().to_record(), to=TO, provenance="configured"
    )
    assert receipt.outcome == "skipped"


# ------------------------------------------------------------- the chain


def test_a_receipt_chains_onto_a_sealed_record_and_it_still_verifies():
    session = _sealed_session()
    receipt = CourierReceipt(outcome="sent", to=TO, provenance="operator_supplied", message_id="x")
    session.append_courier_receipt(summary=receipt.summary, detail=receipt.model_dump(mode="json"))

    intact, detail, bad = verify_entries(session.to_record().entries)
    assert intact, f"{detail} at {bad}"
    assert session.entries[-1].kind == "courier"


def test_the_emailed_copy_is_a_prefix_of_the_archived_one():
    """The core claim of the post-seal design. A detective holding only the
    email and an investigator reading the archive see the same chain."""
    session = _sealed_session()
    emailed = session.to_record().entries

    session.append_courier_receipt(summary="sent", detail={"outcome": "sent"})
    archived = session.to_record().entries

    assert len(archived) == len(emailed) + 1
    assert [e.entry_hash for e in archived[:-1]] == [e.entry_hash for e in emailed]
    assert verify_entries(emailed)[0]
    assert verify_entries(archived)[0]


def test_a_failed_send_lands_on_the_chain_as_loudly_as_a_successful_one():
    session = _sealed_session()
    receipt = CourierReceipt(
        outcome="failed", to=TO, provenance="configured", detail="the mail provider refused"
    )
    entry = session.append_courier_receipt(
        summary=receipt.summary, detail=receipt.model_dump(mode="json")
    )
    assert "NOT sent" in entry.summary
    assert entry.detail["outcome"] == "failed"


def test_a_receipt_before_the_seal_is_refused():
    """It would describe a bundle that is not the bundle sent."""
    incident = Incident(
        incident_id="inc-2",
        site_id="site-1",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=RaisedBy.USER,
        address="1 Test Lane",
    )
    session = ReplaySession(incident, caller_ansname=CALLER)
    with pytest.raises(RecordSealed):
        session.append_courier_receipt(summary="sent", detail={"outcome": "sent"})


def test_a_failed_send_may_be_retried_and_each_attempt_is_kept():
    """A first attempt that failed and a second that worked is exactly the
    history an investigator wants."""
    session = _sealed_session()
    session.append_courier_receipt(summary="failed", detail={"outcome": "failed"})
    session.append_courier_receipt(summary="sent", detail={"outcome": "sent"})

    kinds = [e.detail.get("outcome") for e in session.entries if e.kind == "courier"]
    assert kinds == ["failed", "sent"]
    assert verify_entries(session.to_record().entries)[0]


def test_a_delivered_record_stops_growing():
    session = _sealed_session()
    session.append_courier_receipt(summary="sent", detail={"outcome": "sent"})
    assert session.delivered
    with pytest.raises(RecordSealed):
        session.append_courier_receipt(summary="sent again", detail={"outcome": "sent"})


# ------------------------------------------------------------ the wiring


def test_the_courier_is_off_unless_it_is_configured():
    """An accidental send puts an incident record in a stranger's inbox and
    cannot be recalled, so every incomplete configuration lands on NullCourier."""
    assert isinstance(build_courier(Settings(mode="simulated")), NullCourier)
    assert isinstance(
        build_courier(Settings(mode="simulated", courier="resend")), NullCourier
    )
    assert isinstance(
        build_courier(Settings(mode="simulated", courier="resend", resend_api_key="k",
                               courier_from="")),
        NullCourier,
    )
    assert isinstance(
        build_courier(Settings(mode="simulated", courier="resend", resend_api_key="k")),
        ResendCourier,
    )


@pytest.fixture
def client():
    settings = Settings(
        mode="simulated",
        sim_autostart=False,
        replay_site_enabled=False,
        live_site_enabled=False,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_the_endpoint_404s_for_an_incident_with_no_record(client: TestClient):
    response = client.post("/v1/incident/nope/courier", json={"to": TO})
    assert response.status_code == 404


def test_the_endpoint_answers_202_with_a_receipt_when_the_send_failed(
    client: TestClient, monkeypatch
):
    """202 rather than 5xx. The send is the subject of the request, and a
    failure is a real answer that was recorded rather than a request that
    could not be processed."""
    runtime = client.app.state.runtime
    session = _sealed_session()
    monkeypatch.setattr(runtime.recorder, "get", lambda _id: session)

    async def refuse(record, *, to, provenance):
        return CourierReceipt(outcome="failed", to=to, provenance=provenance, detail="nope")

    monkeypatch.setattr(runtime.courier, "send", refuse)

    response = client.post("/v1/incident/inc-1/courier", json={"to": TO})
    assert response.status_code == 202
    assert response.json()["outcome"] == "failed"
    # And it is on the chain, which is the half that matters.
    assert session.entries[-1].kind == "courier"


def test_an_address_on_the_request_is_operator_supplied_and_the_fallback_is_not(
    client: TestClient, monkeypatch
):
    runtime = client.app.state.runtime
    runtime.settings.courier_to = "configured@example.gov"
    seen: list[tuple[str, str]] = []

    async def record_it(record, *, to, provenance):
        seen.append((to, provenance))
        return CourierReceipt(outcome="sent", to=to, provenance=provenance)

    monkeypatch.setattr(runtime.courier, "send", record_it)
    monkeypatch.setattr(runtime.recorder, "get", lambda _id: _sealed_session())

    client.post("/v1/incident/inc-1/courier", json={"to": TO})
    client.post("/v1/incident/inc-1/courier", json={})

    assert seen == [(TO, "operator_supplied"), ("configured@example.gov", "configured")]


def test_no_address_anywhere_is_skipped_and_the_record_says_why(
    client: TestClient, monkeypatch
):
    runtime = client.app.state.runtime
    runtime.settings.courier_to = ""
    session = _sealed_session()
    monkeypatch.setattr(runtime.recorder, "get", lambda _id: session)

    response = client.post("/v1/incident/inc-1/courier", json={})
    assert response.status_code == 202
    assert response.json()["outcome"] == "skipped"
    assert "no destination address" in session.entries[-1].detail["detail"]


def test_sending_an_unsealed_record_is_a_409(client: TestClient, monkeypatch):
    incident = Incident(
        incident_id="inc-3",
        site_id="site-1",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=RaisedBy.USER,
        address="1 Test Lane",
    )
    open_session = ReplaySession(incident, caller_ansname=CALLER)
    monkeypatch.setattr(client.app.state.runtime.recorder, "get", lambda _id: open_session)

    response = client.post("/v1/incident/inc-3/courier", json={"to": TO})
    assert response.status_code == 409
