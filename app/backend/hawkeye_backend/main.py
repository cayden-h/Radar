"""Application factory and entry point.

    uv run uvicorn hawkeye_backend.main:app --host 0.0.0.0 --port 8787

or just `python -m hawkeye_backend.main`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from hawkeye_backend import __version__, api
from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings, get_settings
from hawkeye_backend.discovery import HubAdvertiser
from hawkeye_backend.master.base import MasterClient
from hawkeye_backend.master.live import LiveMasterClient
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.notices import NoticeSink, TwilioSink
from hawkeye_backend.replay.archive import MongoReplayArchive, NullArchive, ReplayArchive
from hawkeye_backend.replay.courier import Courier, NullCourier, ResendCourier
from hawkeye_backend.runtime import HubRuntime
from hawkeye_backend.store import build_store

logger = logging.getLogger(__name__)

#: The replay console. A static directory, not a build artifact: no bundler, no
#: CDN, nothing to install. `app/backend/hawkeye_backend/main.py` sits three
#: levels under `app/`, and the console lives at `app/web/replay`.
REPLAY_SITE = Path(__file__).resolve().parents[2] / "web" / "replay"

#: The live console. Same deal as REPLAY_SITE: a static directory, no
#: bundler, nothing to install. It is the third surface, and it exists so
#: "any app, same backend" is something a judge can watch rather than a
#: claim they have to take on trust.
LIVE_SITE = Path(__file__).resolve().parents[2] / "web" / "live"


def build_client(settings: Settings) -> MasterClient:
    """One env var decides the whole demo's dependencies."""
    if settings.mode == "simulated":
        return SimulatedMasterClient(
            site_id=settings.site_id,
            address=settings.site_address,
            speed=settings.sim_speed,
            autostart=settings.sim_autostart,
        )
    return LiveMasterClient(settings.master_base_url, settings.master_timeout_s)


def build_courier(settings: Settings) -> Courier:
    """Who mails a sealed record out of the building.

    Built here rather than inside HubRuntime so a misconfiguration is a startup
    log line rather than a surprise at the end of a 911 call.

    Every refusal below is a refusal to construct a courier at all, not a
    courier that fails at send time. A hub that cannot mail anybody says so
    once, at boot, in the log a human is already reading - and the record then
    truthfully says the send was skipped for want of a courier.
    """
    if settings.courier != "resend":
        logger.info("courier: off, sealed records are not sent anywhere")
        return NullCourier()
    if not settings.resend_api_key.get_secret_value():
        logger.warning(
            "courier: HAWKEYE_COURIER=resend but HAWKEYE_RESEND_API_KEY is empty. "
            "Sealed records will not be sent."
        )
        return NullCourier()
    if not settings.courier_from:
        logger.warning(
            "courier: HAWKEYE_COURIER=resend but HAWKEYE_COURIER_FROM is empty. "
            "Sealed records will not be sent."
        )
        return NullCourier()
    logger.warning(
        "courier: resend enabled, sending as %s. A sealed record will be emailed "
        "when an incident's call ends. **Verify the sending domain in the Resend "
        "dashboard**: an unverified domain accepts the send, returns a message id, "
        "and delivers nothing, and the record will record that as a success.",
        settings.courier_from,
    )
    return ResendCourier(
        api_key=settings.resend_api_key.get_secret_value(),
        from_address=settings.courier_from,
    )


