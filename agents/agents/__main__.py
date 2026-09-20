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
    from hawkeye_backend.verification import TrustStore

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


def build_agent(slug: str) -> Agent:
    """Construct one agent with development inputs.

    The wiring is explicit rather than a registry lookup, because each agent
    takes different inputs and hiding that behind a factory would obscure the
    one thing worth seeing here: `people` is the only consumer of the radio,
    `intruder` reads `people` plus the network, `master` reads both plus a
    locally attached gas sensor, and `caller` and `replay` read only `master`.
    """
    mesh = build_mesh(slug)
    # realtime: a running agent has no test driving the clock, so the feed
    # catches up to the wall clock on read. See `agents.core.dev`.
    #
    # `history_s` has to exceed `BASELINE_SEED_S`, or the seed window is capped
    # by the buffer and the baseline lands a hair under its minimum age - which
    # presents as an agent that is up, ticking, and permanently unhealthy.
    feed = SyntheticCsiFeed(DEMO_ZONES, realtime=True, history_s=240.0)
    roster = StaticRoster()

    match slug:
        case "presence":
            from agents.presence import PresenceAgent

            return PresenceAgent(feed, roster)
        case "intruder":
            from agents.intruder import IntruderAgent

            return IntruderAgent(roster, mesh)
        case "master":
            from agents.master import MasterAgent, SimulatedCoSensor

            return MasterAgent(mesh, gas=SimulatedCoSensor())
        case "caller":
            from agents.caller import CallerAgent

            return CallerAgent(mesh)
        case "vision":
            from hawkeye_backend.models.common import Source

            from agents.core.dev import SyntheticOccupancy
            from agents.vision import VisionAgent

            # `CAMERA_SIM` because that is what this is. The agent refuses any
            # source label that is not a camera, and the honest camera label for
            # a process with no lens attached is the simulated one - which the
            # app renders a badge from rather than hiding.
            return VisionAgent(
                SyntheticOccupancy(), room=VISION_ROOM, source_kind=Source.CAMERA_SIM
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents", description=__doc__)
    parser.add_argument("slug", nargs="?", help="Which agent to run.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--transport-port", type=int, default=8107, help="Transport server port (caller only)")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - must be reachable
    parser.add_argument("--list", action="store_true", help="List the roster and exit.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.list:
        for agent in sorted(ROSTER, key=lambda a: (a.tier, a.slug)):
            print(f"tier {agent.tier}  {agent.slug:<12} {agent.ansname:<44} {agent.summary}")
        return 0

    if not args.slug:
        parser.error("name an agent, or pass --list")

    agent = build_agent(args.slug)
    signer = ClaimSigner(identity(args.slug), load_or_create(args.slug))
    app = build_app(agent, signer=signer)

    import uvicorn

    print(f"{identity(args.slug).name} on http://{args.host}:{args.port}")

    # If this is the caller agent, also launch the Twilio transport server.
    if args.slug == "caller":
        from agents.caller.transport.orchestrator import CallOrchestrator
        from agents.caller.transport.server import build_transport_app
        from agents.caller.transport.twilio_client import RealTwilioVoiceClient
        from agents.caller.transport.simulated import SimulatedCallTransport
        from hawkeye_backend.config import get_settings

        settings = get_settings()

        # Choose real or simulated transport, mirroring app/backend's build_client pattern.
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
            auth_token=settings.twilio_auth_token.get_secret_value() if settings.twilio_voice_configured else "test_auth_token",
            elevenlabs_voice_id=settings.elevenlabs_voice_id or "voice123",
            public_base_url=settings.public_base_url or f"http://{args.host}:{args.transport_port}",
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
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    return 0


if __name__ == "__main__":
    sys.exit(main())
