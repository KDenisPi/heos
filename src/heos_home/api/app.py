"""FastAPI application: REST under /api/v1, WebSocket at /api/v1/ws, PWA at /."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..heos.client import HeosClient
from ..heos.protocol import HeosCommandError, HeosConnectionError, HeosTimeoutError
from ..services.devices import DeviceService
from ..services.events import EventBus
from ..services.images import ImageCache, ImageError
from ..services.library import LibraryService, SearchNotSupported
from ..services.playlists import PlaylistExists, PlaylistService
from ..services.players import PlayerService
from ..services.power import PowerDriverError, PowerManager, PowerNotSupported, PowerRateLimited
from ..settings import Settings
from ..storage import Storage

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    storage: Storage
    bus: EventBus
    client: HeosClient
    players: PlayerService
    devices: DeviceService
    images: ImageCache
    power: PowerManager
    library: LibraryService
    playlists: PlaylistService


def build_services(settings: Settings, client: HeosClient | None = None) -> Services:
    storage = Storage(settings.data_dir)
    bus = EventBus()
    client = client or HeosClient(port=settings.heos_port)
    players = PlayerService(client, bus)
    devices = DeviceService(settings, storage, client, players, bus)
    images = ImageCache(storage.images_dir)
    power = PowerManager(storage, players, client, bus)
    devices.power = power
    library = LibraryService(client, storage, images)
    playlists = PlaylistService(storage, players, library, bus)
    return Services(settings, storage, bus, client, players, devices, images, power, library, playlists)


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or (services.settings if services else Settings.from_env())
    svc = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await svc.images.start()
        await svc.client.start()
        await svc.devices.start()
        await svc.power.start()
        log.info("heos-home %s started, data dir %s", __version__, settings.data_dir)
        try:
            yield
        finally:
            await svc.power.stop()
            await svc.devices.stop()
            await svc.client.stop()
            await svc.images.stop()

    app = FastAPI(
        title="HEOS Home Controller",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/api/v1/openapi.json",
    )
    app.state.services = svc

    _install_error_handlers(app)

    from . import routes, ws  # noqa: PLC0415 - avoid import cycles

    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")

    if settings.static_dir and settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="pwa")
    return app


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(KeyError)
    async def _not_found(_: Request, exc: KeyError) -> JSONResponse:
        return _error(404, "not_found", f"unknown id {exc.args[0] if exc.args else ''}")

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return _error(400, "bad_request", str(exc))

    @app.exception_handler(HeosConnectionError)
    async def _offline(_: Request, exc: HeosConnectionError) -> JSONResponse:
        return _error(503, "heos_offline", str(exc))

    @app.exception_handler(HeosTimeoutError)
    async def _timeout(_: Request, exc: HeosTimeoutError) -> JSONResponse:
        return _error(504, "heos_timeout", str(exc))

    @app.exception_handler(HeosCommandError)
    async def _heos_fail(_: Request, exc: HeosCommandError) -> JSONResponse:
        return _error(502, "heos_error", str(exc), eid=exc.eid, text=exc.text)

    @app.exception_handler(ImageError)
    async def _image(_: Request, exc: ImageError) -> JSONResponse:
        return _error(502, "image_unavailable", str(exc))

    @app.exception_handler(PowerNotSupported)
    async def _no_power(_: Request, exc: PowerNotSupported) -> JSONResponse:
        return _error(501, "power_not_supported", str(exc))

    @app.exception_handler(PlaylistExists)
    async def _playlist_exists(_: Request, exc: PlaylistExists) -> JSONResponse:
        return _error(409, "playlist_exists", str(exc))

    @app.exception_handler(SearchNotSupported)
    async def _no_search(_: Request, exc: SearchNotSupported) -> JSONResponse:
        return _error(501, "search_not_supported", str(exc))

    @app.exception_handler(PowerRateLimited)
    async def _power_rate(_: Request, exc: PowerRateLimited) -> JSONResponse:
        resp = _error(429, "power_rate_limited", str(exc), retry_after=round(exc.retry_after, 1))
        resp.headers["Retry-After"] = str(max(1, round(exc.retry_after)))
        return resp

    @app.exception_handler(PowerDriverError)
    async def _power_fail(_: Request, exc: PowerDriverError) -> JSONResponse:
        return _error(502, "power_error", str(exc))
