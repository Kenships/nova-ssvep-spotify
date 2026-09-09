"""Exercises app/main.py's route handlers and _detection_loop directly as
plain function calls (bypassing the ASGI/TestClient layer entirely, which
would need the `httpx` package this project doesn't otherwise depend on).

Every test that could reach a real Spotify network call monkeypatches
`spotify_client`'s methods first -- these tests must never be able to
issue a real playback command against a real device.
"""
import asyncio

import numpy as np
import pytest
from fastapi import HTTPException, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

from app import main
from app.commands.command_bus import CommandBus, Layer
from app.main import ManualCommandRequest


class BroadcastRecorder:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


def _run(coro):
    return asyncio.run(coro)


# --- simple REST routes ---------------------------------------------------


def test_get_moods_returns_configured_moods():
    result = main.get_moods()
    assert {m["id"] for m in result["moods"]} == {"calm", "happy", "energetic", "sad"}


def test_get_now_playing_passes_through_track_info(monkeypatch):
    monkeypatch.setattr(main.spotify_client, "now_playing", lambda: {"track": "Song"})
    assert main.get_now_playing() == {"track": "Song"}


def test_get_now_playing_returns_empty_dict_when_nothing_playing(monkeypatch):
    monkeypatch.setattr(main.spotify_client, "now_playing", lambda: None)
    assert main.get_now_playing() == {}


def test_spotify_status_reflects_client_state(monkeypatch):
    monkeypatch.setattr(main.spotify_client, "is_authenticated", lambda: True)
    assert main.spotify_status() == {"authenticated": True}
    monkeypatch.setattr(main.spotify_client, "is_authenticated", lambda: False)
    assert main.spotify_status() == {"authenticated": False}


def test_spotify_login_redirects_to_authorize_url(monkeypatch):
    fake_url = "https://accounts.spotify.com/authorize?client_id=abc"
    monkeypatch.setattr(main.spotify_client, "get_authorize_url", lambda: fake_url)
    response = main.spotify_login()
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == fake_url


def test_spotify_callback_error_branch():
    response = main.spotify_callback(code=None, error="access_denied")
    assert isinstance(response, HTMLResponse)
    assert response.status_code == 400
    assert b"failed" in response.body


def test_spotify_callback_missing_code_branch():
    response = main.spotify_callback(code=None, error=None)
    assert response.status_code == 400
    assert b"Missing authorization code" in response.body


def test_spotify_callback_success_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(main.spotify_client, "complete_authorization", lambda code: calls.append(code))
    response = main.spotify_callback(code="auth-code", error=None)
    assert response.status_code == 200
    assert calls == ["auth-code"]


def test_ws_commands_route_delegates_to_websocket_endpoint():
    class FakeWebSocket:
        def __init__(self):
            self.accepted = False
            self._recv_count = 0

        async def accept(self):
            self.accepted = True

        async def receive_text(self):
            self._recv_count += 1
            raise WebSocketDisconnect()

    ws = FakeWebSocket()
    _run(main.ws_commands(ws))
    assert ws.accepted


# --- _current_candidate_freqs ---------------------------------------------


def _fresh_command_bus(layer: Layer = Layer.MOOD, dwell_sec: float = 0.75, refractory_sec: float = 1.0) -> CommandBus:
    """A brand-new CommandBus per test -- never the shared main.command_bus
    singleton -- so a test that fires a command (and so enters refractory,
    which is real-wall-clock-timed) can never leak state into a later test.
    """
    return CommandBus(dwell_sec=dwell_sec, refractory_sec=refractory_sec, layer=layer)


def test_current_candidate_freqs_mood_layer(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.MOOD))
    freqs = main._current_candidate_freqs()
    assert freqs["calm"] == 7.5
    assert freqs["energetic"] == 10.0


def test_current_candidate_freqs_transport_layer(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.TRANSPORT))
    assert main._current_candidate_freqs() == main.settings.transport_frequencies


# --- _apply_spotify_side_effect -------------------------------------------


