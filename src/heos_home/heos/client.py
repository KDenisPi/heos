"""The single, long-lived HEOS CLI connection (TCP 1255).

* Commands are serialized: one command is in flight at a time, and its
  response is matched by command name. ``command under process`` interim
  replies are skipped until the real response arrives.
* Unsolicited ``event/*`` messages are handed to listeners in arrival order by a
  separate dispatcher task, so a slow listener never stalls the socket reader.
* A heartbeat runs every 30 s; on any socket failure the client reconnects with
  exponential backoff (1 s to 30 s) and re-registers for change events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .protocol import (
    DELIMITER,
    HeosCommandError,
    HeosConnectionError,
    HeosMessage,
    HeosTimeoutError,
    build_command,
)

log = logging.getLogger(__name__)
wire_log = logging.getLogger("heos_home.wire")

HEOS_PORT = 1255
EventListener = Callable[[HeosMessage], Awaitable[None]]
ConnectionListener = Callable[[bool], Awaitable[None]]

_EID_BUSY = 13  # "Processing previous command"


class HeosClient:
    def __init__(
        self,
        host: str | None = None,
        port: int = HEOS_PORT,
        *,
        command_timeout: float = 10.0,
        heartbeat_interval: float = 30.0,
        backoff_min: float = 1.0,
        backoff_max: float = 30.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.command_timeout = command_timeout
        self.heartbeat_interval = heartbeat_interval
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self.connect_timeout = connect_timeout

        self._event_listeners: list[EventListener] = []
        self._connection_listeners: list[ConnectionListener] = []

        self._lock = asyncio.Lock()
        self._pending: tuple[str, asyncio.Future[HeosMessage]] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._socket_open = False
        self._connected = False
        self._stopping = False
        self._wake = asyncio.Event()
        self._events: asyncio.Queue[HeosMessage] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self._connected_event = asyncio.Event()
        self.last_error: str | None = None

    # ------------------------------------------------------------------ setup
    def add_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.append(listener)

    def add_connection_listener(self, listener: ConnectionListener) -> None:
        self._connection_listeners.append(listener)

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._stopping = False
        self._tasks = [
            asyncio.create_task(self._run(), name="heos-connection"),
            asyncio.create_task(self._dispatch_events(), name="heos-events"),
        ]

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        await self._close_socket()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []

    async def set_host(self, host: str | None) -> None:
        """Point the connection at another device (e.g. after rediscovery)."""
        if host == self.host and self._connected:
            return
        log.info("HEOS host set to %s", host)
        self.host = host
        await self._close_socket()
        self._wake.set()

    async def wait_connected(self, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    # --------------------------------------------------------------- commands
    async def command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retries: int = 2,
    ) -> HeosMessage:
        """Send a command and return its decoded response.

        Raises ``HeosCommandError`` when the device reports ``result=fail``.
        """
        if not self._connected:
            raise HeosConnectionError("not connected to a HEOS device")
        return await self._command(command, params, timeout=timeout, retries=retries)

    async def _command(
        self,
        command: str,
        params: dict[str, Any] | None,
        *,
        timeout: float | None,
        retries: int,
    ) -> HeosMessage:
        attempt = 0
        while True:
            try:
                return await self._send_once(command, params, timeout or self.command_timeout)
            except HeosCommandError as err:
                if err.eid == _EID_BUSY and attempt < retries:
                    attempt += 1
                    await asyncio.sleep(0.25 * attempt)
                    continue
                raise

    async def _send_once(self, command: str, params: dict[str, Any] | None, timeout: float) -> HeosMessage:
        line = build_command(command, params)
        async with self._lock:
            writer = self._writer
            if writer is None or not self._socket_open:
                raise HeosConnectionError("not connected to a HEOS device")
            future: asyncio.Future[HeosMessage] = asyncio.get_running_loop().create_future()
            self._pending = (command, future)
            try:
                wire_log.debug(">> %s", _redact(line))
                writer.write(line.encode() + DELIMITER)
                await writer.drain()
                message = await asyncio.wait_for(future, timeout)
            except asyncio.TimeoutError as err:
                raise HeosTimeoutError(f"{command}: no response within {timeout:.0f} s") from err
            except (ConnectionError, OSError) as err:
                raise HeosConnectionError(f"{command}: {err}") from err
            finally:
                self._pending = None
        message.raise_for_error()
        return message

    # ------------------------------------------------------------ connection
    async def _run(self) -> None:
        delay = self.backoff_min
        while not self._stopping:
            if not self.host:
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                await self._connect_once()
                delay = self.backoff_min
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - any failure means reconnect
                self.last_error = str(err) or type(err).__name__
                log.warning("HEOS connection to %s failed: %s", self.host, self.last_error)
            finally:
                await self._set_connected(False)
                await self._close_socket()
            if self._stopping:
                break
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)
            delay = min(delay * 2, self.backoff_max)

    async def _connect_once(self) -> None:
        host = self.host
        assert host
        log.info("connecting to HEOS CLI at %s:%s", host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, self.port, limit=8 * 1024 * 1024),
            self.connect_timeout,
        )
        self._socket_open = True
        reader_task = asyncio.create_task(self._read_loop(self._reader), name="heos-reader")
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            await self._command("system/register_for_change_events", {"enable": "on"}, timeout=None, retries=2)
            self.last_error = None
            await self._set_connected(True)
            heartbeat_task = asyncio.create_task(self._heartbeat(), name="heos-heartbeat")
            await reader_task  # returns when the socket closes
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await heartbeat_task
            if not reader_task.done():
                reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                try:
                    raw = await reader.readuntil(DELIMITER)
                except asyncio.IncompleteReadError:
                    log.warning("HEOS device closed the connection")
                    break
                except asyncio.LimitOverrunError:
                    log.error("HEOS response too large, dropping connection")
                    break
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                wire_log.debug("<< %s", text)
                try:
                    message = HeosMessage.from_json(json.loads(text))
                except (ValueError, AttributeError) as err:
                    log.warning("unparseable HEOS message (%s): %.200s", err, text)
                    continue
                self._handle_message(message)
        except (ConnectionError, OSError) as err:
            log.warning("HEOS socket error: %s", err)
        finally:
            self._socket_open = False
            if self._pending and not self._pending[1].done():
                self._pending[1].set_exception(HeosConnectionError("connection lost"))

    def _handle_message(self, message: HeosMessage) -> None:
        if message.is_event:
            self._events.put_nowait(message)
            return
        pending = self._pending
        if pending is None or pending[1].done():
            log.debug("unexpected HEOS response: %s", message.command)
            return
        if message.command != pending[0]:
            log.debug("stale HEOS response %s while waiting for %s", message.command, pending[0])
            return
        if message.is_under_process:
            return
        pending[1].set_result(message)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._command("system/heart_beat", None, timeout=None, retries=0)
            except (HeosTimeoutError, HeosConnectionError) as err:
                log.warning("heartbeat failed (%s), reconnecting", err)
                await self._close_socket()
                return
            except HeosCommandError:
                pass  # the device answered, so the socket is alive

    async def _dispatch_events(self) -> None:
        while True:
            message = await self._events.get()
            for listener in list(self._event_listeners):
                try:
                    await listener(message)
                except Exception:  # noqa: BLE001
                    log.exception("event listener failed for %s", message.command)

    async def _set_connected(self, value: bool) -> None:
        if self._connected == value:
            return
        self._connected = value
        if value:
            self._connected_event.set()
            log.info("HEOS CLI connected to %s", self.host)
        else:
            self._connected_event.clear()
            log.info("HEOS CLI disconnected")
        for listener in list(self._connection_listeners):
            try:
                await listener(value)
            except Exception:  # noqa: BLE001
                log.exception("connection listener failed")

    async def _close_socket(self) -> None:
        writer, self._writer = self._writer, None
        self._socket_open = False
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(writer.wait_closed(), 2)


def _redact(line: str) -> str:
    if "system/sign_in" in line and "pw=" in line:
        head, _, _ = line.partition("pw=")
        return head + "pw=***"
    return line
