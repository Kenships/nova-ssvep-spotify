"""Exercises smoke_test_ws_client.py's main() against a fake websockets
connection -- no real backend server is needed.
"""
import asyncio

import smoke_test_ws_client


class _FiniteMessages:
    """Fake `async with websockets.connect(...)` that yields a fixed list of
    messages then ends the stream naturally (no timeout involved)."""

    def __init__(self, messages):
        self._messages = messages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self._messages:
            yield m


class _HangingConnection:
    """Fake connection that never yields a message, so main()'s
    asyncio.timeout is what actually ends the loop."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        while True:
            await asyncio.sleep(10)
            yield "unreachable"


def test_main_prints_every_message_until_stream_ends(monkeypatch, capsys):
    monkeypatch.setattr(smoke_test_ws_client.websockets, "connect", lambda uri: _FiniteMessages(["a", "b"]))

    asyncio.run(smoke_test_ws_client.main(5.0))

    out = capsys.readouterr().out
    assert "a" in out
    assert "b" in out


def test_main_times_out_silently_if_nothing_arrives(monkeypatch, capsys):
    monkeypatch.setattr(smoke_test_ws_client.websockets, "connect", lambda uri: _HangingConnection())

    asyncio.run(smoke_test_ws_client.main(0.05))  # must return, not raise or hang

    assert capsys.readouterr().out == ""