def build_runtime(settings: Settings | None = None) -> HubRuntime:
    settings = settings or get_settings()
    store = build_store(settings.store_backend, settings.mongodb_uri, settings.mongodb_database)

    # The stream sink is added by HubRuntime itself and is always present, so
    # the in-app banner works with no Twilio account at all. Twilio is the only
    # path that reaches a phone that is locked with the app closed.
    notice_sinks: list[NoticeSink] = []
    if settings.twilio_configured:
        notice_sinks.append(
            TwilioSink(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token.get_secret_value(),
                from_number=settings.twilio_from_number,
                to_number=settings.twilio_to_number,
                timezone=settings.site_timezone,
                min_interval_s=settings.twilio_min_interval_s,
                max_per_instance=settings.twilio_max_per_instance,
            )
        )
        logger.info("notices: twilio sms sink enabled")
    else:
        logger.info("notices: twilio not configured, in-app banner only")

    # The replay archive. Sealed records only, written once when a call ends.
    # Built here rather than inside HubRuntime so a failure to construct the
    # driver is a startup log line rather than an exception inside an incident.
    archive: ReplayArchive = NullArchive()
    if settings.replay_archive == "mongodb":
        if not settings.mongodb_uri:
            logger.warning(
                "replay archive: HAWKEYE_REPLAY_ARCHIVE=mongodb but "
                "HAWKEYE_MONGODB_URI is empty. Sealed records will be memory-only."
            )
        else:
            try:
                archive = MongoReplayArchive(settings.mongodb_uri, settings.mongodb_database)
                logger.info(
                    "replay archive: mongodb, database %s, collection replays",
                    settings.mongodb_database,
                )
            except Exception as exc:
                # Constructing a motor client does not connect, so this is a
                # missing dependency or a malformed URI rather than an outage.
                logger.error(
                    "replay archive: could not build the mongodb client (%s). "
                    "Sealed records will be memory-only.",
                    exc,
                )
    else:
        logger.info("replay archive: off, sealed records are memory-only")

    return HubRuntime(
        settings,
        store,
        EventBus(),
        build_client(settings),
        notice_sinks=notice_sinks,
        archive=archive,
        courier=build_courier(settings),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime: HubRuntime = app.state.runtime
    await runtime.start()

    # One line at boot saying whether sealed records are actually going
    # anywhere. The .env for this service already makes this argument about
    # Twilio - a partial configuration "looks exactly like Twilio being slow.
    # Check the startup log line, not the banner" - and the archive has the
    # same shape: silently memory-only is indistinguishable from a quiet night.
    #
    # Never fatal. The demo must not depend on a remote cluster being alive, so
    # an unreachable archive is a warning and the hub serves records from memory.
    try:
        status = await runtime.archive.status()
        # `detail` is already a complete sentence starting "Replay archive ...",
        # written to be printed on the console. Prefixing it here produced
        # "replay archive: connected. Replay archive connected. 1 record."
        if status.configured and not status.connected:
            logger.warning("%s", status.detail)
        else:
            logger.info("%s", status.detail)
    except Exception as exc:
        logger.warning("replay archive: status could not be read at startup (%s)", exc)

    # Bonjour. The app's Connect screen has no manual address field, so without
    # this the only way onto a live hub is editing `Config.fallbackBaseURL` and
    # rebuilding. Never fatal: see hawkeye_backend/discovery.py.
    advertiser = HubAdvertiser(runtime.settings, runtime.settings.port)
    await advertiser.start()

    try:
        yield
    finally:
        await advertiser.stop()
        await runtime.stop()
        await runtime.archive.close()
        await runtime.courier.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Hawk Eye hub",
        version=__version__,
        summary="The app-facing edge of the Hawk Eye agent mesh.",
        description=(
            "The iOS app never talks to the five agents directly. It talks to this service, "
            "which talks to agents/master. That keeps the ANS-verified agent-to-agent mesh "
            "separate from the human-facing surface."
        ),
        lifespan=lifespan,
    )
    # The app is a native iOS client on the same LAN, discovered over Bonjour.
    # CORS is here only so a browser can poke the API during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.runtime = build_runtime(settings)
    app.include_router(api.router)

    # The motion detector. It runs as its own process out of
    # wifi-rssi-motion-template/, on its own port, with no dependency on this
    # service - so all the hub owes it is a stable address on the hub's own
    # origin. /motion is that address; the consoles link to it rather than to
    # a hardcoded localhost port.
    if settings.motion_console_url:

        @app.get("/motion", include_in_schema=False)
        async def motion() -> RedirectResponse:
            return RedirectResponse(url=settings.motion_console_url)

        logger.info("motion console redirect: /motion -> %s", settings.motion_console_url)
    else:
        logger.info("motion console redirect disabled by configuration")

    # The live console. Mounted before /replay and after the API router, so
    # it cannot shadow an API route either.
    if settings.live_site_enabled and LIVE_SITE.is_dir():
        app.mount("/live", StaticFiles(directory=LIVE_SITE, html=True), name="live-console")
        logger.warning(
            "live console served at /live from %s. It carries Start Incident and "
            "the shutter controls and has no authentication, so it is as trusted "
            "as the network it is on. HAWKEYE_LIVE_SITE_ENABLED=false turns it off.",
            LIVE_SITE,
        )
    elif not settings.live_site_enabled:
        logger.info("live console disabled by configuration")

    # The replay console. Mounted last so it cannot shadow an API route, and
    # behind a flag because serving a human surface is a deployment decision.
    if settings.replay_site_enabled and REPLAY_SITE.is_dir():
        app.mount(
            "/replay",
            StaticFiles(directory=REPLAY_SITE, html=True),
            name="replay-console",
        )

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/replay/")

        logger.info("replay console served at /replay from %s", REPLAY_SITE)
    elif settings.replay_site_enabled:
        logger.warning("replay console enabled but %s does not exist", REPLAY_SITE)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode, "version": __version__}

    return app


#: The ASGI target, `hawkeye_backend.main:app`, built on first access.
#:
#: Lazy rather than module-level, because importing this module must not
#: construct a hub. A module-level `app = create_app()` opens a MongoDB client
#: for the replay archive as a side effect of an import - in every test run, in
#: a `--factory` launch that then builds a second one, and in any tool that
#: imports this module to read a symbol out of it.
#:
#: `__getattr__` keeps the uvicorn target spelled exactly as before (PEP 562).
_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    global _app
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _app is None:
        _app = create_app()
    return _app


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = get_settings()
    uvicorn.run(
        "hawkeye_backend.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
