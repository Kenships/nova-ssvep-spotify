"""Exercises app/main.py's route handlers and _detection_loop directly as
plain function calls (bypassing the ASGI/TestClient layer entirely, which
would need the `httpx` package this project doesn't otherwise depend on).

Every test that could reach a real Spotify network call monkeypatches
`spotify_client`'s methods first -- these tests must never be able to
issue a real playback command against a real device.
"""
import asyncio
import json
import threading
import time

import numpy as np
import pytest
from fastapi import HTTPException, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

from app import main
from app.calibration import DEFAULT_SNR_OK_THRESHOLD
from app.commands.command_bus import CommandBus, Layer
from app.main import ManualCommandRequest
from app.signal.detector import Detector


class BroadcastRecorder:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def isolate_control_state(monkeypatch):
    monkeypatch.setattr(main, "_control_lock", asyncio.Lock())
    monkeypatch.setattr(main, "_ingest_lock", asyncio.Lock())
    monkeypatch.setattr(main, "_calibration_active", False)
    monkeypatch.setattr(main, "_current_mood", None)
    monkeypatch.setattr(main, "_control_revision", 0)
    monkeypatch.setattr(main, "_switching_stream", False)


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


# --- LSL input-source status/discover/switch ---------------------------------


class _FakeIngestForStatus:
    def __init__(
        self,
        stream_name="MockEEG",
        connected=True,
        fs=250.0,
        channel_labels=None,
        occipital_indices=None,
        hostname="host",
    ):
        self.stream_name = stream_name
        self._connected = connected
        self.fs = fs
        self.channel_labels = channel_labels if channel_labels is not None else ["Oz", "O1"]
        self.occipital_indices = occipital_indices if occipital_indices is not None else [0, 1]
        self.hostname = hostname
        self.switch_calls: list[str] = []

    def is_connected(self):
        return self._connected

    def switch_stream(self, name):
        self.switch_calls.append(name)
        self.stream_name = name


def test_get_lsl_status_reflects_ingest_state(monkeypatch):
    fake = _FakeIngestForStatus(
        stream_name="MockEEG",
        connected=True,
        fs=250.0,
        channel_labels=["Oz", "O1"],
        occipital_indices=[0, 1],
        hostname="KenAsus",
    )
    monkeypatch.setattr(main, "ingest", fake)

    assert main.get_lsl_status() == {
        "stream_name": "MockEEG",
        "connected": True,
        "fs": 250.0,
        "channel_count": 2,
        "channel_labels": ["Oz", "O1"],
        "occipital_indices": [0, 1],
        "hostname": "KenAsus",
    }


def test_get_lsl_discover_returns_streams_from_the_network_scan(monkeypatch):
    fake_streams = [{"name": "X", "type": "EEG", "channel_count": 1, "nominal_srate": 250.0, "hostname": "h"}]
    monkeypatch.setattr(main, "discover_streams", lambda wait_time: fake_streams)

    assert main.get_lsl_discover(timeout=2.0) == {"streams": fake_streams}


def test_post_lsl_switch_success_returns_new_status(monkeypatch):
    fake = _FakeIngestForStatus(stream_name="Old")
    monkeypatch.setattr(main, "ingest", fake)

    result = _run(main.post_lsl_switch(main.LSLSwitchRequest(stream_name="New")))

    assert fake.switch_calls == ["New"]
    assert result["stream_name"] == "New"


def test_post_lsl_switch_raises_503_when_stream_not_found(monkeypatch):
    class _FailingIngest(_FakeIngestForStatus):
        def switch_stream(self, name):
            raise RuntimeError(f"No LSL stream named '{name}' found")

    monkeypatch.setattr(main, "ingest", _FailingIngest())

    with pytest.raises(HTTPException) as exc_info:
        _run(main.post_lsl_switch(main.LSLSwitchRequest(stream_name="Nonexistent")))

    assert exc_info.value.status_code == 503


# --- calibration SNR ---------------------------------------------------------