def test_apply_spotify_side_effect_mood_known_mood_plays_playlist(monkeypatch):
    calls = []
    monkeypatch.setattr(main.spotify_client, "play_playlist", lambda uri: calls.append(uri))
    main._apply_spotify_side_effect(Layer.MOOD, "calm")
    assert len(calls) == 1
    assert calls[0].startswith("spotify:playlist:")


def test_apply_spotify_side_effect_mood_unknown_mood_does_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(main.spotify_client, "play_playlist", lambda uri: calls.append(uri))
    main._apply_spotify_side_effect(Layer.MOOD, "not-a-real-mood")
    assert calls == []


@pytest.mark.parametrize(
    "label,expected_method",
    [("play_pause", "toggle_play_pause"), ("next", "next_track"), ("previous", "previous_track")],
)
def test_apply_spotify_side_effect_transport_dispatches_to_the_right_call(monkeypatch, label, expected_method):
    calls = []
    for method in ("toggle_play_pause", "next_track", "previous_track"):
        monkeypatch.setattr(main.spotify_client, method, lambda m=method: calls.append(m))
    main._apply_spotify_side_effect(Layer.TRANSPORT, label)
    assert calls == [expected_method]


def test_apply_spotify_side_effect_transport_unknown_label_does_nothing(monkeypatch):
    calls = []
    for method in ("toggle_play_pause", "next_track", "previous_track"):
        monkeypatch.setattr(main.spotify_client, method, lambda m=method: calls.append(m))
    main._apply_spotify_side_effect(Layer.TRANSPORT, "back_to_mood")
    assert calls == []


# --- _handle_fired_command -------------------------------------------------


def test_handle_fired_command_mood_switches_to_transport_and_broadcasts(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.MOOD))
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)

    _run(main._handle_fired_command("calm"))

    assert main.command_bus.layer == Layer.TRANSPORT
    assert recorder.messages == [{"type": "command", "layer": "mood", "target": "calm"}]


def test_handle_fired_command_back_to_mood_switches_back(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.TRANSPORT))
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())

    _run(main._handle_fired_command("back_to_mood"))

    assert main.command_bus.layer == Layer.MOOD


def test_handle_fired_command_other_transport_label_keeps_layer(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.TRANSPORT))
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())

    _run(main._handle_fired_command("next"))

    assert main.command_bus.layer == Layer.TRANSPORT


def test_handle_fired_command_swallows_spotify_side_effect_errors(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.MOOD))

    def boom(layer, label):
        raise RuntimeError("spotify is down")

    monkeypatch.setattr(main, "_apply_spotify_side_effect", boom)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)

    # Must not raise: a broken Spotify call must never block the command
    # from having already reached the frontend.
    _run(main._handle_fired_command("calm"))
    assert recorder.messages  # broadcast still happened before the failure


# --- manual_command ---------------------------------------------------------


def test_manual_command_valid_mood_target(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.TRANSPORT))  # deliberately "wrong" layer
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())

    result = _run(main.manual_command(ManualCommandRequest(target="calm")))

    assert result == {"layer": "transport", "target": "calm"}  # MOOD fire always switches to TRANSPORT
    assert main.command_bus.feed("calm", now=main.time.monotonic()) is None  # refractory engaged


def test_manual_command_valid_transport_target(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.MOOD))
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())

    result = _run(main.manual_command(ManualCommandRequest(target="next")))

    assert result == {"layer": "transport", "target": "next"}
    assert main.command_bus.layer == Layer.TRANSPORT


def test_manual_command_invalid_target_raises_400(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus())
    with pytest.raises(HTTPException) as exc_info:
        _run(main.manual_command(ManualCommandRequest(target="not-a-real-target")))
    assert exc_info.value.status_code == 400


# --- _detection_loop ---------------------------------------------------------


class _FlappyFakeIngest:
    """is_connected() reports disconnected for the first couple of polls,
    then connected -- but never returns enough data for a detection, so
    these tests isolate the connect/disconnect broadcast behavior."""

    def __init__(self):
        self.calls = 0

    def start(self):
        pass

    def is_connected(self):
        self.calls += 1
        return self.calls > 2

    def get_window(self):
        return np.empty((0, 4)), 0.0


