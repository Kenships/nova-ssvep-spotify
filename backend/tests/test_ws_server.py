"""Exercises ConnectionManager and websocket_endpoint directly against fake
WebSocket-like objects, rather than through FastAPI's TestClient (which
would need the `httpx` package, not otherwise needed by this project).
"""
import asyncio
import json

from fastapi import WebSocketDisconnect

from app.ws_server import ConnectionManager, websocket_endpoint


class FakeWebSocket:
    def __init__(self, disconnect_after: int = 0, messages: list[str] | None = None):
        self.accepted = False
        self.sent: list[str] = []
        self._recv_count = 0
        self.disconnect_after = disconnect_after
        # Texts to hand back from receive_text() in order, before
        # disconnecting; defaults to an innocuous non-JSON keepalive.
        self._messages = messages

    async def accept(self):
        self.accepted = True

    async def send_text(self, payload: str):
        self.sent.append(payload)

    async def receive_text(self):
        self._recv_count += 1
        if self._recv_count > self.disconnect_after:
            raise WebSocketDisconnect()
        if self._messages:
            return self._messages[min(self._recv_count - 1, len(self._messages) - 1)]
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


def test_set_raw_subscription_adds_and_removes():
    async def run():
        manager = ConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)
        assert not manager.has_raw_subscribers()

        await manager.set_raw_subscription(ws, True)
        assert manager.has_raw_subscribers()
        assert ws in manager._raw_subscribers

        await manager.set_raw_subscription(ws, False)
        assert not manager.has_raw_subscribers()

    asyncio.run(run())


def test_disconnect_also_drops_raw_subscription():
    async def run():
        manager = ConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)
        await manager.set_raw_subscription(ws, True)

        await manager.disconnect(ws)

        assert not manager.has_raw_subscribers()

    asyncio.run(run())


def test_broadcast_raw_sends_only_to_subscribers():
    async def run():
        manager = ConnectionManager()
        sub, plain = FakeWebSocket(), FakeWebSocket()
        await manager.connect(sub)
        await manager.connect(plain)
        await manager.set_raw_subscription(sub, True)

        await manager.broadcast_raw({"type": "raw", "samples": [[1.0]]})

        assert sub.sent == [json.dumps({"type": "raw", "samples": [[1.0]]})]
        assert plain.sent == []

    asyncio.run(run())


def test_broadcast_raw_drops_failing_subscriber():
    async def run():
        manager = ConnectionManager()
        bad = FakeWebSocket()

        async def failing_send(_payload):
            raise RuntimeError("connection closed")

        bad.send_text = failing_send
        await manager.connect(bad)
        await manager.set_raw_subscription(bad, True)

        await manager.broadcast_raw({"type": "raw"})

        assert bad not in manager._connections
        assert not manager.has_raw_subscribers()

    asyncio.run(run())


def test_websocket_endpoint_ignores_non_json_text():
    async def run():
        ws = FakeWebSocket(disconnect_after=2, messages=["not-json", "{also not json"])
        await websocket_endpoint(ws)
        assert ws.accepted  # malformed frames don't crash the loop

    asyncio.run(run())


def test_websocket_endpoint_ignores_valid_json_that_is_not_an_object():
    async def run():
        # "42", "null", "[1,2]", '"x"' all parse without error but aren't
        # dicts -- msg.get("type") would raise AttributeError if reached.
        ws = FakeWebSocket(disconnect_after=3, messages=["42", "null", "[1, 2]"])
        await websocket_endpoint(ws)
        assert ws.accepted  # non-object JSON frames don't crash the loop

    asyncio.run(run())


def test_websocket_endpoint_applies_raw_subscribe_and_unsubscribe(monkeypatch):
    from app import ws_server

    calls: list[bool] = []

    async def fake_set_raw_subscription(_ws, subscribed):
        calls.append(subscribed)

    monkeypatch.setattr(ws_server.manager, "set_raw_subscription", fake_set_raw_subscription)

    async def run():
        ws = FakeWebSocket(
            disconnect_after=2,
            messages=[json.dumps({"type": "raw_subscribe"}), json.dumps({"type": "raw_unsubscribe"})],
        )
        await websocket_endpoint(ws)

    asyncio.run(run())
    assert calls == [True, False]


def test_websocket_endpoint_ignores_unrecognized_message_type():
    async def run():
        from app import ws_server

        ws = FakeWebSocket(disconnect_after=1, messages=[json.dumps({"type": "something_else"})])
        await websocket_endpoint(ws)
        assert not ws_server.manager.has_raw_subscribers()

    asyncio.run(run())


def test_websocket_endpoint_connects_then_cleans_up_on_disconnect():
    async def run():
        from app import ws_server

        ws = FakeWebSocket(disconnect_after=0)
        await websocket_endpoint(ws)
        assert ws.accepted
        assert ws not in ws_server.manager._connections

    asyncio.run(run())