def _sine_window(freq_hz: float, fs: float, duration_sec: float = 2.0, n_channels: int = 4, noise: float = 0.02):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = np.sin(2 * np.pi * freq_hz * t)
    rng = np.random.default_rng(0)
    return np.tile(sig[:, None], (1, n_channels)) + rng.normal(0, noise, (len(t), n_channels))


class _DisconnectedFakeIngest:
    def is_connected(self):
        return False


class _EmptyWindowFakeIngest:
    def is_connected(self):
        return True

    def get_window(self):
        return np.empty((0, 4)), 0.0


class _ShortWindowFakeIngest:
    def is_connected(self):
        return True

    def get_window(self):
        return np.zeros((10, 4)), 250.0


def test_calibration_snr_invalid_label_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        main.get_calibration_snr(label="not-a-real-mood")
    assert exc_info.value.status_code == 400


def test_calibration_snr_not_ready_when_disconnected(monkeypatch):
    monkeypatch.setattr(main, "ingest", _DisconnectedFakeIngest())
    assert main.get_calibration_snr(label="energetic") == {
        "label": "energetic",
        "ready": False,
        "snr": 0.0,
        "ok": False,
    }


def test_calibration_snr_not_ready_when_window_empty(monkeypatch):
    monkeypatch.setattr(main, "ingest", _EmptyWindowFakeIngest())
    result = main.get_calibration_snr(label="energetic")
    assert result["ready"] is False


def test_calibration_snr_not_ready_when_window_too_short(monkeypatch):
    monkeypatch.setattr(main, "ingest", _ShortWindowFakeIngest())
    result = main.get_calibration_snr(label="energetic")
    assert result["ready"] is False


def test_calibration_snr_reports_ok_for_clean_signal(monkeypatch):
    fs = 250.0
    window = _sine_window(18.0, fs, duration_sec=main.settings.window_sec + 0.5)  # "energetic" mood's target is 18Hz
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))

    result = main.get_calibration_snr(label="energetic")

    assert result["label"] == "energetic"
    assert result["ready"] is True
    assert result["ok"] is True
    assert result["snr"] >= DEFAULT_SNR_OK_THRESHOLD


def test_calibration_snr_reports_not_ok_for_noise(monkeypatch):
    fs = 250.0
    rng = np.random.default_rng(1)
    window = rng.normal(0, 1.0, (int(fs * (main.settings.window_sec + 0.5)), 4))
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))

    result = main.get_calibration_snr(label="energetic")

    assert result["ready"] is True
    assert result["ok"] is False


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


def test_get_detection_config_reflects_command_bus_dwell(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(dwell_sec=1.25))
    assert main.get_detection_config() == {
        "dwell_sec": 1.25, "window_sec": main.settings.window_sec,
        "confidence_threshold": main.detector.confidence_threshold, "detector_backend": main.detector.backend,
    }


def test_set_detection_config_updates_command_bus_dwell(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(dwell_sec=0.75))
    result = main.set_detection_config(main.DwellConfigUpdate(dwell_sec=2.0))
    assert result == main.get_detection_config()
    assert result["dwell_sec"] == 2.0
    assert main.command_bus.dwell_sec == 2.0


def test_set_detection_config_rejects_non_positive_dwell(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(dwell_sec=0.75))
    with pytest.raises(HTTPException) as exc_info:
        main.set_detection_config(main.DwellConfigUpdate(dwell_sec=0))
    assert exc_info.value.status_code == 400
    assert main.command_bus.dwell_sec == 0.75  # left untouched


def test_spotify_callback_success_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(main.spotify_client, "complete_authorization", lambda code: calls.append(code))
    response = main.spotify_callback(code="auth-code", error=None)
    assert response.status_code == 200
    assert calls == ["auth-code"]


