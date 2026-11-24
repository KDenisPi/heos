"""REST endpoints, base path /api/v1 (section 6 of the spec)."""

from __future__ import annotations

import hmac
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .. import __version__
from .app import Services


def services(request: Request) -> Services:
    return request.app.state.services


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_heos_token: str | None = Header(default=None),
) -> None:
    """Optional shared token for write actions (NFR Security)."""
    token = request.app.state.services.settings.token
    if not token:
        return
    supplied = x_heos_token or (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="missing or wrong token")


router = APIRouter()
write = [Depends(require_token)]


# ------------------------------------------------------------------- models
class TransportBody(BaseModel):
    action: Literal["play", "pause", "stop", "next", "prev"]


class VolumeBody(BaseModel):
    level: int | None = Field(default=None, ge=0, le=100)
    step: int | None = Field(default=None, ge=-10, le=10)

    @model_validator(mode="after")
    def _one_of(self) -> "VolumeBody":
        if (self.level is None) == (self.step is None):
            raise ValueError("send exactly one of 'level' or 'step'")
        return self


class MuteBody(BaseModel):
    state: bool


class PlayModeBody(BaseModel):
    shuffle: bool | None = None
    repeat: Literal["off", "on_all", "on_one"] | None = None


class InputBody(BaseModel):
    input: str = Field(examples=["inputs/phono"])
    source_pid: int | None = None


class QueueItem(BaseModel):
    sid: int
    cid: str | None = None
    mid: str | None = None

    @model_validator(mode="after")
    def _needs_id(self) -> "QueueItem":
        if not self.cid and not self.mid:
            raise ValueError("an item needs a 'cid' (container) and/or a 'mid' (track)")
        return self


class QueueAddBody(BaseModel):
    items: list[QueueItem] = Field(min_length=1)
    mode: Literal["now", "next", "end", "replace"] = "end"


class QueueRemoveBody(BaseModel):
    qids: list[int] | None = None


class QueueMoveBody(BaseModel):
    qids: list[int] = Field(min_length=1)
    to: int = Field(ge=1, description="Destination queue id")


class QueuePlayBody(BaseModel):
    qid: int


class DevicePatch(BaseModel):
    ip_override: str | None = None
    power: dict[str, Any] | None = None
    default: bool | None = None


class PowerBody(BaseModel):
    state: Literal["on", "off"]


# ------------------------------------------------------------------- system
@router.get("/health", tags=["system"])
async def health(svc: Services = Depends(services)) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "heos": {
            "connected": svc.client.connected,
            "host": svc.client.host,
            "last_error": svc.client.last_error,
        },
        "ws_clients": svc.bus.subscriber_count,
    }


@router.get("/account", tags=["system"])
async def account(svc: Services = Depends(services)) -> dict[str, Any]:
    if svc.client.connected:
        await svc.players.refresh_account()
    return svc.players.account


# ------------------------------------------------------------------ devices
@router.get("/devices", tags=["devices"])
async def list_devices(svc: Services = Depends(services)) -> dict[str, Any]:
    return {"devices": svc.devices.list(), "last_discovery": svc.devices.last_discovery}


@router.post("/devices/discover", tags=["devices"], dependencies=write)
async def discover_devices(svc: Services = Depends(services)) -> dict[str, Any]:
    found = await svc.devices.discover()
    return {"found": [d.ip for d in found], "devices": svc.devices.list()}


@router.patch("/devices/{pid}", tags=["devices"], dependencies=write)
async def patch_device(pid: int, body: DevicePatch, svc: Services = Depends(services)) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"power": body.power, "default": body.default}
    if "ip_override" in body.model_fields_set:
        kwargs["ip_override"] = body.ip_override
    return await svc.devices.update(pid, **kwargs)


