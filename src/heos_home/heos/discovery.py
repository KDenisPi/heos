"""SSDP discovery of HEOS devices (F1.1).

Sends an M-SEARCH for ``urn:schemas-denon-com:device:ACT-Denon:1`` and collects
the IP of every device that answers. Names and player ids come later from the
CLI (``player/get_players``), so discovery only has to find reachable hosts.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
HEOS_ST = "urn:schemas-denon-com:device:ACT-Denon:1"


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    ip: str
    location: str | None = None
    usn: str | None = None
    server: str | None = None


def _parse_response(data: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in data.decode("utf-8", errors="replace").split("\r\n")[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    return headers


class _SsdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, st: str) -> None:
        self.st = st
        self.found: dict[str, DiscoveredDevice] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # type: ignore[override]
        headers = _parse_response(data)
        if headers.get("st", "").lower() != self.st.lower():
            return
        location = headers.get("location")
        ip = urlparse(location).hostname if location else None
        ip = ip or addr[0]
        if ip not in self.found:
            log.info("SSDP: found HEOS device at %s", ip)
        self.found[ip] = DiscoveredDevice(ip, location, headers.get("usn"), headers.get("server"))


async def discover(timeout: float = 3.0, st: str = HEOS_ST, repeats: int = 2) -> list[DiscoveredDevice]:
    """Return the HEOS devices that answered an SSDP M-SEARCH within ``timeout``."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.bind(("", 0))
    sock.setblocking(False)
    transport, protocol = await loop.create_datagram_endpoint(lambda: _SsdpProtocol(st), sock=sock)
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {max(1, int(timeout) - 1)}\r\n"
        f"ST: {st}\r\n\r\n"
    ).encode()
    try:
        for _ in range(repeats):
            transport.sendto(request, (SSDP_ADDR, SSDP_PORT))
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
    except OSError as err:
        log.warning("SSDP discovery failed: %s", err)
    finally:
        transport.close()
    return sorted(protocol.found.values(), key=lambda d: d.ip)
