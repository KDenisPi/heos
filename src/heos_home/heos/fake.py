"""A fake HEOS device speaking the CLI protocol on TCP, for tests and UI work.

    python -m heos_home.heos.fake --port 1255

It simulates one Marantz PM7000N with inputs, a queue, a DLNA server and
change events. Behaviour follows the HEOS CLI spec v1.17; it is not a full
emulation, just enough to drive the service end to end without the amp.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .protocol import encode_value, parse_message

log = logging.getLogger(__name__)

INPUTS = [
    ("inputs/phono", "Phono"),
    ("inputs/cd", "CD"),
    ("inputs/aux_in_1", "Line"),
    ("inputs/optical_in_1", "Optical 1"),
    ("inputs/optical_in_2", "Optical 2"),
    ("inputs/coax_in_1", "Coaxial"),
]

DLNA_SID = 111
LOGO = "https://logos.example.invalid/media/images/service/logos"
LIBRARY: dict[str, list[dict[str, Any]]] = {
    # cid -> items; "" is the server root. Shaped like the NAS seen on the real amp:
    # folders say playable=no in their parent's listing even when they hold tracks.
    "": [
        {"container": "yes", "playable": "no", "type": "container", "name": "Music", "cid": "64$1"},
        {"container": "yes", "playable": "no", "type": "container", "name": "Folder", "cid": "64$9"},
    ],
    "64$9": [
        {"container": "yes", "playable": "no", "type": "container", "name": "classic", "cid": "64$9$1"},
        {"container": "yes", "playable": "no", "type": "container", "name": "empty", "cid": "64$9$2"},
    ],
    "64$9$1": [
        {"container": "yes", "playable": "no", "type": "container", "name": "Big Box", "cid": "64$9$1$1"},
    ],
    "64$9$2": [],
    "64$9$1$1": [
        {"container": "no", "playable": "yes", "type": "song", "name": f"Track {i:03d}",
         "artist": "Various", "album": "Big Box", "mid": f"64$9$1$1${i}", "duration": 180000,
         "image_url": "http://192.0.2.11:8200/cover/bigbox.jpg"}
        for i in range(1, 121)
    ],
    "64$1": [
        {"container": "yes", "playable": "yes", "type": "album", "name": "Cantatas Vol. 1",
         "artist": "J.S. Bach", "cid": "64$1$3"},
        {"container": "yes", "playable": "yes", "type": "album", "name": "Kind of Blue",
         "artist": "Miles Davis", "cid": "64$1$4"},
    ],
    "64$1$3": [
        {"container": "no", "playable": "yes", "type": "song", "name": f"Cantata BWV 140: {n}",
         "artist": "J.S. Bach", "album": "Cantatas Vol. 1", "mid": f"64$1$3${i}", "duration": d}
        for i, (n, d) in enumerate([("I. Chorus", 325000), ("II. Recitative", 61000), ("III. Aria", 412000)], 1)
    ],
    "64$1$4": [
        {"container": "no", "playable": "yes", "type": "song", "name": n,
         "artist": "Miles Davis", "album": "Kind of Blue", "mid": f"64$1$4${i}", "duration": d}
        for i, (n, d) in enumerate([("So What", 562000), ("Freddie Freeloader", 586000),
                                    ("Blue in Green", 337000)], 1)
    ],
}


class _SystemError(Exception):
    """Answer eid 12, like the real NAS does for search."""


@dataclass
class FakePlayer:
    pid: int
    name: str
    model: str = "Marantz PM7000N"
    version: str = "3.84.410"
    ip: str = "127.0.0.1"
    network: str = "wired"
    serial: str = "FAKE0001"
    state: str = "stop"
    volume: int = 20
    mute: bool = False
    repeat: str = "off"
    shuffle: bool = False
    queue: list[dict[str, Any]] = field(default_factory=list)
    current: int | None = None  # index into queue
    input: str | None = None

    def renumber(self) -> None:
        for i, item in enumerate(self.queue, 1):
            item["qid"] = i


class FakeHeosServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.players: dict[int, FakePlayer] = {-1234: FakePlayer(-1234, "Living room")}
        self.signed_in: str | None = "user@example.com"
        self.received: list[str] = []
        self.under_process_for: set[str] = {"browse/browse"}
        self.fail_next: dict[str, int] = {}  # command -> eid
        self.silent: set[str] = set()  # commands that never get an answer
        self.search_supported = True  # the real NAS answers eid 12 to every search
        self._writers: dict[asyncio.StreamWriter, bool] = {}  # writer -> registered for events
        self._server: asyncio.base_events.Server | None = None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> "FakeHeosServer":
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        await self.drop_connections()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def drop_connections(self) -> None:
        for writer in list(self._writers):
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        self._writers.clear()

    @property
    def connection_count(self) -> int:
        return len(self._writers)

    # ---------------------------------------------------------------- wire
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers[writer] = False
        try:
            while True:
                line = await reader.readuntil(b"\r\n")
                text = line.decode().strip()
                if not text:
                    continue
                self.received.append(text)
                await self._dispatch(text, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.pop(writer, None)
            writer.close()

    def _send(self, writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
        if not writer.is_closing():
            writer.write(json.dumps(obj).encode() + b"\r\n")

    def emit(self, command: str, message: str = "") -> None:
        """Send a change event to every connection registered for events."""
        for writer, registered in list(self._writers.items()):
            if registered:
                self._send(writer, {"heos": {"command": f"event/{command}", "message": message}})

    async def _dispatch(self, text: str, writer: asyncio.StreamWriter) -> None:
        body = text.removeprefix("heos://")
        command, _, query = body.partition("?")
        params = parse_message(query)
        if command in self.silent:
            return
        if command in self.under_process_for:
            self._send(writer, {"heos": {"command": command, "result": "success",
                                         "message": "command under process"}})
            await asyncio.sleep(0.01)
        eid = self.fail_next.pop(command, None)
        if eid is not None:
            self._reply(writer, command, "fail", f"eid={eid}&text=Simulated error&{query}")
            return
        handler = getattr(self, "_cmd_" + command.replace("/", "__"), None)
        if handler is None:
            self._reply(writer, command, "fail", f"eid=1&text=Command not recognized&{query}")
            return
        try:
            result = handler(params, writer)
        except KeyError:
            self._reply(writer, command, "fail", f"eid=2&text=ID not valid&{query}")
            return
        except ValueError:
            self._reply(writer, command, "fail", f"eid=9&text=Out of range&{query}")
            return
        except _SystemError:
            self._reply(writer, command, "fail", "eid=12&text=System error&syserrno=-9")
            return
        if isinstance(result, tuple) and len(result) == 3:
            message, payload, options = result
        else:
            message, payload = result if isinstance(result, tuple) else (result, None)
            options = None
        self._reply(writer, command, "success", query if message is None else message, payload, options)

    def _reply(self, writer: asyncio.StreamWriter, command: str, result: str, message: str,
               payload: Any = None, options: Any = None) -> None:
        obj: dict[str, Any] = {"heos": {"command": command, "result": result, "message": message}}
        if payload is not None:
            obj["payload"] = payload
        if options is not None:
            obj["options"] = options
        self._send(writer, obj)

    def _player(self, params: dict[str, str]) -> FakePlayer:
        return self.players[int(params["pid"])]

    @staticmethod
    def _enc(obj: Any) -> Any:
        if isinstance(obj, str):
            return encode_value(obj)
        if isinstance(obj, list):
            return [FakeHeosServer._enc(x) for x in obj]
        if isinstance(obj, dict):
            return {k: FakeHeosServer._enc(v) for k, v in obj.items()}
        return obj

    # --------------------------------------------------------------- system
    def _cmd_system__register_for_change_events(self, p: dict[str, str], w: asyncio.StreamWriter) -> None:
        self._writers[w] = p.get("enable") == "on"

    def _cmd_system__heart_beat(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        return ""

    def _cmd_system__check_account(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        return f"signed_in&un={self.signed_in}" if self.signed_in else "signed_out"

    def _cmd_system__sign_in(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        self.signed_in = p["un"]
        self.emit("user_changed", f"signed_in&un={self.signed_in}")
        return f"signed_in&un={self.signed_in}"

    def _cmd_system__sign_out(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        self.signed_in = None
        self.emit("user_changed", "signed_out")
        return "signed_out"

    # --------------------------------------------------------------- player
    def _info(self, pl: FakePlayer) -> dict[str, Any]:
        return {"name": pl.name, "pid": pl.pid, "model": pl.model, "version": pl.version, "ip": pl.ip,
                "network": pl.network, "lineout": 1, "serial": pl.serial}

    def _cmd_player__get_players(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        return "", [self._enc(self._info(pl)) for pl in self.players.values()]

    def _cmd_player__get_player_info(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        return f"pid={p['pid']}", self._enc(self._info(self._player(p)))

    def _cmd_player__get_play_state(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        return f"pid={pl.pid}&state={pl.state}"

    def _set_state(self, pl: FakePlayer, state: str) -> None:
        if pl.state != state:
            pl.state = state
            self.emit("player_state_changed", f"pid={pl.pid}&state={state}")

    def _cmd_player__set_play_state(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if p["state"] not in ("play", "pause", "stop"):
            raise ValueError
        self._set_state(pl, p["state"])
        return f"pid={pl.pid}&state={pl.state}"

    def _volume_event(self, pl: FakePlayer) -> None:
        self.emit("player_volume_changed", f"pid={pl.pid}&level={pl.volume}&mute={'on' if pl.mute else 'off'}")

    def _cmd_player__get_volume(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        return f"pid={pl.pid}&level={pl.volume}"

    def _cmd_player__set_volume(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        level = int(p["level"])
        if not 0 <= level <= 100:
            raise ValueError
        pl.volume = level
        self._volume_event(pl)
        return f"pid={pl.pid}&level={level}"

    def _step(self, p: dict[str, str], sign: int) -> str:
        pl = self._player(p)
        step = int(p.get("step", 5))
        if not 1 <= step <= 10:
            raise ValueError
        pl.volume = max(0, min(100, pl.volume + sign * step))
        self._volume_event(pl)
        return f"pid={pl.pid}&step={step}"

    def _cmd_player__volume_up(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        return self._step(p, 1)

    def _cmd_player__volume_down(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        return self._step(p, -1)

    def _cmd_player__get_mute(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        return f"pid={pl.pid}&state={'on' if pl.mute else 'off'}"

    def _cmd_player__set_mute(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        pl.mute = p["state"] == "on"
        self._volume_event(pl)
        return f"pid={pl.pid}&state={p['state']}"

    def _cmd_player__toggle_mute(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        pl.mute = not pl.mute
        self._volume_event(pl)
        return f"pid={pl.pid}"

    def _cmd_player__get_play_mode(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        return f"pid={pl.pid}&repeat={pl.repeat}&shuffle={'on' if pl.shuffle else 'off'}"

    def _cmd_player__set_play_mode(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if "repeat" in p and p["repeat"] != pl.repeat:
            pl.repeat = p["repeat"]
            self.emit("repeat_mode_changed", f"pid={pl.pid}&repeat={pl.repeat}")
        if "shuffle" in p and (p["shuffle"] == "on") != pl.shuffle:
            pl.shuffle = p["shuffle"] == "on"
            self.emit("shuffle_mode_changed", f"pid={pl.pid}&shuffle={p['shuffle']}")
        return self._cmd_player__get_play_mode(p, w)

    def _now_playing(self, pl: FakePlayer) -> dict[str, Any]:
        if pl.input:
            name = dict(INPUTS).get(pl.input, pl.input)
            return {"type": "station", "song": name, "station": name, "album": "", "artist": "",
                    "image_url": "", "mid": pl.input, "qid": 1, "sid": 1027}
        if pl.current is None or not pl.queue:
            return {"type": "song", "song": "", "album": "", "artist": "", "image_url": "", "mid": "",
                    "qid": 0, "sid": 0}
        item = pl.queue[pl.current]
        return {"type": "song", "song": item["song"], "album": item["album"], "artist": item["artist"],
                "image_url": item["image_url"], "mid": item["mid"], "qid": item["qid"], "sid": 1024,
                "album_id": item.get("album_id", "")}

    def _cmd_player__get_now_playing_media(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        pl = self._player(p)
        return f"pid={pl.pid}", self._enc(self._now_playing(pl))

    def _play_index(self, pl: FakePlayer, index: int | None) -> None:
        pl.input = None
        pl.current = index
        self.emit("player_now_playing_changed", f"pid={pl.pid}")
        if index is not None:
            self._set_state(pl, "play")
            duration = pl.queue[index].get("duration", 0)
            self.emit("player_now_playing_progress", f"pid={pl.pid}&cur_pos=0&duration={duration}")

    def _cmd_player__get_queue(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        pl = self._player(p)
        start, end = 0, 99
        if "range" in p:
            a, b = p["range"].split(",")
            start, end = int(a), min(int(b), int(a) + 99)
        items = [{k: v for k, v in it.items() if k != "duration"} for it in pl.queue[start:end + 1]]
        return f"pid={pl.pid}&range={start},{end}", self._enc(items)

    def _cmd_player__play_queue(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        qid = int(p["qid"])
        if not 1 <= qid <= len(pl.queue):
            raise KeyError(qid)
        self._play_index(pl, qid - 1)
        return f"pid={pl.pid}&qid={qid}"

    def _queue_changed(self, pl: FakePlayer) -> None:
        pl.renumber()
        self.emit("player_queue_changed", f"pid={pl.pid}")

    def _cmd_player__remove_from_queue(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        qids = {int(x) for x in p["qid"].split(",")}
        current = pl.queue[pl.current] if pl.current is not None and pl.queue else None
        pl.queue = [it for it in pl.queue if it["qid"] not in qids]
        pl.current = pl.queue.index(current) if current in pl.queue else None
        self._queue_changed(pl)
        return f"pid={pl.pid}&qid={p['qid']}"

    def _cmd_player__clear_queue(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        pl.queue, pl.current = [], None
        self._queue_changed(pl)
        self._set_state(pl, "stop")
        return f"pid={pl.pid}"

    def _cmd_player__move_queue_item(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        sqids = [int(x) for x in p["sqid"].split(",")]
        dqid = int(p["dqid"])
        current = pl.queue[pl.current] if pl.current is not None and pl.queue else None
        moving = [it for it in pl.queue if it["qid"] in sqids]
        rest = [it for it in pl.queue if it["qid"] not in sqids]
        index = max(0, min(len(rest), dqid - 1))
        pl.queue = rest[:index] + moving + rest[index:]
        pl.current = pl.queue.index(current) if current is not None else None
        self._queue_changed(pl)
        return f"pid={pl.pid}&sqid={p['sqid']}&dqid={dqid}"

    def _cmd_player__play_next(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if pl.queue and pl.current is not None and pl.current + 1 < len(pl.queue):
            self._play_index(pl, pl.current + 1)
        return f"pid={pl.pid}"

    def _cmd_player__play_previous(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if pl.queue and pl.current:
            self._play_index(pl, pl.current - 1)
        return f"pid={pl.pid}"

    def _cmd_player__check_update(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        pl = self._player(p)
        return f"pid={pl.pid}", {"update": "update_none"}

    # --------------------------------------------------------------- browse
    def _cmd_browse__get_music_sources(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        return "", [
            {"name": "Amazon Music", "image_url": f"{LOGO}/amazon.png", "type": "music_service", "sid": 13, "available": "true",
             "service_username": "user@example.com"},
            {"name": "Local Music", "image_url": f"{LOGO}/musicsource_logo_servers.png", "type": "heos_server", "sid": 1024, "available": "true"},
            {"name": "Playlists", "image_url": "", "type": "heos_service", "sid": 1025, "available": "true"},
            {"name": "History", "image_url": "", "type": "heos_service", "sid": 1026, "available": "true"},
            {"name": "AUX Input", "image_url": f"{LOGO}/musicsource_logo_aux.png", "type": "heos_service", "sid": 1027, "available": "true"},
            {"name": "Favorites", "image_url": "", "type": "heos_service", "sid": 1028, "available": "true"},
        ]

    def _cmd_browse__browse(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[Any, ...]:
        sid = int(p["sid"])
        options = None
        if sid == 1027:
            items = [{"name": pl.name, "image_url": "", "sid": pl.pid, "type": "heos_service"}
                     for pl in self.players.values()]
        elif sid in self.players:
            items = [{"container": "no", "playable": "yes", "type": "station", "name": name, "image_url": "",
                      "mid": mid} for mid, name in INPUTS]
        elif sid == 1024:
            items = [{"name": "Fake NAS", "image_url": "", "sid": DLNA_SID, "type": "dlna_server"}]
        elif sid == DLNA_SID:
            cid = p.get("cid", "")
            if cid not in LIBRARY:
                raise KeyError(cid)
            items = [{k: v for k, v in it.items() if k != "duration"} for it in LIBRARY[cid]]
            for it in items:
                it.setdefault("image_url", "")
                if it.get("type") == "song":
                    it.setdefault("album_id", cid)
            if any(it.get("type") == "song" for it in items):
                options = [{"browse": [{"id": 21, "name": "Playable Container"}]}]
        else:
            raise KeyError(sid)
        total = len(items)
        start, end = 0, total - 1
        if "range" in p:
            a, b = p["range"].split(",")
            start, end = int(a), int(b)
        page = items[start:end + 1]
        msg = f"sid={sid}" + (f"&cid={encode_value(p['cid'])}" if "cid" in p else "")
        message = f"{msg}&returned={len(page)}&count={total}"
        return (message, self._enc(page), options) if options else (message, self._enc(page))

    def _cmd_browse__get_search_criteria(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        if int(p["sid"]) != DLNA_SID:
            raise KeyError(p["sid"])
        return f"sid={DLNA_SID}", [
            {"name": "Artist", "scid": 1, "wildcard": "no"},
            {"name": "Album", "scid": 2, "wildcard": "no"},
            {"name": "Track", "scid": 3, "wildcard": "no", "cid": "SEARCHED_TRACKS-", "playable": "yes"},
        ]

    def _cmd_browse__search(self, p: dict[str, str], w: asyncio.StreamWriter) -> tuple[str, Any]:
        if int(p["sid"]) != DLNA_SID:
            raise KeyError(p["sid"])
        if not self.search_supported:
            raise _SystemError
        needle, scid = p["search"].casefold(), int(p.get("scid", 3))
        field = {1: "artist", 2: "album", 3: "name"}[scid]
        songs = [dict(it, album_id=cid) for cid, items in LIBRARY.items() for it in items if it.get("type") == "song"]
        hits = [{k: v for k, v in it.items() if k != "duration"} for it in songs if needle in it[field].casefold()]
        start, end = 0, len(hits) - 1
        if "range" in p:
            a, b = p["range"].split(",")
            start, end = int(a), int(b)
        page = hits[start:end + 1]
        return f"sid={DLNA_SID}&search={encode_value(p['search'])}&scid={scid}&returned={len(page)}&count={len(hits)}", self._enc(page)

    def _cmd_browse__play_input(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if p["input"] not in dict(INPUTS):
            raise KeyError(p["input"])
        pl.input = p["input"]
        pl.current = None
        self.emit("player_now_playing_changed", f"pid={pl.pid}")
        self._set_state(pl, "play")
        return f"pid={pl.pid}&input={p['input']}"

    def _tracks_for(self, cid: str, mid: str | None) -> list[dict[str, Any]]:
        if cid not in LIBRARY:
            raise KeyError(cid)
        tracks = [it for it in LIBRARY[cid] if it["type"] == "song"]
        if mid:
            tracks = [it for it in tracks if it["mid"] == mid]
            if not tracks:
                raise KeyError(mid)
        return [{"song": t["name"], "album": t["album"], "artist": t["artist"], "image_url": "",
                 "mid": t["mid"], "qid": 0, "album_id": cid, "duration": t["duration"]} for t in tracks]

    def _cmd_browse__add_to_queue(self, p: dict[str, str], w: asyncio.StreamWriter) -> str:
        pl = self._player(p)
        if int(p["sid"]) != DLNA_SID:
            raise KeyError(p["sid"])
        tracks = self._tracks_for(p.get("cid", ""), p.get("mid"))
        aid = int(p["aid"])
        after_current = (pl.current + 1) if pl.current is not None else len(pl.queue)
        if aid == 4:
            pl.queue, pl.current = list(tracks), None
            self._queue_changed(pl)
            self._play_index(pl, 0)
        elif aid == 3:
            pl.queue.extend(tracks)
            self._queue_changed(pl)
        elif aid in (1, 2):
            pl.queue[after_current:after_current] = tracks
            self._queue_changed(pl)
            if aid == 1:
                self._play_index(pl, after_current)
        else:
            raise ValueError(aid)
        return "&".join(f"{k}={encode_value(v)}" for k, v in p.items())


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Fake HEOS CLI device")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1255)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    server = await FakeHeosServer(args.host, args.port).start()
    log.info("fake HEOS device listening on %s:%s", args.host, server.port)
    await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())
