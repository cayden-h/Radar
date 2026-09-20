"""Run one agent: `python -m agents <slug>`.

One process per agent, not one process with five agents in it. That matters:
they are five independently registered identities on five hostnames, and a
single process serving all of them would have one certificate, one TLS identity
and nothing to verify against anything else.

**Host them before they are finished.** Five empty agents reachable tonight
beats five complete agents on a laptop Sunday morning, because the deploy path
is where the hours disappear, and reachable-with-a-correct-card is the surface
`agent.webmesh.ai verify_agent` actually inspects.

    python -m agents people --port 8001
    python -m agents shutter --port 8106
    python -m agents --list

Inputs default to the development fixtures in `agents.core.dev`, which are
labelled simulated in every reading they produce. `--feed replay` is where a
captured CSI session gets wired in, and it is deliberately not implemented yet:
see `sensor/CLAUDE.md`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import TYPE_CHECKING

import httpx

from agents.core.base import Agent
from agents.core.dev import SyntheticCsiFeed, StaticRoster
from agents.core.identity import ROSTER, identity
from agents.core.keys import load_or_create
from agents.core.ports import LocalMesh, ObservationSource
from agents.core.runtime import build_app
from agents.core.signing import ClaimSigner
from agents.core.transport import CLAIM_TARGET_PATH, A2AObservationSource, Peer
from agents.core.discovery import discover
from hawkeye_backend.verification import ClaimVerifier, VerifierPolicy

if TYPE_CHECKING:  # pragma: no cover
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import FastAPI
    from hawkeye_backend.verification import TrustStore

    from agents.master.shutter_client import ShutterClient
    from agents.shutter.backend import ShutterBackend

logger = logging.getLogger(__name__)

#: The one room the fixed camera covers. Every `vision` assertion carries it as
#: `zone_scope`, because a scoped claim that can be read as unscoped is the
#: failure root CLAUDE.md names by hand.
VISION_ROOM = "living_room"

#: The eleven zones of the demo floorplan, from the hub's `build_floorplan`.
#: TODO(sensor): these come from the one-time enrollment walk in the real
#: install. The floorplan is authored, not sensed - walls are the static
#: baseline the system subtracts to see people, so it cannot map them.
DEMO_ZONES = (
    "main_bedroom",
    "second_bedroom",
    "living_room",
    "kitchen",
    "hallway",
    "main_bath",
    "second_bath",
    "main_closet",
    "linen_closet",
    "entry",
    "laundry",
)


def peers_from(base_urls: dict[str, str]) -> dict[str, Peer]:
    """slug -> Peer, from a map of slug to base URL.

    The ANSName comes from our own roster, not from whatever the peer says it
    is. That asymmetry is the point: a name is anchored rather than
    self-asserted, and an agent answering under a different one is the lookalike
    hostname attack, caught at the transport.
    """
    return {
        slug: Peer(slug=slug, base_url=url.rstrip("/"), ansname=identity(slug).ansname)
        for slug, url in base_urls.items()
    }


def build_agent(slug: str, *, feed_kind: str = "synthetic") -> Agent:
    """Construct one agent with development inputs.

    The wiring is explicit rather than a registry lookup, because each agent
    takes different inputs and hiding that behind a factory would obscure the
    one thing worth seeing here: `people` is the only consumer of the radio,
    `intruder` reads `people` plus the network, `master` reads both plus a
    locally attached gas sensor, and `caller` and `replay` read only `master`.
    """
    mesh = build_mesh(slug)
    roster = StaticRoster()

    match slug:
        case "presence":
            from agents.presence import PresenceAgent

            # `--feed rssi` swaps the synthetic radio for the real Mac WiFi-RSSI
            # motion classifier, scoped to the one room it can resolve. It fails
            # over to *blind*, never to a fabricated "absent", when no radio is
            # available - see `agents.presence.rssi`. The default stays synthetic
            # because the demo must never depend on hardware being alive.
            if feed_kind == "rssi":
                from agents.presence.rssi import RssiCsiFeed

                feed = RssiCsiFeed(room=VISION_ROOM)
            else:
                # realtime: a running agent has no test driving the clock, so the
                # feed catches up to the wall clock on read. See `agents.core.dev`.
                #
                # `history_s` has to exceed `BASELINE_SEED_S`, or the seed window
                # is capped by the buffer and the baseline lands a hair under its
                # minimum age - which presents as an agent that is up, ticking,
                # and permanently unhealthy.
                feed = SyntheticCsiFeed(DEMO_ZONES, realtime=True, history_s=240.0)
            return PresenceAgent(feed, roster)
        case "intruder":
            from agents.intruder import IntruderAgent

            return IntruderAgent(roster, mesh)
        case "master":
            from agents.master import MasterAgent, SimulatedCoSensor

            return MasterAgent(mesh, gas=SimulatedCoSensor(), shutter_client=shutter_client())
        case "caller":
            from agents.caller import CallerAgent

            return CallerAgent(mesh)
        case "vision":
            from agents.core.dev import DevNarrations, DevOpenAttestations
            from agents.vision import VisionAgent

            # `occupancy_source()` is the real camera relay by default (synthetic
            # via `HAWKEYE_VISION_SOURCE`), and it reports its own camera label,
            # so `source_kind` is left to its `CAMERA_SIM` default until it does.
            #
            # `vision` claims nothing without a fresh, open attestation from
            # `shutter`. In the live mesh that attestation arrives over ANS; this
            # single-process dev runner has no `shutter` on the wire and runs on
            # `LocalMesh`, which verifies nothing - so the dev attestation and
            # narration fixtures stand in here exactly as `LocalMesh` does. They
            # are NOT the verified path: that runs as separate processes, and the
            # gate's real enforcement is covered in `tests/test_vision_agent.py`.
            return VisionAgent(
                occupancy_source(),
                attestations=DevOpenAttestations(),
                narrations=DevNarrations(),
                room=VISION_ROOM,
            )
        case "replay":
            from agents.replay import ReplayAgent

            return ReplayAgent()
        case "shutter":
            from agents.shutter.agent import ShutterAgent

            # The stub backend is the default, and that is not a placeholder
            # standing in for the real one. The demo must never depend on
            # hardware being alive, so the servo-less path is a first-class
            # implementation and `HAWKEYE_SHUTTER_BACKEND=pigpio` is what opts
            # into the pin. See `docs/swapping-in-real-parts.md`.
            return ShutterAgent(trust=trust_store(slug), backend=shutter_backend())
        case _:
            raise SystemExit(f"no agent {slug!r}. Try --list.")


def occupancy_source():  # noqa: ANN201 - OccupancySource, a Protocol
    """Where `vision` gets its personhood verdict.

    The real one by default, reading the hub's camera relay and running YOLO11m
    plus BoT-SORT on this machine. `HAWKEYE_VISION_SOURCE=synthetic` opts back
    into the scripted verdict for a laptop with no hub up.

    **The real path is the default and the synthetic one is the opt-in**, which
    is the reverse of how this started. A synthetic default is how you get to a
    judging table with a camera pointed at a room and an agent answering from a
    script, and nothing on any screen tells you which one you are watching -
    because a `CAMERA_SIM` badge is exactly what a real camera relay reports
    until the hub says otherwise.

    Failing to build the real one is **not** a fallback to the synthetic one. It
    returns a source that reports `tracker_unavailable` forever, which is the
    honest answer: this process could not look. A silent downgrade to a scripted
    verdict would let a demo with no camera present as a demo with one.
    """
    from hawkeye_vision.occupancy import Occupancy

    choice = os.environ.get("HAWKEYE_VISION_SOURCE", "relay").strip().lower()
    if choice == "synthetic":
        from agents.core.dev import SyntheticOccupancy

        logger.warning(
            "HAWKEYE_VISION_SOURCE=synthetic: vision is answering from a script, not "
            "from a camera. Every claim it makes will be labelled camera-sim."
        )
        return SyntheticOccupancy()
    if choice != "relay":
        raise SystemExit(
            f"HAWKEYE_VISION_SOURCE={choice!r}; expected 'relay' or 'synthetic'"
        )

    hub = os.environ.get("HAWKEYE_HUB_URL", "http://127.0.0.1:8787")
    try:
        from hawkeye_vision.config import VisionConfig
        from hawkeye_vision.live_occupancy import LiveOccupancySource
        from hawkeye_vision.relay import RelayFrameSource
        from hawkeye_vision.yolo_tracker import build_tracker

        config = VisionConfig()
        source = LiveOccupancySource(
            RelayFrameSource(hub), build_tracker(config), config=config
        )
        source.start()
        logger.info("vision reading the camera relay at %s", hub)
        return source
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.error(
            "could not build the camera path (%s). vision will report "
            "tracker_unavailable rather than falling back to a script: an agent that "
            "answered from a fixture while a camera was on the table would be lying "
            "about which sensor produced the claim.",
            exc,
        )

        class _Blind:
            """Reports that it could not look. Never that the room is empty."""

            def occupancy(self) -> Occupancy:
                return Occupancy.TRACKER_UNAVAILABLE

        return _Blind()


def shutter_client() -> "ShutterClient | None":
    """How `master` reaches the shield, from `HAWKEYE_PEERS`.

    The same env var that turns the mesh on turns this on, and for the same
    reason: both are the difference between an in-process stand-in that verifies
    nothing about a transport and two independently registered agents talking
    over one.

    `None` when `shutter` is not in the peer list, and that is the correct
    degenerate behaviour rather than a fallback. A master with no shutter client
    never issues a grant, so the lens stays covered - and a silent in-process
    substitute here would be a shield that moved without anything crossing the
    wire, which is the one outcome this project must never demonstrate by
    accident.
    """
    raw = os.environ.get("HAWKEYE_PEERS", "").strip()
    base_urls = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
    url = base_urls.get("shutter")
    if not url:
        logger.warning(
            "no shutter in HAWKEYE_PEERS, so master holds no shutter client and will "
            "never issue a grant. The lens stays covered, which is safe and is not a "
            "working demo."
        )
        return None

    from agents.master.shutter_client import A2AShutterClient

    return A2AShutterClient(
        url,
        key=load_or_create("master"),
        issuer=identity("master").ansname,
    )


def shutter_backend() -> "ShutterBackend":
    """Stub unless `HAWKEYE_SHUTTER_BACKEND=pigpio` says otherwise.

    Failing over to the stub when `pigpio` is unavailable would be the wrong
    call and is deliberately not done: an operator who asked for the pin and
    silently got a number has a shutter that reports open while the lens is
    covered, which is the exact failure the attestation's `commanded` wording
    exists to keep visible.
    """
    from agents.shutter.backend import StubShutter

    choice = os.environ.get("HAWKEYE_SHUTTER_BACKEND", "stub").strip().lower()
    if choice == "stub":
        return StubShutter()
    if choice == "pigpio":
        from agents.shutter.pigpio_backend import PigpioShutter

        return PigpioShutter()
    raise SystemExit(f"HAWKEYE_SHUTTER_BACKEND={choice!r}; expected 'stub' or 'pigpio'")


def trust_store(slug: str) -> "TrustStore":
    """The keys this agent will verify against, from the peers' published cards.

    `shutter` needs one of these and no mesh: it does not read anybody's
    observations, it only checks who is giving it orders.
    """
    raw = os.environ.get("HAWKEYE_PEERS", "").strip()
    if not raw:
        from hawkeye_backend.verification import TrustStore

        logger.warning(
            "no HAWKEYE_PEERS, so %s holds an empty trust store and will refuse every "
            "grant as unregistered_issuer. That is the correct behaviour for an agent "
            "that cannot discover who master is, and it is not a working demo.",
            slug,
        )
        return TrustStore()

    base_urls = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
    store, fingerprints = discover(peers_from(base_urls))
    logger.info("trust store holds %d peers", len(fingerprints))
    return store


def build_mesh(slug: str) -> ObservationSource:
    """How this agent reads its dependencies.

    `HAWKEYE_PEERS` turns the wire on: a comma-separated `slug=url` list, e.g.

        HAWKEYE_PEERS=people=https://people.hawkeye.example

    With it set, claims are fetched over A2A, verified against the keys in the
    peers' own published trust cards, and discarded with a reason when they do
    not verify. Without it, the in-process `LocalMesh` stands in and **verifies
    nothing**, which the whole stack reports honestly: master records
    `envelope_verified: false` and `caller` refuses to speak.
    """
    raw = os.environ.get("HAWKEYE_PEERS", "").strip()
    if not raw:
        return LocalMesh()

    base_urls = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
    peers = peers_from(base_urls)
    me = identity(slug)

    # The trust store comes from the peers' published cards, not from a
    # hardcoded key list. That is what ties acceptance to the same document the
    # judge's verifier reads and the transparency log sealed.
    store, fingerprints = discover(peers)
    logger.info("trust store holds %d of %d peers", len(fingerprints), len(peers))

    verifier = ClaimVerifier(
        policy=VerifierPolicy(
            audience=me.ansname,
            target=f"{me.base_url}{CLAIM_TARGET_PATH}",
        ),
        trust=store,
    )
    return A2AObservationSource(
        peers,
        verifier,
        audience=me.ansname,
        target=f"{me.base_url}{CLAIM_TARGET_PATH}",
    )


def build_master_app(
    agent: Agent, signer: ClaimSigner, key: "Ed25519PrivateKey"
) -> "FastAPI":
    """Master serves two surfaces on one app, and this wires the first of them.

    `hub_router` is the read/incident/grant/stream surface `app/backend`'s
    `LiveMasterClient` polls - `/v1/state`, `/v1/sensor`, `/v1/agents`,
    `/v1/stream`, `/v1/shutter/grant`. It is mounted through `build_app`'s
    `routers`/`on_start`/`on_stop` hooks, which exist for exactly this agent:
    the hub needs a background publisher started alongside the agent's own tick
    and stopped before it. Every other agent passes those hooks nothing.

    The second surface, the `/a2a/{start-call,set-mode}` call bridge, is added
    by `attach_call_bridge_routes` after this returns. The two are deliberately
    separate implementations: this surface reports and never dials, and the call
    bridge is the only path to a phone call. `hub_api.a2a_hub_router` is
    intentionally *not* mounted here - it duplicates those two paths but gates
    without triggering `agents/caller`, so mounting it would both shadow the
    dialing routes and serve a start-call that never dials.

    Site id and address come from the same `hawkeye_backend` settings the hub's
    `SimulatedMasterClient` reads, so the live state a surface renders is scoped
    to the same installation the mock one was.
    """
    from agents.master import MasterAgent
    from agents.master.hub_api import MasterHub, hub_router
    from hawkeye_backend.config import get_settings
    from hawkeye_backend.master.scenario import build_floorplan

    if not isinstance(agent, MasterAgent):  # pragma: no cover - guarded by caller
        raise SystemExit("build_master_app called for a non-master agent")

    settings = get_settings()
    hub = MasterHub(
        agent,
        site_id=settings.site_id,
        site_address=settings.site_address,
        floorplan=build_floorplan(settings.site_id),
        key=key,
        camera_room=VISION_ROOM,
    )
    return build_app(
        agent,
        signer=signer,
        routers=[hub_router(hub)],
        on_start=hub.start,
        on_stop=hub.stop,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents", description=__doc__)
    parser.add_argument("slug", nargs="?", help="Which agent to run.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--transport-port", type=int, default=8107, help="Transport server port (caller only)")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - must be reachable
    parser.add_argument("--list", action="store_true", help="List the roster and exit.")
    parser.add_argument(
        "--feed",
        choices=["synthetic", "rssi"],
        default="synthetic",
        help=(
            "presence only. `synthetic` is the ruview-sim radio (default, no "
            "hardware). `rssi` reads the real Mac WiFi-RSSI motion classifier."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.list:
        for agent in sorted(ROSTER, key=lambda a: (a.tier, a.slug)):
            print(f"tier {agent.tier}  {agent.slug:<12} {agent.ansname:<44} {agent.summary}")
        return 0

    if not args.slug:
        parser.error("name an agent, or pass --list")

    agent = build_agent(args.slug, feed_kind=args.feed)
    key = load_or_create(args.slug)
    signer = ClaimSigner(identity(args.slug), key)
    # `master` alone serves a second surface - the one `app/backend` reads - so
    # its app is built with the hub router and its background publisher. The
    # `/a2a` call bridge is attached to this same app in the `master` branch
    # below. Every other agent gets the plain single-surface app.
    if args.slug == "master":
        app = build_master_app(agent, signer, key)
    else:
        app = build_app(agent, signer=signer)

    import uvicorn

    print(f"{identity(args.slug).name} on http://{args.host}:{args.port}")

    # If this is the caller agent, also launch the Twilio transport server.
    if args.slug == "caller":
        # `os` is imported at module top and must not be re-imported here: a
        # local `import os` inside this function makes `os` a local of `main()`
        # for the whole body, so the `master` branch below raises
        # UnboundLocalError reading `os.environ` when its own branch never ran.
        from hawkeye_backend.config import get_settings

        settings = get_settings()
        transport = (settings.call_transport or "retell").strip().lower()
        internal_token = os.environ.get("HAWKEYE_INTERNAL_TRIGGER_TOKEN", "").strip() or None

        if transport == "twilio":
            # Dormant path, retained. Paywalled; not the default.
            from agents.caller.transport.orchestrator import CallOrchestrator
            from agents.caller.transport.server import build_transport_app
            from agents.caller.transport.simulated import SimulatedCallTransport
            from agents.caller.transport.twilio_client import RealTwilioVoiceClient

            if settings.mode == "live" and settings.twilio_voice_configured:
                voice_client = RealTwilioVoiceClient(
                    account_sid=settings.twilio_account_sid,
                    auth_token=settings.twilio_auth_token.get_secret_value(),
                )
            else:
                voice_client = SimulatedCallTransport()
            orchestrator = CallOrchestrator(
                caller=agent,
                transport=voice_client,
                mock_911_number=settings.mock_911_number or "+15550004444",
                twilio_voice_number=settings.twilio_voice_number or "+15550003333",
                twiml_app_sid=settings.twilio_conference_app_sid or "APxxxx",
                status_callback_url=(settings.public_base_url or f"http://{args.host}:{args.transport_port}") + "/twilio/status",
            )
            transport_app = build_transport_app(
                orchestrator,
                auth_token=settings.twilio_auth_token.get_secret_value() if settings.twilio_voice_configured else None,
                elevenlabs_voice_id=settings.elevenlabs_voice_id or "voice123",
                public_base_url=settings.public_base_url or f"http://{args.host}:{args.transport_port}",
                internal_trigger_token=internal_token,
            )
        else:
            # Default: Retell (free). Real client only when live + configured;
            # otherwise a simulated client that drives the identical path.
            from agents.caller.transport.retell import (
                RealRetellVoiceClient,
                RetellCallOrchestrator,
                SimulatedRetellVoiceClient,
                build_retell_transport_app,
            )
            from agents.caller.transport.retell.courier_client import (
                HttpBackendCourierClient,
            )

            if settings.mode == "live" and settings.retell_configured:
                retell_client = RealRetellVoiceClient(
                    api_key=settings.retell_api_key.get_secret_value(),
                    agent_id=settings.retell_agent_id,
                )
            else:
                retell_client = SimulatedRetellVoiceClient()
            # The operator-supplied police email captured mid-call is POSTed to
            # the edge service's courier endpoint. Fail-soft: a POST that cannot
            # reach the hub logs and is dropped rather than breaking the live 911
            # call. The email is a destination the operator read back, never
            # authorization - the backend records it as `operator_supplied`.
            orchestrator = RetellCallOrchestrator(
                agent,
                retell_client,
                from_number=settings.retell_from_number or "+15550003333",
                operator_number=settings.mock_911_number or "+15550004444",
                courier=HttpBackendCourierClient(settings.edge_base_url),
            )
            transport_app = build_retell_transport_app(
                orchestrator,
                websocket_secret=(settings.retell_websocket_secret or None) if (settings.mode == "live" and settings.retell_configured) else None,
                internal_trigger_token=internal_token,
            )

        print(f"caller transport on http://{args.host}:{args.transport_port}")

        # Run both servers: the A2A server on the main port and the transport server on transport-port.
        # We use a simple async wrapper to run both concurrently.
        import asyncio

        async def run_both():
            config_a2a = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
            config_transport = uvicorn.Config(transport_app, host=args.host, port=args.transport_port, log_level="info")
            server_a2a = uvicorn.Server(config_a2a)
            server_transport = uvicorn.Server(config_transport)
            await asyncio.gather(server_a2a.serve(), server_transport.serve())

        asyncio.run(run_both())
    elif args.slug == "master":
        # The two call-bridge hops from app/backend's LiveMasterClient:
        # POST /a2a/start-call and POST /a2a/set-mode, added to the same app
        # build_app() already returned - the same pattern used for caller's
        # second transport-server app above, just without a second port.
        from agents.master.transport import attach_call_bridge_routes

        caller_transport_url = os.environ.get("HAWKEYE_CALLER_TRANSPORT_URL", "").strip()
        internal_trigger_token = os.environ.get("HAWKEYE_INTERNAL_TRIGGER_TOKEN", "").strip() or None

        caller_client: httpx.AsyncClient | None = None
        if caller_transport_url:
            headers = {"Authorization": f"Bearer {internal_trigger_token}"} if internal_trigger_token else {}
            caller_client = httpx.AsyncClient(
                base_url=caller_transport_url.rstrip("/"), headers=headers, timeout=10.0
            )
        else:
            logger.warning(
                "HAWKEYE_CALLER_TRANSPORT_URL is not set; this master process has no way "
                "to reach agents/caller's transport server, so /a2a/start-call and "
                "/a2a/set-mode will fail closed with a 500 rather than doing nothing silently."
            )

        attach_call_bridge_routes(app, agent, caller_client=caller_client)

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    return 0


if __name__ == "__main__":
    sys.exit(main())