class _SteadyFakeIngest:
    """Always connected, always returns the same pre-built window."""

    def __init__(self, window, fs):
        self._window = window
        self._fs = fs

    def start(self):
        pass

    def is_connected(self):
        return True

    def get_window(self):
        return self._window, self._fs


async def _run_briefly(coro, duration_sec):
    task = asyncio.create_task(coro)
    await asyncio.sleep(duration_sec)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_detection_loop_broadcasts_disconnect_then_reconnect(monkeypatch):
    monkeypatch.setattr(main, "ingest", _FlappyFakeIngest())
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)

    asyncio.run(_run_briefly(main._detection_loop(), 1.1))

    types_seen = [m["type"] for m in recorder.messages]
    assert "error" in types_seen
    assert "info" in types_seen
    assert types_seen.index("error") < types_seen.index("info")


def test_detection_loop_detects_and_fires_a_command(monkeypatch):
    fs = 250.0
    t = np.arange(int(fs * 2.0)) / fs
    sig = np.sin(2 * np.pi * 10.0 * t)  # "energetic" target is 10Hz
    rng = np.random.default_rng(0)
    window = np.tile(sig[:, None], (1, 4)) + rng.normal(0, 0.05, (len(t), 4))

    fresh_bus = CommandBus(dwell_sec=0.05, refractory_sec=0.05)
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))
    monkeypatch.setattr(main, "command_bus", fresh_bus)
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda layer, label: None)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)

    asyncio.run(_run_briefly(main._detection_loop(), 1.5))

    debug_msgs = [m for m in recorder.messages if m["type"] == "debug"]
    command_msgs = [m for m in recorder.messages if m["type"] == "command"]
    assert any(m["detectedLabel"] == "energetic" for m in debug_msgs)
    assert any(m["target"] == "energetic" for m in command_msgs)
    assert fresh_bus.layer == Layer.TRANSPORT


def test_detection_loop_logs_and_survives_handle_fired_command_errors(monkeypatch):
    """A failure inside _handle_fired_command itself (as opposed to one
    already swallowed by _apply_spotify_side_effect's own try/except) must
    be caught by _detection_loop's outer try/except so one bad command
    doesn't kill the whole detection loop for the rest of the session."""
    fs = 250.0
    t = np.arange(int(fs * 2.0)) / fs
    sig = np.sin(2 * np.pi * 10.0 * t)
    rng = np.random.default_rng(0)
    window = np.tile(sig[:, None], (1, 4)) + rng.normal(0, 0.05, (len(t), 4))

    fresh_bus = CommandBus(dwell_sec=0.05, refractory_sec=0.05)
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))
    monkeypatch.setattr(main, "command_bus", fresh_bus)

    async def flaky_broadcast(message):
        if message["type"] == "command":
            raise RuntimeError("broadcast boom")

    monkeypatch.setattr(main.manager, "broadcast", flaky_broadcast)

    async def run():
        task = asyncio.create_task(main._detection_loop())
        await asyncio.sleep(1.0)
        assert not task.done()  # the RuntimeError above must not have killed the loop
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


# --- startup/shutdown ---------------------------------------------------------


def test_startup_creates_detection_task_and_shutdown_cancels_it(monkeypatch):
    class NoopIngest:
        def start(self):
            pass

        def is_connected(self):
            return False  # loop just idles on the disconnected branch

        def get_window(self):
            return np.empty((0, 4)), 0.0

        def stop(self):
            self.stopped = True

    fake_ingest = NoopIngest()
    monkeypatch.setattr(main, "ingest", fake_ingest)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())

    async def run():
        await main.on_startup()
        assert main._detection_task is not None
        assert not main._detection_task.done()
        await main.on_shutdown()
        await asyncio.sleep(0)  # let the cancellation propagate
        assert main._detection_task.cancelled() or main._detection_task.done()

    asyncio.run(run())
    assert getattr(fake_ingest, "stopped", False) is True