def test_ws_commands_route_delegates_to_websocket_endpoint(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(Layer.TRANSPORT))
    monkeypatch.setattr(main, "_current_mood", "calm")
    class FakeWebSocket:
        def __init__(self):
            self.accepted = False
            self.sent = []
            self._recv_count = 0

        async def accept(self):
            self.accepted = True

        async def send_text(self, payload):
            self.sent.append(json.loads(payload))

        async def receive_text(self):
            self._recv_count += 1
            raise WebSocketDisconnect()

    ws = FakeWebSocket()
    _run(main.ws_commands(ws))
    assert ws.accepted
    assert ws.sent == [{"type": "state", "layer": "transport", "currentMoodId": "calm", "calibrationActive": False}]


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
    assert freqs["calm"] == 15.0
    assert freqs["energetic"] == 18.0


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
    assert recorder.messages == [
        {"type": "command", "layer": "mood", "target": "calm"},
        {"type": "state", "layer": "transport", "currentMoodId": "calm", "calibrationActive": False},
    ]


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


# --- _broadcast_raw_debug_window ---------------------------------------------


class _RawCapableFakeIngest:
    def __init__(self, window, fs):
        self._window = window
        self._fs = fs
        self.channel_labels = ["0", "1", "2", "3", "4", "5", "6", "7", "8"]
        self.occipital_indices = [5, 6, 7]
        self.inlet = object()  # non-None: _detection_loop treats this as already started

    def start(self):
        pass

    def is_connected(self):
        return True

    def get_window(self, window_sec=None):
        return self._window, self._fs


def test_broadcast_raw_debug_window_noop_without_subscribers(monkeypatch):
    monkeypatch.setattr(main, "ingest", _RawCapableFakeIngest(np.zeros((10, 3)), 250.0))
    monkeypatch.setattr(main.manager, "has_raw_subscribers", lambda: False)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast_raw", recorder)

    _run(main._broadcast_raw_debug_window())

    assert recorder.messages == []


def test_broadcast_raw_debug_window_noop_when_window_empty(monkeypatch):
    monkeypatch.setattr(main, "ingest", _RawCapableFakeIngest(np.empty((0, 3)), 0.0))
    monkeypatch.setattr(main.manager, "has_raw_subscribers", lambda: True)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast_raw", recorder)

    _run(main._broadcast_raw_debug_window())

    assert recorder.messages == []


def test_broadcast_raw_debug_window_sends_samples_and_labels(monkeypatch):
    window = np.array([[1.111, 2.222, 3.333], [4.0, 5.0, 6.0]])
    monkeypatch.setattr(main, "ingest", _RawCapableFakeIngest(window, 250.0))
    monkeypatch.setattr(main.manager, "has_raw_subscribers", lambda: True)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast_raw", recorder)

    _run(main._broadcast_raw_debug_window())

    assert len(recorder.messages) == 1
    msg = recorder.messages[0]
    assert msg["type"] == "raw"
    assert msg["fs"] == 250.0
    assert msg["channelLabels"] == ["5", "6", "7"]
    assert msg["samples"] == [[1.11, 2.22, 3.33], [4.0, 5.0, 6.0]]


# --- _detection_loop ---------------------------------------------------------


class _FlappyFakeIngest:
    """is_connected() reports disconnected for the first couple of polls,
    then connected -- but never returns enough data for a detection, so
    these tests isolate the connect/disconnect broadcast behavior."""

    def __init__(self):
        self.calls = 0
        self.inlet = object()  # non-None: _detection_loop treats this as already started

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
        self.inlet = object()  # non-None: _detection_loop treats this as already started

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


class _StartsLateFakeIngest:
    """inlet stays None (start() keeps raising, as it would if the real data
    source isn't up yet at backend startup) for the first couple of ticks,
    then start() succeeds -- regression guard for the bug where a failed
    *first* start() call used to raise out of _detection_loop entirely,
    silently killing the whole detection task forever (2026-09-12)."""

    def __init__(self, fail_times: int):
        self.inlet = None
        self._fail_times = fail_times
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        if self.start_calls <= self._fail_times:
            raise RuntimeError("data source not up yet")
        self.inlet = object()

    def is_connected(self):
        return self.inlet is not None

    def get_window(self):
        return np.empty((0, 4)), 0.0


