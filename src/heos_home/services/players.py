"""Player service: cached player state, HEOS event handling, player/queue commands.

The cache is filled from the device on every (re)connect and then kept current
by HEOS change events, so REST reads are served from memory and every change is
pushed to WebSocket clients through the ``EventBus``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..heos.client import HeosClient
from ..heos.protocol import HeosCommandError, HeosError, HeosMessage
from .events import EventBus
from .queue_sort import plan_moves, sort_order

log = logging.getLogger(__name__)

TRANSPORT_STATES = {"play", "pause", "stop"}
REPEAT_MODES = {"off", "on_all", "on_one"}
ADD_MODES = {"now": 1, "next": 2, "end": 3, "replace": 4}
QUEUE_PAGE = 100
SORT_ATTEMPTS = 3
# The PM7000N confirms a move before it has finished reordering; a move sent
# right after it fails with eid 12 ("System error", syserrno -2) and succeeds
# when repeated a moment later. So moves are paced and retried.
MOVE_GAP = 0.15
MOVE_RETRY_DELAYS = (0.3, 0.6, 1.0, 1.5, 2.0)
AUX_SOURCE_NAME = "aux input"


def _identity_keys(items: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Stable identities for queue items: (media id, occurrence), since qids are positions."""
    seen: dict[str, int] = {}
    keys = []
    for item in items:
        mid = str(item.get("mid") or item.get("song") or "")
        seen[mid] = seen.get(mid, 0) + 1
        keys.append((mid, seen[mid]))
    return keys


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class PlayerState:
    pid: int
    name: str = ""
    model: str = ""
    version: str = ""
    ip: str | None = None
    network: str | None = None
    serial: str | None = None
    gid: int | None = None
    online: bool = False
    state: str = "stop"
    volume: int = 0
    mute: bool = False
    repeat: str = "off"
    shuffle: bool = False
    now_playing: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, int] = field(default_factory=lambda: {"cur_pos": 0, "duration": 0})
    input: str | None = None
    last_error: str | None = None

    def info(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "model": self.model,
            "version": self.version,
            "ip": self.ip,
            "network": self.network,
            "serial": self.serial,
            "gid": self.gid,
            "online": self.online,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlayerService:
    def __init__(self, client: HeosClient, bus: EventBus) -> None:
        self.client = client
        self.bus = bus
        self.players: dict[int, PlayerState] = {}
        self._inputs: dict[int, list[dict[str, Any]]] = {}
        self._sources: list[dict[str, Any]] | None = None
        self.account: dict[str, Any] = {"signed_in": False, "username": None}
        self._refresh_lock = asyncio.Lock()
        self._sorting: dict[int, asyncio.Lock] = {}
        client.add_event_listener(self._on_event)
        client.add_connection_listener(self._on_connection)

    # ---------------------------------------------------------------- helpers
    def get(self, pid: int) -> PlayerState:
        player = self.players.get(pid)
        if player is None:
            raise KeyError(pid)
        return player

    async def _cmd(self, command: str, **params: Any) -> HeosMessage:
        return await self.client.command(command, params or None)

    # ------------------------------------------------------- connection/state
    async def _on_connection(self, connected: bool) -> None:
        self.bus.publish("connection", data={"connected": connected, "host": self.client.host})
        if connected:
            await self.refresh_all()
        else:
            for player in self.players.values():
                if player.online:
                    player.online = False
                    self.bus.publish("device_offline", player.pid)

    async def refresh_all(self) -> None:
        async with self._refresh_lock:
            self._sources = None
            self._inputs.clear()
            await self.refresh_players()
            for pid in list(self.players):
                if self.players[pid].online:
                    await self.refresh_player(pid)
            await self.refresh_account()

    async def refresh_players(self) -> list[int]:
        """Re-read the player list; return the pids that just came online."""
        msg = await self._cmd("player/get_players")
        came_online: list[int] = []
        seen: set[int] = set()
        for item in msg.payload or []:
            pid = _int(item.get("pid"))
            if pid is None:
                continue
            seen.add(pid)
            player = self.players.get(pid) or PlayerState(pid=pid)
            player.name = item.get("name", player.name)
            player.model = item.get("model", player.model)
            player.version = item.get("version", player.version)
            player.ip = item.get("ip", player.ip)
            player.network = item.get("network", player.network)
            player.serial = item.get("serial", player.serial)
            player.gid = _int(item.get("gid"))
            was_online = player.online
            player.online = True
            self.players[pid] = player
            if not was_online:
                came_online.append(pid)
                self.bus.publish("device_online", pid, player.info())
        for pid, player in self.players.items():
            if pid not in seen and player.online:
                player.online = False
                self.bus.publish("device_offline", pid)
        return came_online

    async def refresh_player(self, pid: int) -> None:
        player = self.get(pid)
        try:
            state = await self._cmd("player/get_play_state", pid=pid)
            player.state = state.params.get("state", player.state)
            vol = await self._cmd("player/get_volume", pid=pid)
            player.volume = _int(vol.params.get("level"), player.volume) or 0
            mute = await self._cmd("player/get_mute", pid=pid)
            player.mute = mute.params.get("state") == "on"
            mode = await self._cmd("player/get_play_mode", pid=pid)
            player.repeat = mode.params.get("repeat", player.repeat)
            player.shuffle = mode.params.get("shuffle") == "on"
            await self.refresh_now_playing(pid, publish=False)
        except HeosError as err:
            log.warning("refresh of player %s failed: %s", pid, err)
            player.last_error = str(err)
        self.bus.publish("player_full", pid, player.to_dict())

    async def refresh_now_playing(self, pid: int, publish: bool = True) -> None:
        player = self.get(pid)
        msg = await self._cmd("player/get_now_playing_media", pid=pid)
        media = msg.payload if isinstance(msg.payload, dict) else {}
        player.now_playing = media
        mid = str(media.get("mid") or "")
        player.input = mid if mid.startswith("inputs/") else None
        if publish:
            self.bus.publish("now_playing", pid, {**media, "input": player.input})

    async def refresh_account(self) -> None:
        msg = await self._cmd("system/check_account")
        self._set_account(msg.params)

    def _set_account(self, params: dict[str, str]) -> None:
        self.account = {"signed_in": "signed_in" in params, "username": params.get("un")}
        self.bus.publish("account", data=self.account)

    # ----------------------------------------------------------------- events
    async def _on_event(self, msg: HeosMessage) -> None:
        name = msg.command.removeprefix("event/")
        p = msg.params
        pid = _int(p.get("pid"))
        player = self.players.get(pid) if pid is not None else None

        if name == "player_state_changed" and player:
            player.state = p.get("state", player.state)
            self.bus.publish("player_state", pid, {"state": player.state})
        elif name == "player_volume_changed" and player:
            player.volume = _int(p.get("level"), player.volume) or 0
            player.mute = p.get("mute") == "on"
            self.bus.publish("volume", pid, {"level": player.volume, "mute": player.mute})
        elif name == "player_now_playing_changed" and player:
            player.progress = {"cur_pos": 0, "duration": 0}
            await self.refresh_now_playing(pid)  # type: ignore[arg-type]
        elif name == "player_now_playing_progress" and player:
            player.progress = {
                "cur_pos": _int(p.get("cur_pos"), 0) or 0,
                "duration": _int(p.get("duration"), 0) or 0,
            }
            self.bus.publish("progress", pid, player.progress)
        elif name == "player_queue_changed" and pid is not None:
            # During a sort every move fires this; one event is sent at the end.
            if not self.sorting(pid):
                self.bus.publish("queue_changed", pid)
        elif name == "repeat_mode_changed" and player:
            player.repeat = p.get("repeat", player.repeat)
            self.bus.publish("play_mode", pid, {"repeat": player.repeat, "shuffle": player.shuffle})
        elif name == "shuffle_mode_changed" and player:
            player.shuffle = p.get("shuffle") == "on"
            self.bus.publish("play_mode", pid, {"repeat": player.repeat, "shuffle": player.shuffle})
        elif name == "player_playback_error" and player:
            player.last_error = p.get("error")
            self.bus.publish("playback_error", pid, {"error": player.last_error})
        elif name in ("players_changed", "groups_changed"):
            for new_pid in await self.refresh_players():
                await self.refresh_player(new_pid)
            self.bus.publish("players_changed")
        elif name == "sources_changed":
            self._sources = None
            self._inputs.clear()
            self.bus.publish("sources_changed")
        elif name == "user_changed":
            self._set_account(p)
        else:
            log.debug("unhandled HEOS event %s %s", name, msg.message)

    # --------------------------------------------------------------- commands
    async def transport(self, pid: int, action: str) -> None:
        self.get(pid)
        if action in TRANSPORT_STATES:
            await self._cmd("player/set_play_state", pid=pid, state=action)
        elif action == "next":
            await self._cmd("player/play_next", pid=pid)
        elif action in ("prev", "previous"):
            await self._cmd("player/play_previous", pid=pid)
        else:
            raise ValueError(f"unknown transport action {action!r}")

    async def set_volume(self, pid: int, level: int) -> int:
        player = self.get(pid)
        level = max(0, min(100, int(level)))
        await self._cmd("player/set_volume", pid=pid, level=level)
        player.volume = level
        return level

    async def step_volume(self, pid: int, step: int) -> None:
        self.get(pid)
        if step == 0:
            return
        size = max(1, min(10, abs(int(step))))
        await self._cmd("player/volume_up" if step > 0 else "player/volume_down", pid=pid, step=size)

    async def set_mute(self, pid: int, state: bool) -> None:
        player = self.get(pid)
        await self._cmd("player/set_mute", pid=pid, state="on" if state else "off")
        player.mute = state

    async def set_play_mode(self, pid: int, shuffle: bool | None, repeat: str | None) -> None:
        player = self.get(pid)
        if repeat is not None and repeat not in REPEAT_MODES:
            raise ValueError(f"repeat must be one of {sorted(REPEAT_MODES)}")
        repeat = repeat if repeat is not None else player.repeat
        shuffle = shuffle if shuffle is not None else player.shuffle
        await self._cmd("player/set_play_mode", pid=pid, repeat=repeat, shuffle="on" if shuffle else "off")
        player.repeat, player.shuffle = repeat, shuffle

    # ------------------------------------------------------------- sources
    async def music_sources(self, refresh: bool = False) -> list[dict[str, Any]]:
        if self._sources is None or refresh:
            msg = await self._cmd("browse/get_music_sources")
            self._sources = list(msg.payload or [])
        return self._sources

    async def inputs(self, pid: int) -> list[dict[str, Any]]:
        """Inputs offered by the device itself (F3.3), not a hard-coded list."""
        player = self.get(pid)
        if pid in self._inputs:
            return self._inputs[pid]
        sources = await self.music_sources()
        aux = next(
            (s for s in sources if str(s.get("name", "")).strip().lower() == AUX_SOURCE_NAME),
            None,
        ) or next((s for s in sources if s.get("type") == "heos_service" and _int(s.get("sid")) == 1027), None)
        if aux is None:
            self._inputs[pid] = []
            return []
        devices = (await self.client.command("browse/browse", {"sid": aux["sid"]}, timeout=20)).payload or []
        # One entry per HEOS device that has inputs; pick the one for this player.
        device = (
            next((d for d in devices if _int(d.get("sid")) == pid), None)
            or next((d for d in devices if d.get("name") == player.name), None)
            or (devices[0] if len(devices) == 1 else None)
        )
        result: list[dict[str, Any]] = []
        if device is not None:
            items = (await self.client.command("browse/browse", {"sid": device["sid"]}, timeout=20)).payload or []
            for item in items:
                mid = str(item.get("mid") or "")
                if mid.startswith("inputs/"):
                    result.append({"input": mid, "name": item.get("name") or mid, "image_url": item.get("image_url")})
        self._inputs[pid] = result
        return result

    async def play_input(self, pid: int, input_name: str, source_pid: int | None = None) -> None:
        self.get(pid)
        if not input_name.startswith("inputs/"):
            input_name = f"inputs/{input_name}"
        await self._cmd("browse/play_input", pid=pid, spid=source_pid, input=input_name)

    # ---------------------------------------------------------------- queue
    async def queue(self, pid: int) -> list[dict[str, Any]]:
        """The whole HEOS queue, fetched in pages of 100."""
        self.get(pid)
        items: list[dict[str, Any]] = []
        start = 0
        while True:
            msg = await self._cmd("player/get_queue", pid=pid, range=f"{start},{start + QUEUE_PAGE - 1}")
            page = list(msg.payload or [])
            for item in page:
                item["qid"] = _int(item.get("qid"), item.get("qid"))
            items.extend(page)
            if len(page) < QUEUE_PAGE:
                return items
            start += QUEUE_PAGE

    async def play_queue_item(self, pid: int, qid: int) -> None:
        self.get(pid)
        await self._cmd("player/play_queue", pid=pid, qid=qid)

    async def remove_from_queue(self, pid: int, qids: list[int]) -> None:
        self.get(pid)
        if qids:
            await self._cmd("player/remove_from_queue", pid=pid, qid=",".join(map(str, qids)))

    async def clear_queue(self, pid: int) -> None:
        self.get(pid)
        await self._cmd("player/clear_queue", pid=pid)

    async def _move(self, pid: int, sqid: int | str, dqid: int) -> None:
        """One move_queue_item, retried while the amp is still busy with the previous change."""
        for attempt, delay in enumerate((0.0, *MOVE_RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._cmd("player/move_queue_item", pid=pid, sqid=sqid, dqid=dqid)
                return
            except HeosCommandError as err:
                if err.eid not in (12, 13) or attempt == len(MOVE_RETRY_DELAYS):
                    raise
                log.info("move %s -> %s rejected while busy (%s), retrying in %.1f s",
                         sqid, dqid, err.text, MOVE_RETRY_DELAYS[attempt])

    async def move_queue(self, pid: int, qids: list[int], to: int) -> None:
        """Move ``qids`` so that they land at queue position ``to`` (a qid, 1-based)."""
        self.get(pid)
        if qids:
            await self._move(pid, ",".join(map(str, qids)), to)

    def sorting(self, pid: int) -> bool:
        lock = self._sorting.get(pid)
        return bool(lock and lock.locked())

    async def sort_queue(self, pid: int, by: str, order: str = "asc") -> dict[str, Any]:
        """Sort the HEOS queue on the device (F3.7) with the fewest single moves.

        Moves are paced (``MOVE_GAP``) and each is retried while the amp
        reports it is still busy (eid 12/13, see ``MOVE_RETRY_DELAYS``). If a
        move still fails, the sort re-reads the queue and plans again from
        where it actually is, up to ``SORT_ATTEMPTS`` times, so it never stops
        halfway silently. Raises ``ValueError`` for unknown or unavailable sort keys and
        ``RuntimeError`` if the queue's content changed underneath the sort.
        """
        self.get(pid)
        if order not in ("asc", "desc"):
            raise ValueError("order must be 'asc' or 'desc'")
        lock = self._sorting.setdefault(pid, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("a sort of this queue is already running")
        async with lock:
            try:
                items = await self.queue(pid)
                new_order = sort_order(items, by, descending=order == "desc")
                keys = _identity_keys(items)
                target = [keys[i] for i in new_order]
                sent = 0
                for attempt in range(1, SORT_ATTEMPTS + 1):
                    current = keys if attempt == 1 else _identity_keys(await self.queue(pid))
                    if sorted(current) != sorted(target):
                        raise RuntimeError("the queue changed while sorting; sort again")
                    moves = plan_moves(current, target)
                    total = sent + len(moves)
                    self.bus.publish("queue_sort", pid, {"state": "running", "done": sent, "total": total})
                    try:
                        for sqid, dqid in moves:
                            if sent:
                                await asyncio.sleep(MOVE_GAP)  # let the amp finish the previous move
                            await self._move(pid, sqid, dqid)
                            sent += 1
                            if sent % 10 == 0 and sent < total:
                                self.bus.publish("queue_sort", pid, {"state": "running", "done": sent, "total": total})
                    except HeosCommandError as err:
                        if err.eid not in (12, 13) or attempt == SORT_ATTEMPTS:
                            raise
                        log.warning("queue sort: move rejected (%s), re-planning (attempt %d)", err, attempt)
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    break
                if _identity_keys(await self.queue(pid)) != target:
                    raise RuntimeError("the queue changed while sorting; sort again")
                self.bus.publish("queue_sort", pid, {"state": "done", "done": sent, "total": sent})
                return {"by": by, "order": order, "items": len(items), "moves": sent}
            except Exception as err:
                self.bus.publish("queue_sort", pid, {"state": "failed", "error": str(err)})
                raise
            finally:
                self.bus.publish("queue_changed", pid)

    async def play_stream(self, pid: int, sid: int, mid: str, name: str, cid: str | None = None) -> None:
        """Play a station-like item (Amazon album/playlist/station). Replaces what is playing."""
        self.get(pid)
        await self.client.command(
            "browse/play_stream", {"pid": pid, "sid": sid, "cid": cid, "mid": mid, "name": name}, timeout=30
        )

    async def play_preset(self, pid: int, preset: int) -> None:
        """Play a HEOS Favorite by its 1-based position (F6.4)."""
        self.get(pid)
        await self.client.command("browse/play_preset", {"pid": pid, "preset": preset}, timeout=30)

    @staticmethod
    def _add_plan(items: list[dict[str, Any]], mode: str) -> list[tuple[dict[str, Any], int]]:
        """(item, aid) pairs that add ``items`` in order with the given mode.

        "next" adds them in reverse with "play next"; "now" and "replace" start
        with the first item and put the rest after it.
        """
        if not items:
            return []
        first, rest = items[0], items[1:]
        if mode == "end":
            return [(item, 3) for item in items]
        if mode == "next":
            return [(item, 2) for item in reversed(items)]
        if mode == "now":
            return [(first, 1)] + [(item, 2) for item in reversed(rest)]
        return [(first, 4)] + [(item, 3) for item in rest]  # replace

    async def add_to_queue(
        self,
        pid: int,
        items: list[dict[str, Any]],
        mode: str,
        expand: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Add browse/search items to the queue (F3.6); returns how many items were added.

        A whole container is tried first (one command). If the amp rejects it
        and ``expand`` is given, the container's tracks are added one by one
        instead, keeping their order for that mode. (With several items and
        mode "now", a fallback container's tracks may interleave; the UI sends
        one item at a time.)
        """
        self.get(pid)
        if mode not in ADD_MODES:
            raise ValueError(f"mode must be one of {sorted(ADD_MODES)}")
        mode_of_aid = {1: "now", 2: "next", 3: "end", 4: "replace"}
        added = 0
        plan = self._add_plan(items, mode)
        for step, (item, aid) in enumerate(plan, 1):
            if progress and len(plan) > 1 and (step == 1 or step % 10 == 0):
                progress(step - 1, len(plan))
            try:
                await self._add_one(pid, item, aid)
                added += 1
            except HeosCommandError as err:
                if expand is None or item.get("mid") or not item.get("cid"):
                    raise
                log.info("container %s not accepted whole (%s); adding its tracks", item.get("cid"), err)
                tracks = await expand(item)
                for track, track_aid in self._add_plan(tracks, mode_of_aid[aid]):
                    await self._add_one(pid, track, track_aid)
                added += len(tracks)
        if progress and len(plan) > 1:
            progress(len(plan), len(plan))
        return added

    async def _add_one(self, pid: int, item: dict[str, Any], aid: int) -> None:
        await self.client.command(
            "browse/add_to_queue",
            {"pid": pid, "sid": item["sid"], "cid": item.get("cid"), "mid": item.get("mid"), "aid": aid},
            timeout=30,
        )
