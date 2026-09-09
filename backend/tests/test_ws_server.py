"""Exercises ConnectionManager and websocket_endpoint directly against fake
WebSocket-like objects, rather than through FastAPI's TestClient (which
would need the `httpx` package, not otherwise needed by this project).
"""
import asyncio
import json

from fastapi import WebSocketDisconnect

from app.ws_server import ConnectionManager, websocket_endpoint


class FakeWebSocket:
    def __init__(self, disconnect_after: int = 0):
        self.accepted = False
        self.sent: list[str] = []
        self._recv_count = 0
        self.disconnect_after = disconnect_after

    async def accept(self):
        self.accepted = True

    async def send_text(self, payload: str):
        self.sent.append(payload)

    async def receive_text(self):
        self._recv_count += 1
        if self._recv_count > self.disconnect_after:
            raise WebSocketDisconnect()
        return "ping"


def test_connect_accepts_and_registers():
    async def run():
        manager = ConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)
        assert ws.accepted
        assert ws in manager._connections

    asyncio.run(run())


def test_disconnect_removes_connection():
    async def run():
        manager = ConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)
        await manager.disconnect(ws)
        assert ws not in manager._connections

    asyncio.run(run())


def test_broadcast_sends_json_to_all_connections():
    async def run():
        manager = ConnectionManager()
        a, b = FakeWebSocket(), FakeWebSocket()
        await manager.connect(a)
        await manager.connect(b)
        await manager.broadcast({"type": "debug", "detectedLabel": "calm", "confidence": 0.9})
        expected = json.dumps({"type": "debug", "detectedLabel": "calm", "confidence": 0.9})
        assert a.sent == [expected]
        assert b.sent == [expected]

    asyncio.run(run())


def test_broadcast_drops_connections_that_fail_to_send():
    async def run():
        manager = ConnectionManager()
        good, bad = FakeWebSocket(), FakeWebSocket()

        async def failing_send(_payload):
            raise RuntimeError("connection closed")

        bad.send_text = failing_send

        await manager.connect(good)
        await manager.connect(bad)
        await manager.broadcast({"type": "info", "message": "hi"})

        assert good in manager._connections
        assert bad not in manager._connections
        assert len(good.sent) == 1

    asyncio.run(run())


def test_websocket_endpoint_connects_then_cleans_up_on_disconnect():
    async def run():
        from app import ws_server

        ws = FakeWebSocket(disconnect_after=0)
        await websocket_endpoint(ws)
        assert ws.accepted
        assert ws not in ws_server.manager._connections

    asyncio.run(run())
