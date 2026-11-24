"""REST endpoints, base path /api/v1 (section 6 of the spec)."""

from __future__ import annotations

import hmac
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from urllib.parse import quote
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


class QueueSortBody(BaseModel):
    by: Literal["title", "artist", "album", "random", "track", "duration", "date_added"]
    order: Literal["asc", "desc"] = "asc"


class QueuePlayBody(BaseModel):
    qid: int


class DevicePatch(BaseModel):
    ip_override: str | None = None
    power: dict[str, Any] | None = None
    default: bool | None = None


class PlayStreamBody(BaseModel):
    sid: int
    mid: str
    name: str = ""
    cid: str | None = None


class AddFavoriteBody(BaseModel):
    sid: int
    mid: str = Field(min_length=1)
    name: str = Field(min_length=1)


class PlayFavoriteBody(BaseModel):
    mid: str = Field(description="Media id of the favorite; its current position is looked up on the device")


class PlaylistCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    from_queue: int | None = Field(default=None, description="pid whose current queue is saved")


class PlaylistPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    items: list[dict[str, Any]] | None = Field(default=None, description="New item list (remove / reorder)")


class PlaylistDuplicateBody(BaseModel):
    name: str | None = None


class PlaylistLoadBody(BaseModel):
    pid: int
    mode: Literal["now", "replace", "end", "append"] = "replace"


class PlaylistSortBody(BaseModel):
    by: Literal["title", "artist", "album", "random"]
    order: Literal["asc", "desc"] = "asc"


class PathStepBody(BaseModel):
    cid: str
    name: str


class ShortcutBody(BaseModel):
    sid: int
    path: list[PathStepBody] = Field(min_length=1, description="Breadcrumb from the server root to the folder")
    name: str | None = None


class LastFolderBody(BaseModel):
    path: list[PathStepBody]


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
    # A container is queued whole; if the amp rejects that, its tracks are added one by one.
    items = [i.model_dump() for i in body.items]
    added = await svc.players.add_to_queue(pid, items, body.mode, expand=svc.library.tracks_of)
    # Remember where each track came from, so the queue can be saved as a playlist (F4.1).
    await svc.playlists.remember_queued(items)
    return {"added": added, "mode": body.mode}


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


