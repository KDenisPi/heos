"""Local playlists (F4): one extended-M3U8 file per playlist in <data dir>/playlists.

A HEOS queue item has no source id, so a playlist must record, at save time,
where each track came from (sid + container cid + mid). Two ways:

* ``SourceMemory``: every time this service queues something, it remembers
  mid -> (sid, cid) for each track (persisted in cache/track-sources.json);
* for tracks queued by other apps, the item's ``album_id`` container is looked
  up on each DLNA server (19 of 19 resolved in 0.9 s on the PM7000N + NAS).

Tracks that cannot be traced are still saved (title, artist, album) but marked
unresolved; loading skips them and says how many.

File format (section 5 of the spec)::

    #EXTM3U
    #PLAYLIST:Bach Cantatas
    #EXTINF:-1,J.S. Bach - Cantata BWV 140: I. Chorus
    #EXTALB:Cantatas Vol. 1
    #EXTHEOS:{"sid":111,"cid":"64$1$3","mid":"64$1$3$1","title":"...","artist":"...","album":"..."}
    heos://111/64%241%243/64%241%243%241

The HEOS queue does not report durations, so #EXTINF carries -1.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..storage import Storage, atomic_write
from .events import EventBus
from .library import LibraryService
from .players import PlayerService
from .queue_sort import sort_order

log = logging.getLogger(__name__)

MAX_NAME = 120
LOAD_MODES = ("now", "replace", "end")


class PlaylistExists(Exception):
    pass


# ----------------------------------------------------------------- model
@dataclass
class PlaylistItem:
    title: str
    artist: str = ""
    album: str = ""
    sid: int | None = None
    cid: str | None = None
    mid: str | None = None
    image_url: str = ""

    @property
    def resolved(self) -> bool:
        return self.sid is not None and bool(self.cid) and bool(self.mid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "artist": self.artist, "album": self.album, "sid": self.sid,
            "cid": self.cid, "mid": self.mid, "image_url": self.image_url, "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlaylistItem":
        sid = d.get("sid")
        return cls(
            title=str(d.get("title") or d.get("song") or ""),
            artist=str(d.get("artist") or ""),
            album=str(d.get("album") or ""),
            sid=int(sid) if sid is not None and str(sid).lstrip("-").isdigit() else None,
            cid=d.get("cid") or None,
            mid=d.get("mid") or None,
            image_url=str(d.get("image_url") or ""),
        )


@dataclass
class Playlist:
    id: str
    name: str
    items: list[PlaylistItem] = field(default_factory=list)
    modified: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "count": len(self.items),
            "unresolved": sum(not i.resolved for i in self.items),
            "modified": self.modified,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "items": [i.to_dict() for i in self.items]}


# --------------------------------------------------------------- M3U8 I/O
def _clean(text: str) -> str:
    return " ".join(str(text).split())


def render_m3u8(name: str, items: list[PlaylistItem]) -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{_clean(name)}"]
    for it in items:
        label = f"{_clean(it.artist)} - {_clean(it.title)}" if it.artist else _clean(it.title)
        lines.append(f"#EXTINF:-1,{label}")
        if it.album:
            lines.append(f"#EXTALB:{_clean(it.album)}")
        if it.artist:
            lines.append(f"#EXTART:{_clean(it.artist)}")
        heos = {"sid": it.sid, "cid": it.cid, "mid": it.mid, "title": it.title, "artist": it.artist,
                "album": it.album}
        if it.image_url:
            heos["image_url"] = it.image_url
        lines.append("#EXTHEOS:" + json.dumps(heos, ensure_ascii=False, separators=(",", ":")))
        if it.resolved:
            lines.append(f"heos://{it.sid}/{quote(str(it.cid), safe='')}/{quote(str(it.mid), safe='')}")
        else:
            lines.append(f"heos://unresolved/{quote(it.mid or it.title, safe='')}")
    return "\n".join(lines) + "\n"


def parse_m3u8(text: str, fallback_name: str) -> tuple[str, list[PlaylistItem]]:
    """Parse extended M3U. #EXTHEOS carries the ids; other players' files load as unresolved items."""
    name = fallback_name
    items: list[PlaylistItem] = []
    pending: dict[str, Any] = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#PLAYLIST:"):
            name = line[len("#PLAYLIST:"):].strip() or name
        elif line.startswith("#EXTINF:"):
            label = line.split(",", 1)[1].strip() if "," in line else ""
            artist, sep, title = label.partition(" - ")
            pending.update({"title": title if sep else label, "artist": artist if sep else ""})
        elif line.startswith("#EXTALB:"):
            pending["album"] = line[len("#EXTALB:"):].strip()
        elif line.startswith("#EXTART:"):
            pending["artist"] = line[len("#EXTART:"):].strip()
        elif line.startswith("#EXTHEOS:"):
            try:
                pending.update({k: v for k, v in json.loads(line[len("#EXTHEOS:"):]).items() if v is not None})
            except ValueError:
                log.warning("bad #EXTHEOS line ignored: %.80s", line)
        elif line.startswith("#"):
            continue
        else:  # the location line closes an entry
            if "title" not in pending:
                pending["title"] = Path(line).stem if not line.startswith("heos://") else line
            items.append(PlaylistItem.from_dict(pending))
            pending = {}
    return name, items


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", name.casefold(), flags=re.UNICODE).strip("-_")
    return slug[:80] or "playlist"


