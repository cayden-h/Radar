# Courier Demo Send Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During a live Retell 911 call, 5 seconds after the caller agent asks the operator for a police email, force-send the incident record (sealed or not) to a fixed demo address and to the operator-supplied address if one was captured.

**Architecture:** The caller agent's `RetellCallOrchestrator` already asks for the email when a closing cue trips. On that transition it now schedules one background task that sleeps `courier_delay_s`, then POSTs to the backend courier endpoint with a new `force` flag so the record is sent even though the call has not ended (the record is not sealed yet). The backend courier gains a `force` parameter that skips its "must be sealed" guard. The seal-time auto-send is put behind a config toggle so it does not double-mail.

**Tech Stack:** Python 3.13, asyncio, httpx, FastAPI, pydantic-settings, pytest (`pytest-asyncio`/`anyio`). Two packages: `agents/` (the caller agent) and `app/backend/` (the hub). Both import `hawkeye_backend.config.get_settings`.

## Global Constraints

- Run agent tests with `cd agents && python -m pytest -q`; backend tests with `cd app/backend && python -m pytest -q`.
- **Fail soft on the call loop.** Nothing in the orchestrator's send path may raise into the WebSocket handler; log and swallow. A dropped 911 call causes a dispatch; a lost email does not.
- **Provenance stays honest.** The fixed demo send goes out as `configured` (empty `to`, backend uses `settings.courier_to`). The operator send goes out as `operator_supplied` (non-empty `to`). Never label the fixed address `operator_supplied`.
- Default values must preserve existing behavior: `force` defaults `False`, `courier_auto_send_on_seal` defaults `True`.
- The `.env` for the demo lives at `app/backend/.env` (gitignored) and already contains: `HAWKEYE_COURIER=resend`, `HAWKEYE_RESEND_API_KEY=…`, `HAWKEYE_COURIER_FROM=Hawk Eye <hawkeye@cayden.tech>`, `HAWKEYE_COURIER_TO=tringuyen7379@gmail.com`, `HAWKEYE_COURIER_DELAY_S=5.0`, `HAWKEYE_COURIER_AUTO_SEND_ON_SEAL=false`.

## File Structure

- `app/backend/hawkeye_backend/config.py` — add `courier_delay_s`, `courier_auto_send_on_seal`.
- `app/backend/hawkeye_backend/runtime.py` — `deliver(..., force=False)`; gate `_archive_sealed` auto-send behind the toggle.
- `app/backend/hawkeye_backend/api.py` — `CourierRequest.force`; thread it in `post_courier`.
- `agents/agents/caller/transport/retell/courier_client.py` — `deliver(..., force=False)`, new `deliver_configured(..., force=False)`, on Protocol + Http + Simulated.
- `agents/agents/caller/transport/retell/orchestrator.py` — `courier_delay_s` field; schedule the delayed force-send on the ask; add `force=True` to the operator send.
- `agents/agents/__main__.py` — pass `settings.courier_delay_s` into `RetellCallOrchestrator`.
- Tests: `app/backend/tests/test_courier_force.py`, `agents/tests/test_courier_client.py`, `agents/tests/test_retell_demo_send.py`.

---

### Task 1: Backend `force` send + seal-send toggle

**Files:**
- Modify: `app/backend/hawkeye_backend/config.py` (add two settings near `courier_to`, ~line 257)
- Modify: `app/backend/hawkeye_backend/runtime.py` (`deliver` ~line 362; `_archive_sealed` ~line 349)
- Test: `app/backend/tests/test_courier_force.py` (create)

**Interfaces:**
- Produces: `Settings.courier_delay_s: float = 5.0`, `Settings.courier_auto_send_on_seal: bool = True`.
- Produces: `HubRuntime.deliver(incident_id: str, *, to: str, provenance: AddressProvenance, force: bool = False) -> CourierReceipt`. When `force=True`, an unsealed record is sent instead of raising `RecordSealed`.

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_courier_force.py`:

```python
"""force lets the courier send a record that has not sealed yet, and the
seal-time auto-send can be switched off so a force-send is not doubled."""

