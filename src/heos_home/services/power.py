"""Pluggable power drivers (F2.5).

The PM7000N's power path is undocumented (risk R1), so v1 ships only the
``none`` driver; the amp's own remote handles power. Real drivers
(``heos_hidden``, ``http_8080``, ``https_10443``) are added here once the
phase-0 traffic capture shows which path works.
"""

from __future__ import annotations

from typing import Any, Protocol


class PowerNotSupported(Exception):
    pass


class PowerDriver(Protocol):
    name: str

    async def get_state(self) -> str:
        """Return "on", "standby" or "unknown"."""

    async def set_state(self, state: str) -> None:
        """Switch to "on" or "off"."""


class NoPowerDriver:
    name = "none"

    def __init__(self, ip: str | None, config: dict[str, Any]) -> None:
        self.ip = ip

    async def get_state(self) -> str:
        return "unknown"

    async def set_state(self, state: str) -> None:
        raise PowerNotSupported("no power driver configured for this device; use the amp's remote")


DRIVERS: dict[str, type] = {"none": NoPowerDriver}
KNOWN_DRIVERS = ("none", "heos_hidden", "http_8080", "https_10443")


def make_driver(name: str, ip: str | None, config: dict[str, Any]) -> PowerDriver:
    cls = DRIVERS.get(name)
    if cls is None:
        raise PowerNotSupported(f"power driver {name!r} is not implemented yet")
    return cls(ip, config)