# ---------------------------------------------------------- source memory
class SourceMemory:
    """mid -> (sid, cid) for tracks this service has queued; survives restarts."""

    def __init__(self, path: Path, limit: int = 50_000) -> None:
        self.path = path
        self.limit = limit
        self._map: OrderedDict[str, tuple[int, str]] = OrderedDict()
        try:
            data = json.loads(path.read_text("utf-8"))
            for mid, (sid, cid) in data.items():
                self._map[mid] = (int(sid), str(cid))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as err:
            log.warning("track source memory unreadable (%s); starting empty", err)

    def get(self, mid: str) -> tuple[int, str] | None:
        return self._map.get(mid)

    def remember(self, entries: list[tuple[str, int, str]]) -> None:
        changed = False
        for mid, sid, cid in entries:
            if not mid or not cid:
                continue
            if self._map.get(mid) != (sid, cid):
                self._map[mid] = (sid, cid)
                changed = True
            self._map.move_to_end(mid)
        while len(self._map) > self.limit:
            self._map.popitem(last=False)
            changed = True
        if changed:
            atomic_write(self.path, json.dumps(self._map, ensure_ascii=False).encode())


# --------------------------------------------------------------- service
class PlaylistService:
    def __init__(self, storage: Storage, players: PlayerService, library: LibraryService, bus: EventBus) -> None:
        self.storage = storage
        self.players = players
        self.library = library
        self.bus = bus
        self.dir = storage.playlists_dir
        self.sources = SourceMemory(storage.data_dir / "cache" / "track-sources.json")

    # ----------------------------------------------------------- files
    def _path(self, playlist_id: str) -> Path:
        if not re.fullmatch(r"[\w-]+", playlist_id, flags=re.UNICODE):
            raise KeyError(playlist_id)
        return self.dir / f"{playlist_id}.m3u8"

    def _read(self, path: Path) -> Playlist:
        name, items = parse_m3u8(path.read_text("utf-8", errors="replace"), path.stem)
        return Playlist(id=path.stem, name=name, items=items, modified=path.stat().st_mtime)

    def _write(self, playlist: Playlist) -> Playlist:
        path = self._path(playlist.id)
        atomic_write(path, render_m3u8(playlist.name, playlist.items).encode("utf-8"))
        playlist.modified = path.stat().st_mtime
        self.bus.publish("playlists_changed", data={"id": playlist.id})
        return playlist

    def list(self) -> list[dict[str, Any]]:
        """All playlists; the folder is scanned each time, so files copied in by hand appear."""
        result = []
        for path in sorted(self.dir.glob("*.m3u8")):
            try:
                result.append(self._read(path).summary())
            except OSError as err:
                log.warning("cannot read playlist %s: %s", path.name, err)
        return sorted(result, key=lambda p: p["name"].casefold())

    def get(self, playlist_id: str) -> Playlist:
        path = self._path(playlist_id)
        if not path.exists():
            raise KeyError(playlist_id)
        return self._read(path)

    def _check_name(self, name: str, except_id: str | None = None) -> str:
        name = _clean(name)
        if not name:
            raise ValueError("a playlist needs a name")
        if len(name) > MAX_NAME:
            raise ValueError(f"name longer than {MAX_NAME} characters")
        for p in self.list():
            if p["name"].casefold() == name.casefold() and p["id"] != except_id:
                raise PlaylistExists(f'a playlist named "{p["name"]}" already exists')
        return name

    def _new_id(self, name: str) -> str:
        base = slugify(name)
        candidate, n = base, 2
        while (self.dir / f"{candidate}.m3u8").exists():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def create(self, name: str, items: list[PlaylistItem] | None = None) -> Playlist:
        name = self._check_name(name)
        return self._write(Playlist(id=self._new_id(name), name=name, items=list(items or [])))

    def rename(self, playlist_id: str, name: str) -> Playlist:
        """Rename = rewrite #PLAYLIST and rename the file to the new slug."""
        playlist = self.get(playlist_id)
        name = self._check_name(name, except_id=playlist_id)
        old_path = self._path(playlist_id)
        playlist.name = name
        if slugify(name) != playlist_id:
            playlist.id = self._new_id(name)
            self._write(playlist)
            old_path.unlink(missing_ok=True)
        else:
            self._write(playlist)
        return playlist

    def update_items(self, playlist_id: str, items: list[dict[str, Any]]) -> Playlist:
        """Replace the items (edit without playing: remove, reorder; F4.4)."""
        playlist = self.get(playlist_id)
        playlist.items = [PlaylistItem.from_dict(i) for i in items]
        return self._write(playlist)

    def sort(self, playlist_id: str, by: str, order: str = "asc") -> Playlist:
        playlist = self.get(playlist_id)
        as_queue = [{"song": i.title, "artist": i.artist, "album": i.album} for i in playlist.items]
        new_order = sort_order(as_queue, by, descending=order == "desc")
        playlist.items = [playlist.items[i] for i in new_order]
        return self._write(playlist)

    def duplicate(self, playlist_id: str, name: str | None = None) -> Playlist:
        source = self.get(playlist_id)
        if not name:
            base, n = f"{source.name} (copy)", 2
            name = base
            existing = {p["name"].casefold() for p in self.list()}
            while name.casefold() in existing:
                name, n = f"{base} {n}", n + 1
        return self.create(name, source.items)

    def delete(self, playlist_id: str) -> None:
        path = self._path(playlist_id)
        if not path.exists():
            raise KeyError(playlist_id)
        path.unlink()
        self.bus.publish("playlists_changed", data={"id": playlist_id, "deleted": True})

    def export(self, playlist_id: str) -> tuple[str, str]:
        path = self._path(playlist_id)
        if not path.exists():
            raise KeyError(playlist_id)
        return path.name, path.read_text("utf-8")

    def import_text(self, text: str, name: str | None = None) -> Playlist:
        parsed_name, items = parse_m3u8(text, name or "Imported playlist")
        return self.create(name or parsed_name, items)

    # ------------------------------------------------------ track sources
    async def remember_queued(self, items: list[dict[str, Any]]) -> None:
        """Called after this service queued ``items``: record where every track came from."""
        entries: list[tuple[str, int, str]] = []
        for item in items:
            sid, cid, mid = item.get("sid"), item.get("cid"), item.get("mid")
            if sid is None or not cid:
                continue
            if mid:
                entries.append((str(mid), int(sid), str(cid)))
                continue
            try:  # a whole container: remember each of its tracks
                tracks = await self.library.tracks_of({"sid": sid, "cid": cid})
            except Exception as err:  # noqa: BLE001 - best effort, never fail the add
                log.info("could not list tracks of %s for playlists: %s", cid, err)
                continue
            entries += [(t["mid"], int(t["sid"]), str(t["cid"])) for t in tracks]
        self.sources.remember(entries)

    async def _resolve_by_album(self, queue: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
        """Find unknown tracks in their album_id container on each DLNA server."""
        wanted: dict[str, set[str]] = {}
        for it in queue:
            mid, album_id = str(it.get("mid") or ""), str(it.get("album_id") or "")
            if mid and album_id and self.sources.get(mid) is None:
                wanted.setdefault(album_id, set()).add(mid)
        if not wanted:
            return {}
        found: dict[str, tuple[int, str]] = {}
        try:
            servers = [s["sid"] for s in await self.library.servers()]
        except Exception as err:  # noqa: BLE001
            log.info("cannot list DLNA servers to resolve tracks: %s", err)
            return {}
        for album_id, mids in wanted.items():
            for sid in servers:
                try:
                    tracks = await self.library.tracks_of({"sid": sid, "cid": album_id})
                except Exception:  # noqa: BLE001 - not on this server
                    continue
                hits = {t["mid"] for t in tracks} & mids
                for mid in hits:
                    found[mid] = (sid, album_id)
                if hits:
                    break
        return found

    async def save_queue(self, pid: int, name: str) -> dict[str, Any]:
        """Save the player's current queue as a new local playlist (F4.1)."""
        name = self._check_name(name)
        queue = await self.players.queue(pid)
        found = await self._resolve_by_album(queue)
        self.sources.remember([(mid, sid, cid) for mid, (sid, cid) in found.items()])
        items = []
        for it in queue:
            mid = str(it.get("mid") or "")
            src = self.sources.get(mid) if mid else None
            items.append(PlaylistItem(
                title=str(it.get("song") or ""), artist=str(it.get("artist") or ""),
                album=str(it.get("album") or ""), sid=src[0] if src else None, cid=src[1] if src else None,
                mid=mid or None, image_url=str(it.get("image_url_remote") or it.get("image_url") or ""),
            ))
        playlist = self.create(name, items)
        return playlist.summary()

    # ----------------------------------------------------------- loading
    async def _compact(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace runs that equal a whole container (in order) by the container: one command."""
        result: list[dict[str, Any]] = []
        i = 0
        while i < len(items):
            j = i
            while j < len(items) and (items[j]["sid"], items[j]["cid"]) == (items[i]["sid"], items[i]["cid"]):
                j += 1
            run = items[i:j]
            if len(run) > 1:
                try:
                    tracks = await self.library.tracks_of({"sid": run[0]["sid"], "cid": run[0]["cid"]})
                    if [t["mid"] for t in tracks] == [r["mid"] for r in run]:
                        result.append({"sid": run[0]["sid"], "cid": run[0]["cid"]})
                        i = j
                        continue
                except Exception:  # noqa: BLE001 - fall back to single tracks
                    pass
            result += run
            i = j
        return result

    async def load(self, playlist_id: str, pid: int, mode: str) -> dict[str, Any]:
        """Put a playlist into the HEOS queue (F4.3): now / replace / end (append)."""
        if mode == "append":
            mode = "end"
        if mode not in LOAD_MODES:
            raise ValueError(f"mode must be one of {', '.join(LOAD_MODES)}")
        self.players.get(pid)
        playlist = self.get(playlist_id)
        items = [{"sid": i.sid, "cid": i.cid, "mid": i.mid} for i in playlist.items if i.resolved]
        skipped = len(playlist.items) - len(items)
        if not items:
            raise ValueError("no track in this playlist can be played (all unresolved)")
        commands = await self._compact(items)
        progress: Callable[[int, int], None] = lambda done, total: self.bus.publish(  # noqa: E731
            "playlist_load", pid, {"id": playlist_id, "done": done, "total": total})
        started = time.monotonic()
        await self.players.add_to_queue(pid, commands, mode, expand=self.library.tracks_of, progress=progress)
        await self.remember_queued(items)
        log.info("loaded playlist %s: %d tracks in %d commands, %.1f s",
                 playlist_id, len(items), len(commands), time.monotonic() - started)
        return {"id": playlist_id, "mode": mode, "tracks": len(items), "skipped": skipped,
                "commands": len(commands)}
