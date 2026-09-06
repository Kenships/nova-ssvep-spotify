"""Broadcasts detected commands + debug telemetry to the frontend over a
single persistent WebSocket. The frontend never polls; it only reacts to
pushed {"type": "command", ...} / {"type": "debug", ...} messages.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message)
        dead = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Frontend doesn't need to send anything, but keep the socket
            # alive and detect disconnects promptly.
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("Frontend WebSocket disconnected")
    finally:
        await manager.disconnect(ws)