def test_detection_loop_retries_start_until_the_source_comes_up(monkeypatch):
    fake = _StartsLateFakeIngest(fail_times=2)
    monkeypatch.setattr(main, "ingest", fake)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)

    asyncio.run(_run_briefly(main._detection_loop(), 1.1))

    assert fake.start_calls >= 3  # 2 failures, then the successful attempt
    assert fake.inlet is not None
    assert fake.is_connected() is True


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
    sig = np.sin(2 * np.pi * 18.0 * t)  # "energetic" target is 18Hz
    rng = np.random.default_rng(0)
    window = np.tile(sig[:, None], (1, 4)) + rng.normal(0, 0.05, (len(t), 4))

    fresh_bus = CommandBus(dwell_sec=0.05, refractory_sec=0.05)
    # A fresh psda Detector at a fixed 2.0s/0.35 config, decoupled from
    # whatever DETECTOR_BACKEND/WINDOW_SEC/CONFIDENCE_THRESHOLD happen to be
    # in the real .env right now -- this test exercises _detection_loop's
    # wiring (detect -> broadcast -> command_bus.feed -> fire), not any
    # particular backend's numerical behavior (see test_fbcca.py/test_psda.py
    # for that).
    fresh_detector = Detector(
        backend="psda", bandpass_low_hz=5.0, bandpass_high_hz=40.0, mains_notch_hz=60.0, confidence_threshold=0.3
    )
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))
    monkeypatch.setattr(main, "command_bus", fresh_bus)
    monkeypatch.setattr(main, "detector", fresh_detector)
    monkeypatch.setattr(main.settings, "window_sec", 2.0)
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
    sig = np.sin(2 * np.pi * 18.0 * t)  # "energetic" target is 18Hz
    rng = np.random.default_rng(0)
    window = np.tile(sig[:, None], (1, 4)) + rng.normal(0, 0.05, (len(t), 4))

    fresh_bus = CommandBus(dwell_sec=0.05, refractory_sec=0.05)
    fresh_detector = Detector(
        backend="psda", bandpass_low_hz=5.0, bandpass_high_hz=40.0, mains_notch_hz=60.0, confidence_threshold=0.3
    )
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(window, fs))
    monkeypatch.setattr(main, "command_bus", fresh_bus)
    monkeypatch.setattr(main, "detector", fresh_detector)
    monkeypatch.setattr(main.settings, "window_sec", 2.0)

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



def test_calibration_pauses_commands_and_resumes_after_fresh_window(monkeypatch):
    bus = _fresh_command_bus()
    bus.feed("calm", now=0)
    monkeypatch.setattr(main, "command_bus", bus)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)
    effects = []
    monkeypatch.setattr(main, "_apply_spotify_side_effect", lambda *args: effects.append(args))

    async def run():
        state = await main.set_calibration_session(main.CalibrationRequest(active=True))
        assert state["calibrationActive"] is True
        assert bus._pending_label is None
        with pytest.raises(HTTPException) as exc:
            await main.manual_command(ManualCommandRequest(target="calm"))
        assert exc.value.status_code == 409
        assert effects == []
        assert bus.layer == Layer.MOOD
        before = time.monotonic()
        state = await main.set_calibration_session(main.CalibrationRequest(active=False))
        assert state["calibrationActive"] is False
        assert bus._refractory_until >= before + main.settings.window_sec
        await main.manual_command(ManualCommandRequest(target="calm"))
        assert effects == [(Layer.MOOD, "calm")]
    asyncio.run(run())


def test_calibration_keeps_detection_loop_alive_without_playback(monkeypatch):
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(_sine_window(15, 250), 250))
    monkeypatch.setattr(main, "_calibration_active", True)
    bus = _fresh_command_bus()
    bus.feed("calm", now=0)
    monkeypatch.setattr(main, "command_bus", bus)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)
    asyncio.run(_run_briefly(main._detection_loop(), 0.6))
    assert bus._pending_label is None
    assert not any(m["type"] == "command" for m in recorder.messages)