@router.get("/devices/{pid}/info", tags=["devices"])
async def device_info(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    if svc.client.connected and pid in svc.players.players:
        msg = await svc.client.command("player/get_player_info", {"pid": pid})
        info = msg.payload if isinstance(msg.payload, dict) else {}
        return {**svc.devices.describe(pid), "raw": info}
    return svc.devices.describe(pid)


@router.get("/devices/{pid}/firmware", tags=["devices"])
async def firmware(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    player = svc.players.get(pid)
    msg = await svc.client.command("player/check_update", {"pid": pid})
    payload = msg.payload if isinstance(msg.payload, dict) else {}
    return {
        "installed": player.version,
        "update_available": payload.get("update") == "update_exist",
        "how_to_install": "Front panel: Setup > General > Firmware > Check for Update",
    }


@router.get("/devices/{pid}/power", tags=["devices"])
async def get_power(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    """Read the power state from the device now (read only, F2.4; the "Test power" button)."""
    svc.devices.describe(pid)  # 404 for unknown devices
    await svc.power.refresh(pid)
    return svc.devices.describe(pid)["power"]


@router.post("/devices/{pid}/power", tags=["devices"], dependencies=write)
async def set_power(pid: int, body: PowerBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Switch on or to standby (F2.1). No-op if already there; 429 if switched < 10 s ago."""
    return await svc.power.set_power(pid, body.state == "on")


# ------------------------------------------------------------------ players
@router.get("/players", tags=["players"])
async def list_players(svc: Services = Depends(services)) -> dict[str, Any]:
    return {"players": [p.to_dict() for p in svc.players.players.values()]}


@router.get("/players/{pid}/state", tags=["players"])
async def player_state(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.players.get(pid).to_dict()


@router.post("/players/{pid}/transport", tags=["players"], dependencies=write)
async def transport(pid: int, body: TransportBody, svc: Services = Depends(services)) -> dict[str, str]:
    await svc.players.transport(pid, body.action)
    return {"action": body.action}


@router.put("/players/{pid}/volume", tags=["players"], dependencies=write)
async def volume(pid: int, body: VolumeBody, svc: Services = Depends(services)) -> dict[str, Any]:
    if body.level is not None:
        await svc.players.set_volume(pid, body.level)
    else:
        await svc.players.step_volume(pid, body.step or 0)
    player = svc.players.get(pid)
    return {"level": player.volume, "mute": player.mute}


@router.put("/players/{pid}/mute", tags=["players"], dependencies=write)
async def mute(pid: int, body: MuteBody, svc: Services = Depends(services)) -> dict[str, bool]:
    await svc.players.set_mute(pid, body.state)
    return {"state": body.state}


@router.put("/players/{pid}/play-mode", tags=["players"], dependencies=write)
async def play_mode(pid: int, body: PlayModeBody, svc: Services = Depends(services)) -> dict[str, Any]:
    await svc.players.set_play_mode(pid, body.shuffle, body.repeat)
    player = svc.players.get(pid)
    return {"shuffle": player.shuffle, "repeat": player.repeat}


@router.get("/players/{pid}/inputs", tags=["players"])
async def inputs(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    player = svc.players.get(pid)
    return {"current": player.input, "inputs": svc.images.localize_all(await svc.players.inputs(pid))}


@router.put("/players/{pid}/input", tags=["players"], dependencies=write)
async def select_input(pid: int, body: InputBody, svc: Services = Depends(services)) -> dict[str, str]:
    await svc.players.play_input(pid, body.input, body.source_pid)
    return {"input": body.input}


# -------------------------------------------------------------------- queue
@router.get("/players/{pid}/queue", tags=["queue"])
async def get_queue(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    items = await svc.players.queue(pid)
    return {"count": len(items), "items": items}


@router.post("/players/{pid}/queue", tags=["queue"], dependencies=write)
async def add_to_queue(pid: int, body: QueueAddBody, svc: Services = Depends(services)) -> dict[str, Any]:
    await svc.players.add_to_queue(pid, [i.model_dump() for i in body.items], body.mode)
    return {"added": len(body.items), "mode": body.mode}


@router.delete("/players/{pid}/queue", tags=["queue"], dependencies=write)
async def remove_from_queue(
    pid: int,
    body: QueueRemoveBody | None = Body(default=None),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    if body is None or body.qids is None:
        await svc.players.clear_queue(pid)
        return {"cleared": True}
    await svc.players.remove_from_queue(pid, body.qids)
    return {"removed": body.qids}


@router.post("/players/{pid}/queue/move", tags=["queue"], dependencies=write)
async def move_queue(pid: int, body: QueueMoveBody, svc: Services = Depends(services)) -> dict[str, Any]:
    await svc.players.move_queue(pid, body.qids, body.to)
    return {"moved": body.qids, "to": body.to}


@router.post("/players/{pid}/queue/play", tags=["queue"], dependencies=write)
async def play_queue_item(pid: int, body: QueuePlayBody, svc: Services = Depends(services)) -> dict[str, int]:
    await svc.players.play_queue_item(pid, body.qid)
    return {"qid": body.qid}


# ------------------------------------------------------------------ sources
@router.get("/sources", tags=["sources"])
async def sources(refresh: bool = False, svc: Services = Depends(services)) -> dict[str, Any]:
    return {"sources": svc.images.localize_all(await svc.players.music_sources(refresh))}


# ------------------------------------------------------------------- images
@router.get("/images/{key}", tags=["images"], response_class=FileResponse)
async def image(key: str, svc: Services = Depends(services)) -> FileResponse:
    """A device image (logo, icon, cover) served from the local cache."""
    path = await svc.images.get(key)
    return FileResponse(
        path,
        media_type=svc.images.media_type(key),
        headers={"Cache-Control": "public, max-age=604800"},
    )