@router.post("/players/{pid}/queue/sort", tags=["queue"], dependencies=write)
async def sort_queue(pid: int, body: QueueSortBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Sort the queue on the device (F3.7): title, artist, album or random.

    HEOS does not report track number, duration or date added for queue items,
    so those keys answer 400. Ties keep their current order (album tracks stay
    in sequence). Progress is pushed as ``queue_sort`` WebSocket events.
    """
    try:
        return await svc.players.sort_queue(pid, body.by, body.order)
    except RuntimeError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


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


# ------------------------------------------------------------------ library
@router.get("/library/sources", tags=["library"])
async def library_sources(svc: Services = Depends(services)) -> dict[str, Any]:
    """Library home: HEOS Favorites, available streaming services (Amazon), DLNA servers (F6.5)."""
    return {"sources": await svc.library.sources()}


@router.post("/players/{pid}/play-stream", tags=["library"], dependencies=write)
async def play_stream(pid: int, body: PlayStreamBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Play an item whose ``play`` is "stream" (Amazon albums, playlists, stations). Replaces what is playing."""
    await svc.players.play_stream(pid, body.sid, body.mid, body.name, body.cid)
    return {"playing": body.name or body.mid}


@router.post("/players/{pid}/play-favorite", tags=["library"], dependencies=write)
async def play_favorite(pid: int, body: PlayFavoriteBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Play a HEOS Favorite (F6.4). The position is read fresh, so reordering in the app is safe."""
    svc.players.get(pid)
    preset = await svc.library.favorite_preset(body.mid)
    await svc.players.play_preset(pid, preset)
    return {"preset": preset}


@router.get("/favorites", tags=["library"])
async def favorites(svc: Services = Depends(services)) -> dict[str, Any]:
    """Media ids of the HEOS Favorites, to mark items and the playing station as favorites."""
    return {"mids": await svc.library.favorite_mids()}


@router.post("/favorites", tags=["library"], dependencies=write)
async def add_favorite(body: AddFavoriteBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Add a station / Amazon album / playlist to HEOS Favorites (stored in the HEOS account)."""
    await svc.library.add_favorite(body.sid, body.mid, body.name)
    svc.bus.publish("favorites_changed")
    return {"added": body.name}


@router.post("/players/{pid}/favorite-now-playing", tags=["library"], dependencies=write)
async def favorite_now_playing(pid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    """Add the station playing on this player to HEOS Favorites."""
    player = svc.players.get(pid)
    await svc.library.add_now_playing_favorite(pid)
    svc.bus.publish("favorites_changed")
    return {"added": player.now_playing.get("station") or player.now_playing.get("song") or ""}


@router.delete("/favorites", tags=["library"], dependencies=write)
async def remove_favorite(mid: str = Query(min_length=1), svc: Services = Depends(services)) -> dict[str, Any]:
    """Remove a station from HEOS Favorites. 404 if it is not a favorite."""
    await svc.library.remove_favorite(mid)
    svc.bus.publish("favorites_changed")
    return {"removed": mid}


@router.get("/library/servers", tags=["library"])
async def library_servers(svc: Services = Depends(services)) -> dict[str, Any]:
    """DLNA / UPnP media servers the HEOS device sees (F5.1)."""
    return {"servers": await svc.library.servers()}


@router.get("/sources/{sid}/browse", tags=["library"])
async def browse(
    sid: int,
    cid: str | None = None,
    start: int = Query(0, ge=0),
    count: int = Query(50, ge=1, le=100),
    refresh: bool = False,
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """One page of a source or container (F5.2). Cached for 10 minutes (F5.5).

    ``playable`` tells whether the container itself can be queued as a whole.
    """
    return await svc.library.browse(sid, cid, start, count, refresh=refresh)


@router.get("/sources/{sid}/search-criteria", tags=["library"])
async def search_criteria(sid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    return {"criteria": await svc.library.search_criteria(sid)}


@router.get("/sources/{sid}/search", tags=["library"])
async def search(
    sid: int,
    q: str = Query(min_length=1),
    criteria: int = Query(3, description="Search criteria id (scid), see /search-criteria"),
    start: int = Query(0, ge=0),
    count: int = Query(50, ge=1, le=100),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """Search a source (F5.4). 501 when the server does not support search."""
    return await svc.library.search(sid, q, criteria, start, count)


@router.get("/library/shortcuts", tags=["library"])
async def shortcuts(svc: Services = Depends(services)) -> dict[str, Any]:
    """Pinned folders (F5.7)."""
    return {"shortcuts": svc.library.shortcuts()}


@router.post("/library/shortcuts", tags=["library"], dependencies=write)
async def add_shortcut(body: ShortcutBody, svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.library.add_shortcut(body.sid, [p.model_dump() for p in body.path], body.name)


@router.delete("/library/shortcuts/{shortcut_id}", tags=["library"], dependencies=write)
async def remove_shortcut(shortcut_id: int, svc: Services = Depends(services)) -> dict[str, Any]:
    svc.library.remove_shortcut(shortcut_id)
    return {"removed": shortcut_id}


@router.get("/library/last-folder/{sid}", tags=["library"])
async def get_last_folder(sid: int, svc: Services = Depends(services)) -> dict[str, Any]:
    """Breadcrumb of the folder last browsed on this server, to reopen it (F5.7)."""
    return {"sid": sid, "path": svc.library.last_folder(sid)}


@router.put("/library/last-folder/{sid}", tags=["library"], dependencies=write)
async def set_last_folder(sid: int, body: LastFolderBody, svc: Services = Depends(services)) -> dict[str, Any]:
    svc.library.set_last_folder(sid, [p.model_dump() for p in body.path])
    return {"sid": sid, "path": svc.library.last_folder(sid)}


# ---------------------------------------------------------------- playlists
@router.get("/playlists", tags=["playlists"])
async def list_playlists(svc: Services = Depends(services)) -> dict[str, Any]:
    """Local playlists (M3U8 files on the server), with item and unresolved counts (F4.2)."""
    return {"playlists": svc.playlists.list()}


@router.post("/playlists", tags=["playlists"], dependencies=write)
async def create_playlist(body: PlaylistCreateBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Create a playlist; with ``from_queue`` it saves that player's current queue (F4.1). 409 if the name exists."""
    if body.from_queue is not None:
        return await svc.playlists.save_queue(body.from_queue, body.name)
    return svc.playlists.create(body.name).summary()


@router.post("/playlists/import", tags=["playlists"], dependencies=write)
async def import_playlist(request: Request, name: str | None = None, svc: Services = Depends(services)) -> dict[str, Any]:
    """Import an .m3u8 file sent as the request body (F4.5)."""
    body = await request.body()
    if len(body) > 5 * 1024 * 1024:
        raise ValueError("playlist file too large")
    return svc.playlists.import_text(body.decode("utf-8", errors="replace"), name).summary()


@router.get("/playlists/{playlist_id}", tags=["playlists"])
async def get_playlist(playlist_id: str, svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.playlists.get(playlist_id).to_dict()


@router.patch("/playlists/{playlist_id}", tags=["playlists"], dependencies=write)
async def patch_playlist(playlist_id: str, body: PlaylistPatchBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Rename, or replace the item list (remove / reorder) without playing (F4.2, F4.4)."""
    if body.items is not None:
        svc.playlists.update_items(playlist_id, body.items)
    if body.name is not None:
        return svc.playlists.rename(playlist_id, body.name).to_dict()
    return svc.playlists.get(playlist_id).to_dict()


@router.delete("/playlists/{playlist_id}", tags=["playlists"], dependencies=write)
async def delete_playlist(playlist_id: str, svc: Services = Depends(services)) -> dict[str, Any]:
    svc.playlists.delete(playlist_id)
    return {"deleted": playlist_id}


@router.post("/playlists/{playlist_id}/duplicate", tags=["playlists"], dependencies=write)
async def duplicate_playlist(
    playlist_id: str, body: PlaylistDuplicateBody = Body(default=PlaylistDuplicateBody()), svc: Services = Depends(services)
) -> dict[str, Any]:
    return svc.playlists.duplicate(playlist_id, body.name).summary()


@router.post("/playlists/{playlist_id}/sort", tags=["playlists"], dependencies=write)
async def sort_playlist(playlist_id: str, body: PlaylistSortBody, svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.playlists.sort(playlist_id, body.by, body.order).to_dict()


@router.post("/playlists/{playlist_id}/load", tags=["playlists"], dependencies=write)
async def load_playlist(playlist_id: str, body: PlaylistLoadBody, svc: Services = Depends(services)) -> dict[str, Any]:
    """Put the playlist into the HEOS queue (F4.3). Unresolved tracks are skipped and counted."""
    return await svc.playlists.load(playlist_id, body.pid, body.mode)


@router.get("/playlists/{playlist_id}/export", tags=["playlists"])
async def export_playlist(playlist_id: str, svc: Services = Depends(services)) -> Response:
    """Download the .m3u8 file (F4.5)."""
    filename, text = svc.playlists.export(playlist_id)
    return Response(
        content=text.encode("utf-8"),
        media_type="audio/x-mpegurl; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=playlist.m3u8; filename*=UTF-8''{quote(filename)}"},
    )
