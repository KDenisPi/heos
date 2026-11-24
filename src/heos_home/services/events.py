"""In-process pub/sub that feeds the WebSocket clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_size = queue_size

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, type_: str, pid: int | None = None, data: dict[str, Any] | None = None) -> None:
        event: dict[str, Any] = {"type": type_}
        if pid is not None:
            event["pid"] = pid
        if data is not None:
            event["data"] = data
        for queue in list(self._subscribers):
            if queue.full():
                # A stalled client: drop its oldest event rather than block everyone.
                # Progress events are frequent, so this only loses stale updates.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
