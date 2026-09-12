"""Broadcasts detected commands + debug telemetry to the frontend over a
single persistent WebSocket. The frontend never polls; it only reacts to
pushed {"type": "command", ...} / {"type": "debug", ...} messages.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        # Subset of _connections that opted into raw per-sample channel data
        # (the debug panel's live graph) -- kept separate from the main
        # broadcast so idle/closed debug panels don't pay for a stream of
        # full EEG windows several times a second.
        self._raw_subscribers: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            self._raw_subscribers.discard(ws)

    async def set_raw_subscription(self, ws: WebSocket, subscribed: bool) -> None:
        async with self._lock:
            if subscribed:
                self._raw_subscribers.add(ws)
            else:
                self._raw_subscribers.discard(ws)

    def has_raw_subscribers(self) -> bool:
        return bool(self._raw_subscribers)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._connections)
        await self._send_to(targets, message)

    async def broadcast_raw(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._raw_subscribers)
        await self._send_to(targets, message)

    async def _send_to(self, targets: list[WebSocket], message: dict) -> None:
        payload = json.dumps(message)
        dead = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket, initial_state: Callable[[], dict] | None = None) -> None:
    await manager.connect(ws)
    try:
        if initial_state is not None:
            await ws.send_text(json.dumps(initial_state()))
        while True:
            # The frontend only sends raw_subscribe/raw_unsubscribe (to
            # toggle the debug panel's live graph); anything else -- or
            # non-JSON keepalive text -- is ignored, but receiving keeps the
            # socket alive and lets us detect disconnects promptly.
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue  # valid JSON but not an object, e.g. "42" or "null" -- nothing to dispatch on
            if msg.get("type") == "raw_subscribe":
                await manager.set_raw_subscription(ws, True)
            elif msg.get("type") == "raw_unsubscribe":
                await manager.set_raw_subscription(ws, False)
    except WebSocketDisconnect:
        logger.info("Frontend WebSocket disconnected")
    finally:
        await manager.disconnect(ws)
