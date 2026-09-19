"""Application factory and entry point.

    uv run uvicorn hawkeye_backend.main:app --host 0.0.0.0 --port 8787

or just `python -m hawkeye_backend.main`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hawkeye_backend import __version__, api
from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings, get_settings
from hawkeye_backend.master.base import MasterClient
from hawkeye_backend.master.live import LiveMasterClient
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.runtime import HubRuntime
from hawkeye_backend.store import build_store

logger = logging.getLogger(__name__)


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


def build_runtime(settings: Settings | None = None) -> HubRuntime:
    settings = settings or get_settings()
    store = build_store(settings.store_backend, settings.mongodb_uri, settings.mongodb_database)
    return HubRuntime(settings, store, EventBus(), build_client(settings))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime: HubRuntime = app.state.runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Hawk Eye hub",
        version=__version__,
        summary="The app-facing edge of the Hawk Eye agent mesh.",
        description=(
            "The iOS app never talks to the nine agents directly. It talks to this service, "
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

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode, "version": __version__}

    return app


app = create_app()


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
