"""WebSocket /api/v1/ws: pushes typed state events; clients never poll.

On connect the client first gets a ``snapshot`` with the full state, then a
stream of events such as ``{"type":"volume","pid":-1234,"data":{...}}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    svc = ws.app.state.services
    await ws.accept()
    queue = svc.bus.subscribe()
    try:
        await ws.send_json(
            {
                "type": "snapshot",
                "data": {
                    "connection": {"connected": svc.client.connected, "host": svc.client.host},
                    "players": [p.to_dict() for p in svc.players.players.values()],
                    "devices": svc.devices.list(),
                    "account": svc.players.account,
                },
            }
        )
        receiver = asyncio.create_task(_drain_incoming(ws))
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if receiver in done:
                    getter.cancel()
                    break
                await ws.send_json(getter.result())
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
    except WebSocketDisconnect:
        pass
    finally:
        svc.bus.unsubscribe(queue)


async def _drain_incoming(ws: WebSocket) -> None:
    """Answer pings and notice when the client goes away."""
    try:
        while True:
            message = await ws.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        return
