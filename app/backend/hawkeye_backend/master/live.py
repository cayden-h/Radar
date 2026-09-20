"""LiveMasterClient: talks to a real agents/master.

`agents/master` does not exist yet (agents/ holds CLAUDE.md files and no code as
of 2026-09-19), so this client is written against the contract in
agents/CLAUDE.md rather than against a running service. Every assumption it
makes about master's HTTP surface is marked TODO(master) below, and the client
raises MasterUnavailable rather than fabricating state when the mesh is down.

That last property is the important one. A hub that quietly invents interior
state when it cannot reach the mesh is exactly the failure this project exists
to prevent, so there is no fallback-to-simulated path here. If you want the
scripted incident, set HAWKEYE_MODE=simulated and say so out loud.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from pydantic import ValidationError

from hawkeye_backend.master.base import (
    AutonomousDialRefused,
    EventSink,
    MasterUnavailable,
    ParticipationModeRefused,
)
from hawkeye_backend.master.scenario import AGENT_ROSTER
from hawkeye_backend.models.events import EnvelopeAdapter
from hawkeye_backend.models.hub import AgentReachability, Reachability, SensorLiveness
from hawkeye_backend.models.incident import (
    ContextNote,
    Incident,
    IncidentType,
    RaisedBy,
    ReplayRecord,
)
from hawkeye_backend.models.state import InteriorState

logger = logging.getLogger(__name__)

# TODO(master): these paths are this service's proposal, not a contract
# agents/master has agreed to. Reconcile with whoever builds master before the
# live demo. The open questions are:
#   (a) does master expose one merged state document, or does the hub fan out to
#       the five sensing agents itself? The architecture diagram in
#       agents/CLAUDE.md routes everything through master, so this assumes one.
#   (b) is the push channel a websocket, SSE, or an outbound webhook to the hub?
#       This assumes master exposes a websocket the hub subscribes to.
#   (c) does master accept an incident raised by the app directly, or does the
#       hub have to present an ANS identity to do it? The hub is on the human
#       side of the boundary, so it presumably authenticates as itself over mTLS
#       (ANS-2). Nothing here implements mTLS yet.
PATH_STATE = "/v1/state"
PATH_SENSOR = "/v1/sensor"
PATH_AGENTS = "/v1/agents"
PATH_INCIDENT = "/v1/incident"
PATH_STREAM = "/v1/stream"
PATH_START_CALL = "/a2a/start-call"
PATH_SET_MODE = "/a2a/set-mode"
PATH_INJECT_CONTEXT = "/a2a/inject-context"
PATH_GRANT = "/v1/shutter/grant"


class LiveMasterClient:
    """Implements MasterClient against a real agents/master over HTTP."""

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None
        self._sink: EventSink | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    # ---------------------------------------------------------------- lifecycle

    async def start(self, sink: EventSink) -> None:
        self._sink = sink
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        self._stream_task = asyncio.create_task(self._stream_loop())
        logger.info("live master client started against %s", self._base_url)

    async def stop(self) -> None:
        self._stopping.set()
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
        if self._client is not None:
            await self._client.aclose()

    def _require(self) -> httpx.AsyncClient:
        if self._client is None:
            raise MasterUnavailable("live master client was not started")
        return self._client

    # ------------------------------------------------------------ push channel

    async def _stream_loop(self) -> None:
        """Subscribe to master's push channel and forward every envelope.

        Master already speaks the same tagged-union envelope the app consumes, so
        the hub validates and forwards rather than translating. Validation is not
        optional: a malformed frame from the mesh must not reach the app as if it
        were fine.
        """
        import websockets  # imported lazily so simulated mode does not need it

        url = self._base_url.replace("http://", "ws://").replace("https://", "wss://") + PATH_STREAM
        backoff = 1.0
        while not self._stopping.is_set():
            try:
                async with websockets.connect(url) as socket:
                    logger.info("subscribed to master stream at %s", url)
                    backoff = 1.0
                    async for raw in socket:
                        if self._sink is None:
                            continue
                        try:
                            envelope = EnvelopeAdapter.validate_json(raw)
                        except ValidationError:
                            logger.exception("master sent a frame this hub cannot validate; dropped")
                            continue
                        await self._sink.emit(envelope.payload, envelope.incident_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on anything
                logger.warning("master stream dropped (%s); retrying in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    # ------------------------------------------------------------------ queries

    async def _get(self, path: str) -> dict[str, object]:
        try:
            response = await self._require().get(path)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"GET {path} failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise MasterUnavailable(f"GET {path} returned a non-object body")
        return payload

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        try:
            response = await self._require().post(path, json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"POST {path} failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise MasterUnavailable(f"POST {path} returned a non-object body")
        return payload

    async def sensor_liveness(self) -> SensorLiveness:
        return SensorLiveness.model_validate(await self._get(PATH_SENSOR))

    async def agent_reachability(self) -> list[AgentReachability]:
        try:
            payload = await self._get(PATH_AGENTS)
        except MasterUnavailable as exc:
            # master itself being unreachable is a reportable state, not a 500.
            # The Connect screen needs to render "cannot reach the mesh".
            return [
                AgentReachability(
                    name=name,
                    ansname=ans,
                    tier=tier,
                    reachability=Reachability.UNREACHABLE,
                    detail=str(exc),
                )
                for name, tier, ans, _ in AGENT_ROSTER
            ]
        agents = payload.get("agents", [])
        if not isinstance(agents, list):
            raise MasterUnavailable("GET /v1/agents returned no agents array")
        return [AgentReachability.model_validate(a) for a in agents]

    async def current_state(self) -> InteriorState:
        return InteriorState.model_validate(await self._get(PATH_STATE))

    async def raise_incident(
        self, incident_type: IncidentType, raised_by: RaisedBy, note: str | None
    ) -> Incident:
        # The hub forwards taps, and only taps. master owns the mesh side of
        # this, but the hub refuses to be the thing that asks it to dial without
        # a human: Hawk Eye never calls 911 on its own, settled 2026-09-19.
        if raised_by is not RaisedBy.USER:
            raise AutonomousDialRefused(
                f"the hub will not forward a {raised_by.value!r}-raised incident to master. "
                "A detection surfaces as interior state; a human tap releases the call."
            )
        body: dict[str, object] = {
            "incident_type": incident_type.value,
            "raised_by": raised_by.value,
        }
        if note:
            body["note"] = note
        return Incident.model_validate(await self._post(PATH_INCIDENT, body))

    async def submit_context(self, incident_id: str, text: str) -> ContextNote:
        return ContextNote.model_validate(
            await self._post(f"{PATH_INCIDENT}/{incident_id}/context", {"text": text})
        )

    async def fetch_replay(self, incident_id: str) -> ReplayRecord | None:
        try:
            payload = await self._get(f"{PATH_INCIDENT}/{incident_id}/replay")
        except MasterUnavailable:
            return None
        return ReplayRecord.model_validate(payload)

    async def start_call(self, incident: Incident) -> None:
        # Same guard as raise_incident above, and for the same reason: this
        # process cannot lean on agents/master's in-process
        # `release_for_call` check across the network boundary, so it holds
        # its own copy. Hawk Eye never calls 911 on its own, settled
        # 2026-09-19.
        if incident.raised_by is not RaisedBy.USER:
            raise AutonomousDialRefused(
                f"the hub will not start a call for a {incident.raised_by.value!r}-raised "
                "incident. A detection surfaces as interior state; a human tap releases the call."
            )
        # `agents/master` has no route for raising an incident over HTTP
        # (out of scope for the call-bridge wiring; see
        # agents/agents/master/transport.py's docstring), so master cannot
        # call its own `raise_incident` before `release_for_call` unless the
        # incident it needs is carried inline in this request. This hub is
        # the only side holding the full `Incident` at this point in the
        # flow, so the body widens to carry what `raise_incident` needs
        # rather than just the id.
        body: dict[str, object] = {
            "incident_id": incident.incident_id,
            "incident_type": incident.incident_type.value,
            "raised_by": incident.raised_by.value,
            "address": incident.address,
        }
        if incident.context_notes:
            body["note"] = incident.context_notes[-1].text
        try:
            response = await self._require().post(PATH_START_CALL, json=body)
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"POST {PATH_START_CALL} failed: {exc}") from exc
        if response.status_code == 403:
            raise AutonomousDialRefused(
                f"master refused to start the call for incident {incident.incident_id}: "
                f"{response.text}"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"POST {PATH_START_CALL} failed: {exc}") from exc

    async def set_participation_mode(
        self, incident_id: str, mode: str, *, by_human: bool
    ) -> str:
        body: dict[str, object] = {
            "incident_id": incident_id,
            "mode": mode,
            "by_human": by_human,
        }
        try:
            response = await self._require().post(PATH_SET_MODE, json=body)
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"POST {PATH_SET_MODE} failed: {exc}") from exc
        if response.status_code == 403:
            raise ParticipationModeRefused(
                f"master refused to switch incident {incident_id} to mode {mode!r}: "
                f"{response.text}"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MasterUnavailable(f"POST {PATH_SET_MODE} failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("announcement"), str):
            raise MasterUnavailable(f"POST {PATH_SET_MODE} returned no announcement string")
        return payload["announcement"]

    async def inject_context(self, incident_id: str, text: str) -> None:
        """POST the resident's note to master's `/a2a/inject-context`.

        Best-effort by contract (see `MasterClient.inject_context`): raises
        `MasterUnavailable` on failure like every other POST here, and it is
        the caller's job (`api.post_context`) to catch that and log rather
        than fail the note store. This method does not swallow the error
        itself, so a genuine misconfiguration is still visible to whoever is
        watching logs - fail-loud at this layer, fail-soft one layer up.
        """
        await self._post(
            PATH_INJECT_CONTEXT,
            {"incident_id": incident_id, "text": text},
        )

    async def issue_shutter_grant(
        self, *, action: str, reason: str, nonce: str, incident_id: str | None = None
    ) -> str:
        """Ask the real master to sign a grant.

        Returned opaque and never re-parsed on the way to `shutter`, which
        verifies the signature over exactly these bytes.
        """
        payload = await self._post(
            PATH_GRANT,
            {
                "action": action,
                "reason": reason,
                "nonce": nonce,
                "incident_id": incident_id,
            },
        )
        grant = payload.get("grant_json")
        if not isinstance(grant, str) or not grant:
            raise MasterUnavailable("master returned no grant_json")
        return grant
