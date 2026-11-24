"""Device registry: discovery, manual IP overrides, choice of the CLI host (F1, F8.1).

All players are reached through one CLI connection to one device
(``player/get_players`` lists every player on the LAN). This service decides
which device to connect to and merges three views of each device: config.json,
SSDP results and the live player list.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..heos.client import HeosClient
from ..heos.discovery import DiscoveredDevice, discover
from ..settings import Settings
from ..storage import DeviceConfig, PowerConfig, Storage
from .events import EventBus
from .players import PlayerService
from .power import KNOWN_DRIVERS, PowerManager

log = logging.getLogger(__name__)


class DeviceService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        client: HeosClient,
        players: PlayerService,
        bus: EventBus,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.client = client
        self.players = players
        self.bus = bus
        self.discovered: dict[str, DiscoveredDevice] = {}
        self.last_discovery: float | None = None
        self._discover_lock = asyncio.Lock()
        self._discovery_task: asyncio.Task[Any] | None = None
        self.power: PowerManager | None = None  # set by build_services
        # Registered after PlayerService, so the player list is fresh when this runs.
        client.add_connection_listener(self._on_connection)

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        host = self.pick_host()
        if host:
            await self.client.set_host(host)
        if self.settings.discovery:
            # Do not hold up startup (< 10 s target): discovery runs in background.
            self._discovery_task = asyncio.create_task(self.discover(), name="ssdp-discovery")

    async def stop(self) -> None:
        if self._discovery_task and not self._discovery_task.done():
            self._discovery_task.cancel()

    def pick_host(self) -> str | None:
        """Choose the device to hold the CLI connection to.

        Order: default device (override, then last known IP), manual hosts from
        the environment, other overrides, the last host that worked, SSDP results.
        """
        cfg = self.storage.config.data
        candidates: list[str | None] = []
        default = cfg.device(cfg.default_pid) if cfg.default_pid is not None else None
        if default:
            candidates += [default.ip_override, default.ip]
        candidates += self.settings.hosts
        candidates += [d.ip_override for d in cfg.devices]
        candidates.append(self.storage.state.data.last_host)
        candidates += list(self.discovered)
        return next((c for c in candidates if c), None)

    async def discover(self) -> list[DiscoveredDevice]:
        """Run SSDP discovery (F1.1, F1.5); connect if not connected yet."""
        async with self._discover_lock:
            found = await discover(self.settings.discovery_timeout)
            self.discovered = {d.ip: d for d in found}
            self.last_discovery = time.time()
            log.info("discovery finished: %d device(s)", len(found))
            if not self.client.connected:
                host = self.pick_host()
                if host and host != self.client.host:
                    await self.client.set_host(host)
            else:
                await self.players.refresh_players()
            self.bus.publish("devices_changed")
            return found

    # ------------------------------------------------------------ persistence
    async def _on_connection(self, connected: bool) -> None:
        if not connected:
            return
        cfg = self.storage.config.data
        changed = False
        for player in self.players.players.values():
            dev = cfg.device(player.pid)
            if dev is None:
                cfg.devices.append(
                    DeviceConfig(pid=player.pid, name=player.name, model=player.model, ip=player.ip)
                )
                changed = True
            elif (dev.name, dev.model, dev.ip) != (player.name, player.model, player.ip or dev.ip):
                dev.name, dev.model, dev.ip = player.name, player.model, player.ip or dev.ip
                changed = True
        if cfg.default_pid is None and self.players.players:
            cfg.default_pid = next(iter(self.players.players))
            changed = True
        if changed:
            self.storage.config.save()
        if self.storage.state.data.last_host != self.client.host:
            self.storage.state.data.last_host = self.client.host
            self.storage.state.save()

    # ------------------------------------------------------------------ views
    def list(self) -> list[dict[str, Any]]:
        cfg = self.storage.config.data
        pids = list(dict.fromkeys([*self.players.players, *(d.pid for d in cfg.devices)]))
        return [self.describe(pid) for pid in pids]

    def describe(self, pid: int) -> dict[str, Any]:
        cfg = self.storage.config.data
        dev = cfg.device(pid)
        live = self.players.players.get(pid)
        if dev is None and live is None:
            raise KeyError(pid)
        ip = (live.ip if live else None) or (dev.ip if dev else None)
        return {
            "pid": pid,
            "name": (live.name if live else None) or (dev.name if dev else ""),
            "model": (live.model if live else None) or (dev.model if dev else ""),
            "ip": ip,
            "ip_override": dev.ip_override if dev else None,
            "firmware": live.version if live else None,
            "network": live.network if live else None,
            "serial": live.serial if live else None,
            "online": bool(live and live.online),
            "connection_host": bool(self.client.connected and self.client.host in {ip, dev and dev.ip_override}),
            "default": cfg.default_pid == pid,
            "power": self._power_info(pid, dev),
        }

    def _power_info(self, pid: int, dev: DeviceConfig | None) -> dict[str, Any]:
        if self.power is None:
            return {"driver": dev.power.driver if dev else "auto", "effective_driver": None,
                    "state": "unknown", "error": None}
        return {
            "driver": self.power.configured_driver(pid),
            "effective_driver": self.power.driver_name(pid),
            "state": self.power.state(pid),
            "error": self.power.errors.get(pid),
        }

    async def update(
        self,
        pid: int,
        *,
        ip_override: str | None | object = ...,
        power: dict[str, Any] | None = None,
        default: bool | None = None,
    ) -> dict[str, Any]:
        """PATCH /devices/{pid} (F1.2, F2.5)."""
        cfg = self.storage.config.data
        dev = cfg.device(pid)
        if dev is None:
            live = self.players.players.get(pid)
            if live is None:
                raise KeyError(pid)
            dev = DeviceConfig(pid=pid, name=live.name, model=live.model, ip=live.ip)
            cfg.devices.append(dev)
        reconnect = False
        if ip_override is not ...:
            old = dev.address
            dev.ip_override = ip_override or None  # type: ignore[assignment]
            reconnect = old != dev.address and (self.client.host == old or not self.client.connected)
        if power is not None:
            driver = power.get("driver", dev.power.driver)
            if driver not in KNOWN_DRIVERS:
                raise ValueError(f"power driver must be one of {KNOWN_DRIVERS}")
            dev.power = PowerConfig(driver=driver, config=power.get("config", dev.power.config))
            if self.power:
                self.power.forget(pid)
        if default:
            cfg.default_pid = pid
        self.storage.config.save()
        if reconnect and dev.address:
            await self.client.set_host(dev.address)
        self.bus.publish("devices_changed")
        return self.describe(pid)