from __future__ import annotations

import pytest

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
from hawkeye_backend.models.events import IncidentEvent, IncidentPhase
from hawkeye_backend.models.incident import (
    Incident,
    IncidentStatus,
    IncidentType,
    RaisedBy,
)
from hawkeye_backend.replay.courier import AddressProvenance
from hawkeye_backend.replay.session import RecordSealed


class SpyCourier:
    """Records every send; never touches the network."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, record, *, to: str, provenance: AddressProvenance):
        from hawkeye_backend.replay.courier import CourierReceipt

        self.sends.append({"incident_id": record.incident_id, "to": to, "provenance": provenance})
        return CourierReceipt(outcome="sent", to=to, provenance=provenance, detail="spy")


def _open_incident(runtime, incident_id: str) -> None:
    """Open a recording session the way the hub does — an observed RAISED event.

    The recorder has no `open`; a session begins when it observes the incident's
    RAISED event (see `test_replay_session.py`'s `raise_it`).
    """
    incident = Incident(
        incident_id=incident_id,
        site_id="site-1",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=RaisedBy.USER,
        address="1 Test Lane",
    )
    runtime.recorder.observe(
        IncidentEvent(phase=IncidentPhase.RAISED, incident=incident), incident_id
    )


def _runtime_with_open_incident():
    app = create_app(Settings(mode="simulated", replay_site_enabled=False))
    runtime = app.state.runtime
    _open_incident(runtime, "inc-force")
    return runtime


@pytest.mark.anyio
async def test_force_sends_an_unsealed_record():
    runtime = _runtime_with_open_incident()
    spy = SpyCourier()
    runtime.courier = spy
    receipt = await runtime.deliver(
        "inc-force", to="x@y.test", provenance="operator_supplied", force=True
    )
    assert receipt.outcome == "sent"
    assert spy.sends and spy.sends[0]["to"] == "x@y.test"


@pytest.mark.anyio
async def test_without_force_an_unsealed_record_raises():
    runtime = _runtime_with_open_incident()
    runtime.courier = SpyCourier()
    with pytest.raises(RecordSealed):
        await runtime.deliver("inc-force", to="x@y.test", provenance="operator_supplied")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && python -m pytest tests/test_courier_force.py -q`
Expected: FAIL — `deliver()` got an unexpected keyword argument `force` (and/or the no-force case does not raise as written).

- [ ] **Step 3: Add the two settings**

In `app/backend/hawkeye_backend/config.py`, immediately after the `courier_to: str = ""` field (~line 257), add:

```python
    # Seconds the caller agent waits after asking the operator for a police
    # email before it force-sends the record. Consumed by the caller agent's
    # orchestrator, which reads the same Settings.
    courier_delay_s: float = 5.0

    # Whether a record that seals triggers the automatic send to `courier_to`.
    # True preserves the historical behavior. Set False when the caller agent
    # drives a force-send during the call, so the record sealing later does not
    # mail the same address a second time.
    courier_auto_send_on_seal: bool = True
```

- [ ] **Step 4: Add `force` to `deliver` and gate the seal-time send**

In `app/backend/hawkeye_backend/runtime.py`, change the `deliver` signature and its sealed-guard:

```python
    async def deliver(
        self, incident_id: str, *, to: str, provenance: AddressProvenance, force: bool = False
    ) -> CourierReceipt:
```

Then replace the guard:

```python
        if not session.sealed:
            raise RecordSealed(f"{incident_id} is not sealed; there is nothing to send yet")
```

with:

```python
        if not session.sealed and not force:
            raise RecordSealed(f"{incident_id} is not sealed; there is nothing to send yet")
```

In `_archive_sealed`, wrap the auto-send so the toggle controls it. Replace:

```python
            await self.deliver(incident_id, to=self.settings.courier_to, provenance="configured")
```

with:

```python
            if self.settings.courier_auto_send_on_seal:
                await self.deliver(
                    incident_id, to=self.settings.courier_to, provenance="configured"
                )
```

- [ ] **Step 5: Run the tests**

Run: `cd app/backend && python -m pytest tests/test_courier_force.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/config.py app/backend/hawkeye_backend/runtime.py app/backend/tests/test_courier_force.py
git commit -m "courier: force-send an unsealed record; toggle seal-time auto-send"
```

---

### Task 2: Thread `force` through the courier endpoint

**Files:**
- Modify: `app/backend/hawkeye_backend/api.py` (`CourierRequest` ~line 616; `post_courier` ~line 654)
- Test: append to `app/backend/tests/test_courier_force.py`

**Interfaces:**
- Consumes: `HubRuntime.deliver(..., force=...)` from Task 1.
- Produces: `POST /v1/incident/{id}/courier` accepts `{"to": str, "force": bool}`; `force` defaults `False`.

- [ ] **Step 1: Write the failing test**

Append to `app/backend/tests/test_courier_force.py`:

```python
from fastapi.testclient import TestClient


def _client_with_incident():
    app = create_app(Settings(mode="simulated", replay_site_enabled=False))
    _open_incident(app.state.runtime, "inc-ep")
    return TestClient(app)


def test_endpoint_rejects_unsealed_without_force():
    with _client_with_incident() as client:
        resp = client.post("/v1/incident/inc-ep/courier", json={"to": "a@b.test"})
        assert resp.status_code == 409


def test_endpoint_accepts_unsealed_with_force():
    with _client_with_incident() as client:
        resp = client.post("/v1/incident/inc-ep/courier", json={"to": "a@b.test", "force": True})
        assert resp.status_code == 202
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && python -m pytest tests/test_courier_force.py -q`
Expected: FAIL — the force case still returns 409 because the endpoint ignores `force`.

- [ ] **Step 3: Add `force` to the request model**

In `app/backend/hawkeye_backend/api.py`, in `class CourierRequest`, after the `to` field add:

```python
    force: bool = Field(
        default=False,
        description=(
            "Send even if the record has not sealed yet. Used by the caller "
            "agent's demo send during a live call, when the record is still "
            "being written. The emailed copy is a snapshot, not the final "
            "sealed record."
        ),
    )
```

- [ ] **Step 4: Thread it into the delivery call**

In `post_courier`, change:

```python
        return await runtime.deliver(incident_id, to=to, provenance=provenance)
```

to:

```python
        return await runtime.deliver(incident_id, to=to, provenance=provenance, force=body.force)
```

- [ ] **Step 5: Run the tests**

Run: `cd app/backend && python -m pytest tests/test_courier_force.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/api.py app/backend/tests/test_courier_force.py
git commit -m "courier endpoint: accept and thread a force flag"
```

---

### Task 3: Courier client — `force` and a configured send

**Files:**
- Modify: `agents/agents/caller/transport/retell/courier_client.py`
- Test: `agents/tests/test_courier_client.py` (create)

**Interfaces:**
- Consumes: `POST /v1/incident/{id}/courier {to, force}` from Task 2.
- Produces on `BackendCourierClient` (Protocol), `HttpBackendCourierClient`, `SimulatedBackendCourierClient`:
  - `deliver(incident_id: str, to: str, *, force: bool = False) -> None`
  - `deliver_configured(incident_id: str, *, force: bool = False) -> None` — POSTs with no `to`, so the backend uses `courier_to` and records `configured`.
- `SimulatedBackendCourierClient.deliveries` entries gain a `force: bool` key and a `configured: bool` key (True for `deliver_configured`).

- [ ] **Step 1: Write the failing test**

Create `agents/tests/test_courier_client.py`:

```python
"""The courier-client seam: what it POSTs to the backend, including force and
the configured (no-address) send."""

from __future__ import annotations

import httpx
import pytest

from agents.caller.transport.retell.courier_client import (
    HttpBackendCourierClient,
    SimulatedBackendCourierClient,
)


def _recording_transport(captured: list[dict]) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(202, json={"outcome": "sent"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_deliver_posts_to_and_force():
    captured: list[dict] = []
    client = HttpBackendCourierClient("http://hub.test", client=_recording_transport(captured))
    await client.deliver("inc-1", "police@dept.test", force=True)
    assert captured[0]["url"].endswith("/v1/incident/inc-1/courier")
    assert captured[0]["body"] == {"to": "police@dept.test", "force": True}


@pytest.mark.asyncio
async def test_deliver_configured_posts_no_address():
    captured: list[dict] = []
    client = HttpBackendCourierClient("http://hub.test", client=_recording_transport(captured))
    await client.deliver_configured("inc-1", force=True)
    assert captured[0]["body"] == {"force": True}
    assert "to" not in captured[0]["body"]


@pytest.mark.asyncio
async def test_simulated_records_force_and_configured():
    sim = SimulatedBackendCourierClient()
    await sim.deliver("inc-1", "a@b.test", force=True)
    await sim.deliver_configured("inc-1", force=True)
    assert sim.deliveries[0] == {"incident_id": "inc-1", "to": "a@b.test", "force": True, "configured": False}
    assert sim.deliveries[1] == {"incident_id": "inc-1", "to": "", "force": True, "configured": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_courier_client.py -q`
Expected: FAIL — `deliver()` has no `force` kwarg and `deliver_configured` does not exist.

- [ ] **Step 3: Update the Protocol**

In `agents/agents/caller/transport/retell/courier_client.py`, replace the `BackendCourierClient` Protocol body:

```python
class BackendCourierClient(Protocol):
    async def deliver(self, incident_id: str, to: str, *, force: bool = False) -> None: ...
    async def deliver_configured(self, incident_id: str, *, force: bool = False) -> None: ...
```

- [ ] **Step 4: Update the HTTP implementation**

Replace `HttpBackendCourierClient.deliver` with the version below and add `deliver_configured` and a shared `_post` right after it (keep the existing docstring above `deliver`):

```python
    async def deliver(self, incident_id: str, to: str, *, force: bool = False) -> None:
        # The email is the destination only. It is passed straight through as
        # `to`; the backend attaches `operator_supplied` provenance and never
        # reads it as authorization. See this module's docstring.
        await self._post(incident_id, {"to": to, "force": force})

    async def deliver_configured(self, incident_id: str, *, force: bool = False) -> None:
        # No `to`: the backend falls back to its configured `courier_to` and
        # records the send as `configured`, not `operator_supplied`. This is the
        # fixed demo destination, honestly labelled as the hub's own address.
        await self._post(incident_id, {"force": force})

    async def _post(self, incident_id: str, body: dict) -> None:
        url = f"{self._base_url}/v1/incident/{incident_id}/courier"
        try:
            resp = await self._client.post(url, json=body)
        except httpx.HTTPError as exc:
            # Fail soft: the call outlives a courier POST that never landed.
            logger.warning("courier POST to %s failed to send: %s", url, exc)
            return
        if resp.status_code >= 400:
            logger.warning(
                "courier POST to %s rejected: %s %s", url, resp.status_code, resp.text
            )
```

- [ ] **Step 5: Update the simulated implementation**

Widen the `deliveries` annotation (values now include booleans) — change
`self.deliveries: list[dict[str, str]] = []` to `self.deliveries: list[dict] = []`.
Then replace `SimulatedBackendCourierClient` methods:

```python
    async def deliver(self, incident_id: str, to: str, *, force: bool = False) -> None:
        self.deliveries.append(
            {"incident_id": incident_id, "to": to, "force": force, "configured": False}
        )

    async def deliver_configured(self, incident_id: str, *, force: bool = False) -> None:
        self.deliveries.append(
            {"incident_id": incident_id, "to": "", "force": force, "configured": True}
        )
```

- [ ] **Step 6: Run the tests**

Run: `cd agents && python -m pytest tests/test_courier_client.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add agents/agents/caller/transport/retell/courier_client.py agents/tests/test_courier_client.py
git commit -m "courier client: force flag and a configured (no-address) send"
```

---

### Task 4: Orchestrator schedules the 5s force-send on the ask

**Files:**
- Modify: `agents/agents/caller/transport/retell/orchestrator.py`
- Modify: `agents/agents/__main__.py` (RetellCallOrchestrator construction ~line 530)
- Test: `agents/tests/test_retell_demo_send.py` (create)

**Interfaces:**
- Consumes: `deliver_configured(incident_id, force=True)` and `deliver(incident_id, to, force=True)` from Task 3; `Settings.courier_delay_s` from Task 1.
- Produces: `RetellCallOrchestrator` gains a `courier_delay_s: float = 5.0` field and, after asking for the email, an awaitable `_demo_send_task` that force-sends the configured destination once.

- [ ] **Step 1: Write the failing test**

Create `agents/tests/test_retell_demo_send.py`:

```python
"""When the agent asks for the police email, it schedules exactly one delayed
force-send to the configured (demo) destination."""

from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent
from agents.caller.transport.retell.client import SimulatedRetellVoiceClient
from agents.caller.transport.retell.courier_client import SimulatedBackendCourierClient
from agents.caller.transport.retell.orchestrator import RetellCallOrchestrator
from agents.master import MasterAgent


def _orchestrator(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    courier = SimulatedBackendCourierClient()
    orch = RetellCallOrchestrator(
        caller,
        SimulatedRetellVoiceClient(),
        from_number="+15550001111",
        operator_number="+15550009999",
        courier=courier,
        courier_delay_s=0.0,
    )
    return orch, courier


async def _closing_cue_turn(orch):
    # A response_required carrying an operator line that reads as a dispatch
    # close, which is what makes the agent ask for the email.
    return await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 1,
            "transcript": [{"role": "agent", "content": "hi"}, {"role": "user", "content": "I've dispatched units, two minutes out"}],
        }
    )


@pytest.mark.asyncio
async def test_asking_for_the_email_schedules_a_configured_force_send(mesh):
    orch, courier = _orchestrator(mesh)
    await orch.start_call("inc-9", IncidentType.BURGLARY, "12 Elm Street")
    reply = await _closing_cue_turn(orch)
    assert "email" in reply["content"].lower()
    await orch._demo_send_task  # delay is 0.0
    assert courier.deliveries == [
        {"incident_id": "inc-9", "to": "", "force": True, "configured": True}
    ]


@pytest.mark.asyncio
async def test_the_demo_send_is_scheduled_only_once(mesh):
    orch, courier = _orchestrator(mesh)
    await orch.start_call("inc-9", IncidentType.BURGLARY, "12 Elm Street")
    await _closing_cue_turn(orch)
    first_task = orch._demo_send_task
    # A second closing cue must not schedule another send.
    await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 2,
            "transcript": [{"role": "user", "content": "units are still two minutes out"}],
        }
    )
    assert orch._demo_send_task is first_task
    await orch._demo_send_task
    configured = [d for d in courier.deliveries if d["configured"]]
    assert len(configured) == 1


@pytest.mark.asyncio
async def test_operator_email_is_sent_with_force(mesh):
    orch, courier = _orchestrator(mesh)
    await orch.start_call("inc-9", IncidentType.BURGLARY, "12 Elm Street")
    await _closing_cue_turn(orch)  # now in ASKED_EMAIL
    await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 3,
            "transcript": [{"role": "user", "content": "send it to dispatch@pd.test"}],
        }
    )
    operator = [d for d in courier.deliveries if d["to"] == "dispatch@pd.test"]
    assert operator and operator[0]["force"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_retell_demo_send.py -q`
Expected: FAIL — `RetellCallOrchestrator` has no `courier_delay_s` argument / no `_demo_send_task`.

- [ ] **Step 3: Add imports, fields, and the operator-send force flag**

In `agents/agents/caller/transport/retell/orchestrator.py`:

At the top of the module (after `from __future__ import annotations`), add:

```python
import asyncio
import logging
```

and after the existing imports add:

```python
logger = logging.getLogger(__name__)
```

In the `@dataclass` `RetellCallOrchestrator`, add these fields after `courier: BackendCourierClient | None = None`:

```python
    courier_delay_s: float = 5.0
```

and after the existing `_email_capture` field add:

```python
    _demo_send_scheduled: bool = field(default=False, init=False)
    _demo_send_task: asyncio.Task | None = field(default=None, init=False)
```

In `_respond_to_operator`, in the branch that captures the operator email, change:

```python
                if self.courier is not None:
                    await self.courier.deliver(self.incident_id or "", email)
```

to:

```python
                if self.courier is not None:
                    await self.courier.deliver(self.incident_id or "", email, force=True)
```

- [ ] **Step 4: Schedule the delayed send when the agent asks**

Still in `_respond_to_operator`, in the branch that trips the closing cue (`NORMAL` → `ASKED_EMAIL`), add the scheduling call right after `self._email_capture = _EmailCapture.ASKED_EMAIL`:

```python
            self._email_capture = _EmailCapture.ASKED_EMAIL
            self._schedule_demo_send()
            return (
                "Before you go - what email address should I send the sealed "
                "incident record to?"
            )
```

Then add these two methods to the class (place them just before `_opening_text`):

```python
    def _schedule_demo_send(self) -> None:
        """Start the one-shot delayed force-send to the configured destination.

        Called the moment the agent asks for the police email. Fires exactly
        once per call; a second closing cue does not re-arm it.
        """
        if self._demo_send_scheduled:
            return
        self._demo_send_scheduled = True
        incident_id = self.incident_id or ""
        self._demo_send_task = asyncio.create_task(self._delayed_demo_send(incident_id))

    async def _delayed_demo_send(self, incident_id: str) -> None:
        """Wait `courier_delay_s`, then force-send to the configured address.

        Fail-soft by contract: this runs on the call's event loop and must
        never raise into the WebSocket handler. The configured (no-address)
        send is recorded `configured`; the operator address, if the operator
        gives one, is sent separately on capture.
        """
        try:
            await asyncio.sleep(self.courier_delay_s)
            if self.courier is not None:
                await self.courier.deliver_configured(incident_id, force=True)
        except Exception as exc:  # noqa: BLE001 - never break the call loop
            logger.warning("delayed demo courier send failed for %s: %s", incident_id, exc)
```

- [ ] **Step 5: Pass `courier_delay_s` in at construction**

In `agents/agents/__main__.py`, find the `RetellCallOrchestrator(` construction (~line 530) and add the `courier_delay_s` argument:

```python
            orchestrator = RetellCallOrchestrator(
                agent,
                retell_client,
                from_number=settings.retell_from_number or "+15550003333",
                operator_number=settings.mock_911_number or "+15550004444",
                courier=HttpBackendCourierClient(settings.edge_base_url),
                courier_delay_s=settings.courier_delay_s,
            )
```

- [ ] **Step 6: Run the tests**

Run: `cd agents && python -m pytest tests/test_retell_demo_send.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the existing orchestrator tests for regressions**

Run: `cd agents && python -m pytest tests/test_retell_orchestrator.py -q`
Expected: PASS (unchanged).

- [ ] **Step 8: Commit**

```bash
git add agents/agents/caller/transport/retell/orchestrator.py agents/agents/__main__.py agents/tests/test_retell_demo_send.py
git commit -m "caller: force-send the record 5s after asking for the police email"
```

---

## End-to-end verification (run once, at the very end)

Not a task with a checkbox — the final manual proof after all four tasks pass.

1. Confirm `app/backend/.env` has the courier block (see Global Constraints).
2. Restart the demo processes so they pick up the `.env`: caller (`:8107`), cloudflared tunnel, master (`:8900`), hub (`:8787`); re-point the Retell agent's Custom-LLM URL at the current tunnel.
3. Place a call. As the operator, say a closing line ("I've dispatched units, two minutes out"). The agent asks for the email.
4. Within ~5 seconds, an email from `hawkeye@cayden.tech` with the record bundle lands in `tringuyen7379@gmail.com`. If a spoken email was captured, it arrives there too.
5. If the receipt says `sent` but no email arrives, the `cayden.tech` sending domain is not verified on the Resend account — check the Resend dashboard, not the code.