def test_disconnection_discards_pending_dwell(monkeypatch):
    fake = _FlappyFakeIngest()
    bus = _fresh_command_bus()
    bus.feed("calm", now=0)
    monkeypatch.setattr(main, "ingest", fake)
    monkeypatch.setattr(main, "command_bus", bus)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())
    asyncio.run(_run_briefly(main._detection_loop(), 0.4))
    assert bus.feed("calm", now=10) is None


def test_detection_from_previous_state_is_discarded(monkeypatch):
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus())
    recorder = BroadcastRecorder()
    monkeypatch.setattr(main.manager, "broadcast", recorder)
    asyncio.run(main._handle_fired_command("calm", expected_revision=-1))
    assert recorder.messages == []
    assert main.command_bus.layer == Layer.MOOD


def test_calibration_entered_during_debug_broadcast_cannot_fire(monkeypatch):
    monkeypatch.setattr(main, "ingest", _SteadyFakeIngest(_sine_window(15, 250), 250))
    monkeypatch.setattr(main.settings, "window_sec", 2.0)
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(dwell_sec=0))
    seen = []
    async def broadcast(message):
        seen.append(message)
        if message["type"] == "debug":
            await main.set_calibration_session(main.CalibrationRequest(active=True))
    monkeypatch.setattr(main.manager, "broadcast", broadcast)
    asyncio.run(_run_briefly(main._detection_loop(), 0.6))
    assert any(m["type"] == "debug" for m in seen)
    assert not any(m["type"] == "command" for m in seen)


def test_blocking_start_does_not_block_api_event_loop(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class SlowIngest(_StartsLateFakeIngest):
        def start(self):
            entered.set()
            assert release.wait(2)
            super().start()
    fake = SlowIngest(fail_times=0)
    monkeypatch.setattr(main, "ingest", fake)
    monkeypatch.setattr(main.manager, "broadcast", BroadcastRecorder())
    async def run():
        task = asyncio.create_task(main._detection_loop())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            # This coroutine can run while the worker is blocked in discovery.
            state = await main.set_calibration_session(main.CalibrationRequest(active=True))
            assert state["calibrationActive"]
        finally:
            release.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    asyncio.run(run())



def test_confidence_update_changes_live_detector_and_resets_dwell(monkeypatch):
    live_detector = Detector("psda", 5, 40, 60, 0.45)
    monkeypatch.setattr(main, "detector", live_detector)
    bus = _fresh_command_bus(dwell_sec=1.5)
    bus.feed("calm", now=0)
    monkeypatch.setattr(main, "command_bus", bus)
    # A score between the old and new gates must become acceptable.
    monkeypatch.setattr(live_detector, "_normalize", lambda scores: {"calm": 0.4})
    window = _sine_window(15, 250)
    assert live_detector.detect(window, 250, {"calm": 15})[0] is None
    result = main.set_detection_config(main.DwellConfigUpdate(confidence_threshold=0.35))
    assert result["confidence_threshold"] == 0.35
    assert result["dwell_sec"] == 1.5
    assert bus._pending_label is None
    assert live_detector.detect(window, 250, {"calm": 15})[0] == "calm"


@pytest.mark.parametrize("value", [0, -0.1, 1.1, float("nan"), float("inf")])
def test_confidence_update_rejects_invalid_values_atomically(monkeypatch, value):
    monkeypatch.setattr(main, "detector", Detector("psda", 5, 40, 60, 0.45))
    monkeypatch.setattr(main, "command_bus", _fresh_command_bus(dwell_sec=1.5))
    with pytest.raises(HTTPException) as exc:
        main.set_detection_config(main.DwellConfigUpdate(dwell_sec=0.5, confidence_threshold=value))
    assert exc.value.status_code == 400
    assert main.detector.confidence_threshold == 0.45
    assert main.command_bus.dwell_sec == 1.5


def test_detection_update_requires_a_setting():
    with pytest.raises(HTTPException) as exc:
        main.set_detection_config(main.DwellConfigUpdate())
    assert exc.value.status_code == 400
