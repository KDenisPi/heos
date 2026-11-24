from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Awaitable
from pathlib import Path

import httpx
import pytest

from heos_home.api.app import build_services, create_app
from heos_home.heos.client import HeosClient
from heos_home.heos.fake import FakeHeosServer
from heos_home.settings import Settings

PID = -1234


async def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def fake() -> AsyncIterator[FakeHeosServer]:
    server = await FakeHeosServer().start()
    yield server
    await server.stop()


def fast_client(port: int, host: str | None = "127.0.0.1") -> HeosClient:
    return HeosClient(host, port, command_timeout=1.0, heartbeat_interval=0.2,
                      backoff_min=0.05, backoff_max=0.2, connect_timeout=1.0)


@pytest.fixture
async def client(fake: FakeHeosServer) -> AsyncIterator[HeosClient]:
    c = fast_client(fake.port)
    await c.start()
    assert await c.wait_connected(3)
    yield c
    await c.stop()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", discovery=False, hosts=["127.0.0.1"])


@pytest.fixture
async def app_env(fake: FakeHeosServer, settings: Settings):
    """A started app wired to the fake device, plus an HTTP client."""
    svc = build_services(settings, fast_client(fake.port, host=None))
    app = create_app(settings, svc)
    async with app.router.lifespan_context(app):
        assert await svc.client.wait_connected(3)
        await wait_for(lambda: PID in svc.players.players and svc.storage.config.data.devices != [])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as http:
            yield app, svc, http
