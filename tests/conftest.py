from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Awaitable
from pathlib import Path

import re

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


class FakeAct:
    """Mocked UPnP ACT power service. Counts every SetDevicePowerState call."""

    def __init__(self, power: str = "ON") -> None:
        self.power = power
        self.set_calls: list[str] = []
        self.get_calls = 0
        self.reachable = True

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if not self.reachable:
                raise httpx.ConnectError("connection refused", request=request)
            assert request.url.path == "/ACT/control" and request.url.port == 60006
            action = request.headers["SOAPACTION"].strip('"').split("#")[1]
            body = request.content.decode()
            if action == "GetDevicePowerState":
                self.get_calls += 1
                inner = f"<devicePower>{self.power}</devicePower>"
            elif action == "SetDevicePowerState":
                value = re.search(r"<devicePower>(\w+)</devicePower>", body).group(1)
                self.set_calls.append(value)
                self.power = value
                inner = ""
            else:
                return httpx.Response(500)
            xml = (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                   f'<u:{action}Response xmlns:u="urn:schemas-denon-com:service:ACT:1">{inner}'
                   f'</u:{action}Response></s:Body></s:Envelope>')
            return httpx.Response(200, text=xml)

        return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def no_add_pacing(monkeypatch):
    """The real 1 s pacing between playlist adds; tests that need it set it themselves."""
    import heos_home.services.playlists as playlists_mod
    monkeypatch.setattr(playlists_mod, "ADD_GAP", 0.0)


@pytest.fixture
def act() -> FakeAct:
    return FakeAct()


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
    return Settings(data_dir=tmp_path / "data", discovery=False, hosts=["127.0.0.1"], key_file=tmp_path / "etc" / "key")


@pytest.fixture
async def app_env(fake: FakeHeosServer, settings: Settings, act: FakeAct):
    """A started app wired to the fake device and fake ACT service, plus an HTTP client."""
    svc = build_services(settings, fast_client(fake.port, host=None))
    svc.power._transport = act.transport()
    svc.power.settle_timeout = 2.0
    app = create_app(settings, svc)
    async with app.router.lifespan_context(app):
        assert await svc.client.wait_connected(3)
        await wait_for(lambda: PID in svc.players.players and svc.storage.config.data.devices != [])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as http:
            yield app, svc, http
