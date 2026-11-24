"""Music library: DLNA servers and other HEOS sources (F5, and the base for F6).

All browsing goes through the HEOS CLI: the amp talks to the media servers, the
service only asks it for pages. Facts measured on the PM7000N with a NAS:

* ``browse/browse?sid=1024`` lists the DLNA servers (each with its own sid);
* a server's root is Music / Videos / Photos; Music offers views (Songs,
  Artist, Album, Folder, ...); "Folder" mirrors the NAS shares;
* paging uses ``range=start,end``; the reply message carries ``count``;
* a folder that holds tracks is listed as ``playable: no`` by its parent, but
  browsing it returns option 21 "Playable Container", and
  ``add_to_queue`` with its cid queues all its tracks in order;
* this NAS answers every ``browse/search`` with eid 12 (syserrno -9), although
  ``get_search_criteria`` lists Artist / Album / Track.

Amazon Music (sid 13) and HEOS Favorites (sid 1028), measured the same way:

* Amazon menus are containers, but every album, playlist and station is a
  single ``station`` item (mid ``catalog/albums/<id>/#chunk``): it cannot be
  browsed into or queued, it plays with ``browse/play_stream``;
* Amazon has no search criteria and search fails with eid 12;
* the root's upsell banner fails with "User account error" and is hidden;
* Amazon pages take 0.7-2.2 s, so the cache matters;
* Favorites are stations too and play with ``browse/play_preset`` (1-based).
  ``browse/set_service_option`` option 19 adds a station (sid + mid + name, or
  the station playing on a pid) to HEOS Favorites, option 20 removes one (mid).
  Favorites live in the HEOS account, so the official app sees them too.
* Amazon "My Music" albums are real containers holding ``song`` items,
  without option 21, yet ``add_to_queue`` with the album's cid queues all its
  tracks (13 of 13 on the PM7000N). So a container is always tried whole
  first; only if the amp rejects it are its tracks (``tracks_of``) added one
  by one.

Every item gets a ``play`` field telling the UI how it can be played:
``queue`` (add_to_queue modes), ``stream`` (play_stream, replaces what is
playing) or ``favorite`` (play_preset).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

from ..heos.client import HeosClient
from ..heos.protocol import HeosCommandError, HeosMessage
from ..storage import FolderShortcut, PathStep, Storage
from .images import ImageCache

log = logging.getLogger(__name__)

LOCAL_MUSIC_SID = 1024
FAVORITES_SID = 1028
HIDDEN_CID_PREFIXES = ("upsell-banner",)  # Amazon's "NEW with Prime" entry fails with an account error
PLAYABLE_CONTAINER_OPTION = 21
BROWSE_TIMEOUT = 30.0
MAX_PAGE = 100  # the CLI returns at most 50-100 records per request


class SearchNotSupported(Exception):
    """The source answered a search with a system error (seen on DLNA servers)."""


def _flag(value: Any) -> bool:
    return str(value).lower() in ("yes", "true", "1")


def _has_option(options: Any, option_id: int) -> bool:
    for group in options or []:
        if isinstance(group, dict):
            for entries in group.values():
                if isinstance(entries, list) and any(
                    isinstance(e, dict) and str(e.get("id")) == str(option_id) for e in entries
                ):
                    return True
    return False


class LibraryService:
    def __init__(self, client: HeosClient, storage: Storage, images: ImageCache, *,
                 ttl: float = 600.0, max_entries: int = 500) -> None:
        self.client = client
        self.storage = storage
        self.images = images
        self.ttl = ttl
        self.max_entries = max_entries
        self._cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()
        client.add_event_listener(self._on_event)

    async def _on_event(self, msg: HeosMessage) -> None:
        if msg.command == "event/sources_changed":
            self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()

    # -------------------------------------------------------------- helpers
    def _normalize(self, item: dict[str, Any], sid: int) -> dict[str, Any]:
        container = _flag(item.get("container"))
        out: dict[str, Any] = {
            "sid": int(item.get("sid", sid)) if str(item.get("sid", sid)).lstrip("-").isdigit() else sid,
            "name": item.get("name", ""),
            "type": item.get("type", "container" if container else "song"),
            "container": container,
            "playable": _flag(item.get("playable")),
            "cid": item.get("cid"),
            "mid": item.get("mid"),
            "artist": item.get("artist") or "",
            "album": item.get("album") or "",
            "album_id": item.get("album_id") or None,  # Amazon sends ""
            "image_url": item.get("image_url") or item.get("image_uri") or "",
        }
        if container:
            out["play"] = "queue"
        elif sid == FAVORITES_SID:
            out["play"] = "favorite"
        elif out["type"] == "station":
            out["play"] = "stream"
        else:
            out["play"] = "queue"
        # Stations, Amazon albums and playlists can be HEOS Favorites (option 19).
        out["can_favorite"] = out["play"] in ("stream", "favorite") and bool(out["mid"])
        return self.images.localize(out)

    async def _browse_raw(self, params: dict[str, Any]) -> HeosMessage:
        return await self.client.command("browse/browse", params, timeout=BROWSE_TIMEOUT)

    # ------------------------------------------------------------- servers
    async def servers(self) -> list[dict[str, Any]]:
        """DLNA servers the HEOS device sees (F5.1)."""
        msg = await self._browse_raw({"sid": LOCAL_MUSIC_SID})
        result = []
        for item in msg.payload or []:
            entry = self._normalize(item, LOCAL_MUSIC_SID)
            entry["sid"] = int(item["sid"])
            entry["type"] = item.get("type", "dlna_server")
            entry["container"] = True
            result.append(entry)
        return result

    # -------------------------------------------------------------- browse
    async def browse(self, sid: int, cid: str | None = None, start: int = 0, count: int = 50,
                     *, refresh: bool = False) -> dict[str, Any]:
        """One page of a container (F5.2), cached for ``ttl`` seconds (F5.5)."""
        if start < 0 or not 1 <= count <= MAX_PAGE:
            raise ValueError(f"start must be >= 0 and count 1..{MAX_PAGE}")
        key = ("browse", sid, cid, start, count)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and not refresh and now - cached[0] < self.ttl:
            self._cache.move_to_end(key)
            return cached[1]
        params: dict[str, Any] = {"sid": sid, "cid": cid, "range": f"{start},{start + count - 1}"}
        msg = await self._browse_raw(params)
        raw = [it for it in (msg.payload or []) if not str(it.get("cid") or "").startswith(HIDDEN_CID_PREFIXES)]
        hidden = len(msg.payload or []) - len(raw)
        items = [self._normalize(it, sid) for it in raw]
        total = max(0, int(msg.params.get("count", len(items)) or 0) - hidden)
        result = {
            "sid": sid,
            "cid": cid,
            "start": start,
            "count": len(items),
            "total": total,
            # Option 21: the container being browsed can be queued as a whole.
            "playable": _has_option(msg.options, PLAYABLE_CONTAINER_OPTION),
            "items": items,
        }
        self._cache[key] = (now, result)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return result

    async def sources(self) -> list[dict[str, Any]]:
        """Library home (F6.5): Favorites, available streaming services, DLNA servers.

        Any HEOS service that is signed in shows up here; adding one is
        configuration in the HEOS account, not new code.
        """
        key = ("sources",)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.ttl:
            return cached[1]  # type: ignore[return-value]
        msg = await self.client.command("browse/get_music_sources")
        result: list[dict[str, Any]] = []
        for src in msg.payload or []:
            sid = int(src.get("sid", 0))
            available = _flag(src.get("available", "true"))
            if sid == FAVORITES_SID and available:
                result.append({"sid": sid, "name": src.get("name") or "Favorites", "kind": "favorites",
                               "image_url": src.get("image_url") or ""})
            elif src.get("type") == "music_service" and available:
                result.append({"sid": sid, "name": src.get("name", ""), "kind": "service",
                               "image_url": src.get("image_url") or "",
                               "account": src.get("service_username")})
        for server in await self.servers():
            result.append({"sid": server["sid"], "name": server["name"], "kind": "dlna",
                           "image_url": server.get("image_url_remote") or ""})
        result = [self.images.localize(r) for r in result]
        self._cache[key] = (time.monotonic(), result)  # type: ignore[assignment]
        return result

    async def tracks_of(self, item: dict[str, Any], limit: int = 500) -> list[dict[str, Any]]:
        """The queueable tracks of a container, as add_to_queue items (cid + mid), in order.

        Used when the amp rejects queueing the container whole. Raises
        ``ValueError`` if it holds nothing that can be queued.
        """
        sid, cid = int(item["sid"]), str(item["cid"])
        tracks: list[dict[str, Any]] = []
        start = 0
        while True:
            page = await self.browse(sid, cid, start, MAX_PAGE)
            tracks += [
                {"sid": sid, "cid": t.get("album_id") or cid, "mid": t["mid"]}
                for t in page["items"]
                if not t["container"] and t["play"] == "queue" and t.get("mid")
            ]
            start += page["count"]
            if not page["count"] or start >= page["total"] or len(tracks) >= limit:
                break
        if not tracks:
            raise ValueError("nothing in this folder can be added to the queue; open it and pick an item")
        return tracks[:limit]

    # ------------------------------------------------------- HEOS Favorites
    def _forget_favorites(self) -> None:
        for key in [k for k in self._cache if k[:2] == ("browse", FAVORITES_SID)]:
            del self._cache[key]

    async def favorite_mids(self) -> list[str]:
        """Media ids of the current HEOS Favorites (cached like any browse page)."""
        page = await self.browse(FAVORITES_SID, None, 0, MAX_PAGE)
        return [str(i["mid"]) for i in page["items"] if i.get("mid")]

    async def add_favorite(self, sid: int, mid: str, name: str) -> None:
        """Add a station / Amazon album / playlist to HEOS Favorites (option 19)."""
        if not mid or not name:
            raise ValueError("a favorite needs a media id and a name")
        await self.client.command("browse/set_service_option",
                                  {"sid": sid, "option": 19, "mid": mid, "name": name}, timeout=BROWSE_TIMEOUT)
        self._forget_favorites()

    async def add_now_playing_favorite(self, pid: int) -> None:
        """Add the station playing on ``pid`` to HEOS Favorites (option 19 with pid)."""
        await self.client.command("browse/set_service_option", {"option": 19, "pid": pid}, timeout=BROWSE_TIMEOUT)
        self._forget_favorites()

    async def remove_favorite(self, mid: str) -> None:
        """Remove a station from HEOS Favorites (option 20)."""
        if mid not in await self.favorite_mids():
            raise KeyError(mid)
        await self.client.command("browse/set_service_option", {"option": 20, "mid": mid}, timeout=BROWSE_TIMEOUT)
        self._forget_favorites()

    async def favorite_preset(self, mid: str) -> int:
        """Current 1-based position of a favorite, read fresh, for play_preset."""
        page = await self.browse(FAVORITES_SID, None, 0, MAX_PAGE, refresh=True)
        for index, item in enumerate(page["items"], 1):
            if item.get("mid") == mid:
                return index
        raise KeyError(mid)

    # -------------------------------------------------------------- search
    async def search_criteria(self, sid: int) -> list[dict[str, Any]]:
        try:
            msg = await self.client.command("browse/get_search_criteria", {"sid": sid})
        except HeosCommandError as err:
            log.info("no search criteria for sid %s: %s", sid, err)
            return []
        return [
            {"scid": int(c["scid"]), "name": c.get("name", ""), "playable": _flag(c.get("playable")),
             "cid": c.get("cid")}
            for c in (msg.payload or [])
            if str(c.get("scid", "")).isdigit()
        ]

    async def search(self, sid: int, query: str, scid: int, start: int = 0, count: int = 50) -> dict[str, Any]:
        """Search a source (F5.4, F6.2). Raises ``SearchNotSupported`` on a system error."""
        query = query.strip()
        if not query:
            raise ValueError("empty search")
        if not 1 <= count <= MAX_PAGE:
            raise ValueError(f"count must be 1..{MAX_PAGE}")
        try:
            msg = await self.client.command(
                "browse/search",
                {"sid": sid, "search": query, "scid": scid, "range": f"{start},{start + count - 1}"},
                timeout=BROWSE_TIMEOUT,
            )
        except HeosCommandError as err:
            if err.eid == 12:
                raise SearchNotSupported("this server does not support search; filter a folder instead") from err
            raise
        items = [self._normalize(it, sid) for it in (msg.payload or [])]
        return {"sid": sid, "query": query, "scid": scid, "start": start, "count": len(items),
                "total": int(msg.params.get("count", len(items)) or 0), "items": items}

    # ---------------------------------------------- shortcuts and last folder
    def shortcuts(self) -> list[dict[str, Any]]:
        return [dict(s.model_dump(), id=i) for i, s in enumerate(self.storage.config.data.folder_shortcuts)]

    def add_shortcut(self, sid: int, path: list[dict[str, str]], name: str | None = None) -> dict[str, Any]:
        steps = [PathStep(**step) for step in path]
        if not steps:
            raise ValueError("a shortcut needs a folder path")
        cfg = self.storage.config.data
        last = steps[-1]
        existing = next((s for s in cfg.folder_shortcuts if s.sid == sid and s.cid == last.cid), None)
        if existing is None:
            existing = FolderShortcut(name=name or last.name, sid=sid, cid=last.cid, path=steps)
            cfg.folder_shortcuts.append(existing)
            self.storage.config.save()
        return dict(existing.model_dump(), id=cfg.folder_shortcuts.index(existing))

    def remove_shortcut(self, shortcut_id: int) -> None:
        cfg = self.storage.config.data
        if not 0 <= shortcut_id < len(cfg.folder_shortcuts):
            raise KeyError(shortcut_id)
        cfg.folder_shortcuts.pop(shortcut_id)
        self.storage.config.save()

    def last_folder(self, sid: int) -> list[dict[str, str]]:
        return [s.model_dump() for s in self.storage.state.data.last_folder.get(str(sid), [])]

    def set_last_folder(self, sid: int, path: list[dict[str, str]]) -> None:
        steps = [PathStep(**step) for step in path]
        state = self.storage.state.data
        if [s.model_dump() for s in state.last_folder.get(str(sid), [])] == [s.model_dump() for s in steps]:
            return
        state.last_folder[str(sid)] = steps
        self.storage.state.save()
