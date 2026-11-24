"""Power drivers and power state (F2).

The HEOS CLI has no power command and keeps answering in network standby, so
power goes through a separate path. On the PM7000N that path is the UPnP
"ACT" service the HEOS app uses (``urn:schemas-denon-com:service:ACT:1`` on
port 60006): ``GetDevicePowerState`` / ``SetDevicePowerState`` with ON/OFF.

Drivers (``power.driver`` per device in config.json):

* ``auto``     - use ``upnp_act`` if the device answers it, else ``none`` (default)
* ``upnp_act`` - UPnP ACT service, verified on PM7000N firmware 3.139.175
* ``none``     - no power control; the amp's remote handles power

``PowerManager`` caches the state, polls it (30 s, plus a quick re-check when
a HEOS volume event hints at a change), pushes ``power`` events, and guards
the hardware: a request for the current state is a no-op, and real switches
are at least ``min_switch_interval`` seconds apart.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from typing import Any, Protocol

import httpx

from ..heos.client import HeosClient
from ..heos.protocol import HeosMessage
from ..storage import Storage
from .events import EventBus
from .players import PlayerService

log = logging.getLogger(__name__)

ON, STANDBY, UNKNOWN = "on", "standby", "unknown"
KNOWN_DRIVERS = ("auto", "upnp_act", "none")


class PowerNotSupported(Exception):
    pass


class PowerRateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"power was switched moments ago; try again in {retry_after:.0f} s")


class PowerDriverError(Exception):
    """The device did not accept or answer a power request."""


class PowerDriver(Protocol):
    name: str

    async def get_state(self) -> str:
        """Return "on", "standby" or "unknown"."""

    async def set_state(self, on: bool) -> None:
        """Switch on (True) or to standby (False)."""


class NoPowerDriver:
    name = "none"

    async def get_state(self) -> str:
        return UNKNOWN

    async def set_state(self, on: bool) -> None:
        raise PowerNotSupported("no power driver for this device; use the amp's remote")


class UpnpActDriver:
    """Power via the Denon/Marantz UPnP ACT service (port 60006)."""

    name = "upnp_act"
    SERVICE = "urn:schemas-denon-com:service:ACT:1"

    def __init__(self, ip: str, http: httpx.AsyncClient, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.ip = ip
        self.http = http
        port = int(config.get("port", 60006))
        self.url = config.get("control_url") or f"http://{ip}:{port}/ACT/control"

    async def _soap(self, action: str, args: str = "") -> str:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{self.SERVICE}">{args}</u:{action}>'
            "</s:Body></s:Envelope>"
        )
        headers = {"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{self.SERVICE}#{action}"'}
        try:
            resp = await self.http.post(self.url, content=body.encode(), headers=headers)
        except httpx.HTTPError as err:
            raise PowerDriverError(f"{action}: {err or type(err).__name__}") from err
        if resp.status_code != 200:
            raise PowerDriverError(f"{action}: HTTP {resp.status_code}")
        return resp.text

    async def get_state(self) -> str:
        text = await self._soap("GetDevicePowerState")
        match = re.search(r"<devicePower>\s*(\w+)\s*</devicePower>", text)
        if not match:
            raise PowerDriverError("GetDevicePowerState: no devicePower in response")
        return {"ON": ON, "OFF": STANDBY}.get(match.group(1).upper(), UNKNOWN)

    async def set_state(self, on: bool) -> None:
        await self._soap("SetDevicePowerState", f"<devicePower>{'ON' if on else 'OFF'}</devicePower>")


class PowerManager:
    def __init__(
        self,
        storage: Storage,
        players: PlayerService,
        client: HeosClient,
        bus: EventBus,
        *,
        poll_interval: float = 30.0,
        min_switch_interval: float = 10.0,
        settle_timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.storage = storage
        self.players = players
        self.bus = bus
        self.poll_interval = poll_interval
        self.min_switch_interval = min_switch_interval
        self.settle_timeout = settle_timeout
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self.states: dict[int, str] = {}
        self.errors: dict[int, str | None] = {}
        self._resolved: dict[int, str] = {}  # pid -> driver that "auto" resolved to
        self._last_switch: dict[int, float] = {}
        self._switch_locks: dict[int, asyncio.Lock] = {}
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        client.add_connection_listener(self._on_connection)
        client.add_event_listener(self._on_event)

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._stopping = False
        self._http = httpx.AsyncClient(timeout=4.0, transport=self._transport)
        self._task = asyncio.create_task(self._poll_loop(), name="power-poll")

    async def stop(self) -> None:
        # httpx can turn a cancellation that lands mid-connect into a plain
        # ConnectError, so the poll loop also checks an explicit flag.
        self._stopping = True
        self._wake.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._http:
            await self._http.aclose()

    # ---------------------------------------------------------------- drivers
    def _device_ip(self, pid: int) -> str | None:
        dev = self.storage.config.data.device(pid)
        live = self.players.players.get(pid)
        return (dev.ip_override if dev else None) or (live.ip if live else None) or (dev.ip if dev else None)

    def configured_driver(self, pid: int) -> str:
        dev = self.storage.config.data.device(pid)
        return dev.power.driver if dev else "auto"

    def driver_name(self, pid: int) -> str:
        """Effective driver: "auto" shows what it resolved to once a read succeeded."""
        name = self.configured_driver(pid)
        return self._resolved.get(pid, name) if name == "auto" else name

    def _make(self, name: str, pid: int) -> PowerDriver:
        if name == "none":
            return NoPowerDriver()
        ip = self._device_ip(pid)
        if not ip or self._http is None:
            raise PowerNotSupported("device address unknown or power manager not started")
        dev = self.storage.config.data.device(pid)
        config = dev.power.config if dev else {}
        if name == "upnp_act":
            return UpnpActDriver(ip, self._http, config)
        raise PowerNotSupported(f"power driver {name!r} is not implemented")

    def driver(self, pid: int) -> PowerDriver:
        name = self.driver_name(pid)
        return self._make("upnp_act" if name == "auto" else name, pid)

    def forget(self, pid: int) -> None:
        """Drop cached driver resolution (after a config change)."""
        self._resolved.pop(pid, None)
        self._wake.set()

    # ------------------------------------------------------------------ state
    def state(self, pid: int) -> str:
        return self.states.get(pid, UNKNOWN)

    async def refresh(self, pid: int) -> str:
        """Read the power state from the device; never switches anything."""
        configured = self.configured_driver(pid)
        try:
            state = await self.driver(pid).get_state()
            if configured == "auto" and pid not in self._resolved:
                self._resolved[pid] = "upnp_act"
                log.info("power: device %s supports upnp_act", pid)
            self.errors[pid] = None
        except (PowerDriverError, PowerNotSupported) as err:
            # "auto" stays unresolved on failure, so a device that was briefly
            # unreachable is not locked out of power control.
            state = UNKNOWN
            if self.errors.get(pid) != str(err):
                log.info("power state of %s unavailable: %s", pid, err)
            self.errors[pid] = str(err)
        self._set(pid, state)
        return state

    def _set(self, pid: int, state: str) -> None:
        if self.states.get(pid) != state:
            self.states[pid] = state
            self.bus.publish("power", pid, {"state": state})

    async def refresh_all(self) -> None:
        pids = set(self.players.players) | {d.pid for d in self.storage.config.data.devices}
        for pid in pids:
            if self.driver_name(pid) != "none" and self._device_ip(pid):
                await self.refresh(pid)

    async def _poll_loop(self) -> None:
        while not self._stopping:
            try:
                await self.refresh_all()
            except Exception:  # noqa: BLE001
                log.exception("power poll failed")
            if self._stopping:
                break
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.poll_interval)

    async def _on_connection(self, connected: bool) -> None:
        if connected:
            self._wake.set()

    async def _on_event(self, msg: HeosMessage) -> None:
        # Power changes from the remote show up on the CLI as a volume event
        # (standby reports volume 0 + mute on), so use it as a hint to re-check.
        if msg.command == "event/player_volume_changed":
            self._wake.set()

    # ---------------------------------------------------------------- switch
    async def set_power(self, pid: int, on: bool) -> dict[str, Any]:
        """Switch a device on or to standby, gently.

        Does nothing if the device is already in the requested state, and
        refuses a second switch within ``min_switch_interval`` seconds.
        """
        if pid not in self.players.players and self.storage.config.data.device(pid) is None:
            raise KeyError(pid)
        if self.driver_name(pid) == "none":
            raise PowerNotSupported("no power driver for this device; use the amp's remote")
        target = ON if on else STANDBY
        lock = self._switch_locks.setdefault(pid, asyncio.Lock())
        async with lock:
            current = await self.refresh(pid)
            if current == target:
                return {"state": current, "changed": False}
            since = time.monotonic() - self._last_switch.get(pid, -1e9)
            if since < self.min_switch_interval:
                raise PowerRateLimited(self.min_switch_interval - since)
            driver = self.driver(pid)
            log.info("power: switching device %s %s", pid, target)
            self._last_switch[pid] = time.monotonic()
            await driver.set_state(on)
            state = await self._settle(pid, target)
            return {"state": state, "changed": True}

    async def _settle(self, pid: int, target: str) -> str:
        """Poll the state (reads only) until it reaches ``target`` or times out."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settle_timeout
        state = UNKNOWN
        while loop.time() < deadline:
            await asyncio.sleep(0.5)
            state = await self.refresh(pid)
            if state == target:
                break
        return state
