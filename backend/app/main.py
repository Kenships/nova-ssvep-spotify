"""FastAPI app: mounts REST (config, calibration, Spotify OAuth callback)
and the real-time command WebSocket. Runs the detection loop as a background
asyncio task that reads from LSLIngest, feeds detector.Detector, and pushes
fired commands through command_bus.CommandBus to the frontend via ws_server.

Run with: uvicorn app.main:app --reload --port 8000
Point LSL_STREAM_NAME at the simulator's stream ("MockEEG", default) for
dev/demo, or the real ant-neuro eego stream name for the one hardware
session -- that's the only thing that needs to change (see config.py).
"""
from __future__ import annotations

import asyncio
import logging
import math
from contextlib import suppress
import time

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .calibration import DEFAULT_SNR_OK_THRESHOLD, signal_to_noise_ratio
from .commands.command_bus import CommandBus, Layer
from .config import settings
from .lsl_ingest import LSLIngest, discover_streams
from .signal.detector import Detector
from .spotify.mood_map import frequency_map, load_moods, playlist_uri_for
from .spotify.spotify_client import spotify_client
from .ws_server import manager, websocket_endpoint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SSVEP Spotify Player")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any real deployment; fine for local demo
    allow_methods=["*"],
    allow_headers=["*"],
)

ingest = LSLIngest(
    stream_name=settings.lsl_stream_name,
    resolve_timeout_sec=settings.lsl_resolve_timeout_sec,
    window_sec=settings.window_sec,
    preferred_channel_labels=settings.occipital_channel_labels,
    fallback_channel_indices=settings.occipital_channel_indices,
)
detector = Detector(
    backend=settings.detector_backend,
    bandpass_low_hz=settings.bandpass_low_hz,
    bandpass_high_hz=settings.bandpass_high_hz,
    mains_notch_hz=settings.mains_notch_hz,
    confidence_threshold=settings.confidence_threshold,
)
command_bus = CommandBus(dwell_sec=settings.dwell_sec, refractory_sec=settings.refractory_sec)

_detection_task: asyncio.Task | None = None
_control_lock = asyncio.Lock()
_ingest_lock = asyncio.Lock()
_calibration_active = False
_current_mood: str | None = None
_control_revision = 0
_switching_stream = False


def player_state() -> dict:
    return {
        "type": "state", "layer": command_bus.layer.value,
        "currentMoodId": _current_mood, "calibrationActive": _calibration_active,
    }


class CalibrationRequest(BaseModel):
    active: bool


@app.post("/api/calibration/session")
async def set_calibration_session(req: CalibrationRequest):
    global _calibration_active, _control_revision
    async with _control_lock:
        _calibration_active = req.active
        _control_revision += 1
        command_bus.enter_refractory()
        # Drain the calibration stimulus from the detector window before resuming.
        if not req.active:
            command_bus.enter_refractory(duration_sec=max(settings.window_sec, command_bus.refractory_sec))
        state = player_state()
        await manager.broadcast(state)
        return state


@app.get("/api/config/moods")
def get_moods():
    return {"moods": load_moods()}


def _lsl_status() -> dict:
    return {
        "stream_name": ingest.stream_name,
        "connected": ingest.is_connected(),
        "fs": ingest.fs,
        "channel_count": len(ingest.channel_labels),
        "channel_labels": ingest.channel_labels,
        "occipital_indices": ingest.occipital_indices,
        "hostname": ingest.hostname,
    }


@app.get("/api/lsl/status")
def get_lsl_status():
    """What the backend is actually connected to right now -- the frontend's
    input-source picker polls this to confirm a switch really took effect,
    not just that the request was accepted."""
    return _lsl_status()


@app.get("/api/lsl/discover")
def get_lsl_discover(timeout: float = 3.0):
    """Every LSL stream currently visible on the network, so the picker can
    offer a list instead of requiring the exact stream name up front."""
    return {"streams": discover_streams(wait_time=timeout)}


class LSLSwitchRequest(BaseModel):
    stream_name: str


@app.post("/api/lsl/switch")
async def post_lsl_switch(req: LSLSwitchRequest):
    global _switching_stream, _control_revision
    async with _ingest_lock:
        _switching_stream = True
        _control_revision += 1
        command_bus.reset_dwell()
        try:
            await asyncio.to_thread(ingest.switch_stream, req.stream_name)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        finally:
            command_bus.reset_dwell()
            _switching_stream = False
    return _lsl_status()


class DwellConfigUpdate(BaseModel):
    dwell_sec: float | None = None
    confidence_threshold: float | None = None
    refractory_sec: float | None = None


@app.get("/api/config/detection")
def get_detection_config():
    """Live detector settings, including the active instance's confidence gate."""
    return {
        "dwell_sec": command_bus.dwell_sec, "window_sec": settings.window_sec,
        "confidence_threshold": detector.confidence_threshold, "detector_backend": detector.backend,
        "refractory_sec": command_bus.refractory_sec,
    }


@app.post("/api/config/detection")
def set_detection_config(req: DwellConfigUpdate):
    global _control_revision
    if req.dwell_sec is None and req.confidence_threshold is None and req.refractory_sec is None:
        raise HTTPException(status_code=400, detail="Provide dwell_sec, confidence_threshold, or refractory_sec")
    if req.dwell_sec is not None and (not math.isfinite(req.dwell_sec) or req.dwell_sec <= 0):
        raise HTTPException(status_code=400, detail="dwell_sec must be positive and finite")
    if req.confidence_threshold is not None and (
        not math.isfinite(req.confidence_threshold) or not 0 < req.confidence_threshold <= 1
    ):
        raise HTTPException(status_code=400, detail="confidence_threshold must be greater than 0 and at most 1")
    if req.refractory_sec is not None and (not math.isfinite(req.refractory_sec) or req.refractory_sec <= 0):
        raise HTTPException(status_code=400, detail="refractory_sec must be positive and finite")
    if req.dwell_sec is not None:
        command_bus.dwell_sec = req.dwell_sec
    if req.confidence_threshold is not None:
        detector.confidence_threshold = req.confidence_threshold
    if req.refractory_sec is not None:
        command_bus.refractory_sec = req.refractory_sec
    command_bus.reset_dwell()
    _control_revision += 1
    return get_detection_config()


@app.get("/api/calibration/snr")
def get_calibration_snr(label: str):
    """Live signal-to-noise ratio for one mood target, computed from
    whatever's currently in the ingest ring buffer -- the calibration screen
    polls this while cueing each target in turn so the user sees real signal
    quality feedback instead of just a countdown.
    """
    freqs = frequency_map(load_moods())
    if label not in freqs:
        raise HTTPException(
            status_code=400, detail=f"'{label}' is not a valid mood id; expected one of {sorted(freqs)}"
        )
    if not ingest.is_connected():
        return {"label": label, "ready": False, "snr": 0.0, "ok": False}
    window, fs = ingest.get_window()
    if fs <= 0 or len(window) < int(fs * settings.window_sec):
        return {"label": label, "ready": False, "snr": 0.0, "ok": False}
    snr = signal_to_noise_ratio(
        window, fs, freqs[label], settings.bandpass_low_hz, settings.bandpass_high_hz, settings.mains_notch_hz
    )
    return {"label": label, "ready": True, "snr": snr, "ok": snr >= DEFAULT_SNR_OK_THRESHOLD}


@app.get("/api/now-playing")
def get_now_playing():
    return spotify_client.now_playing() or {}


@app.get("/api/spotify/status")
def spotify_status():
    return {"authenticated": spotify_client.is_authenticated()}


@app.get("/api/spotify/login")
def spotify_login():
    """Visit this URL in a browser to authorize the app (one-time, then the
    refresh token is cached in backend/.spotify_token_cache)."""
    return RedirectResponse(spotify_client.get_authorize_url())


@app.get("/api/spotify/callback")
def spotify_callback(code: str | None = None, error: str | None = None):
    """Spotify redirects here after the user authorizes (or denies) access.
    Must exactly match SPOTIFY_REDIRECT_URI configured both here and in the
    app's dashboard settings at https://developer.spotify.com/dashboard.
    """
    if error:
        return HTMLResponse(f"<p>Spotify authorization failed: {error}</p>", status_code=400)
    if not code:
        return HTMLResponse("<p>Missing authorization code.</p>", status_code=400)
    spotify_client.complete_authorization(code)
    return HTMLResponse("<p>Spotify connected. You can close this tab.</p>")


@app.websocket("/ws/commands")
async def ws_commands(ws: WebSocket):
    await websocket_endpoint(ws, player_state)


def _current_candidate_freqs() -> dict[str, float]:
    moods = load_moods()
    if command_bus.layer == Layer.MOOD:
        return frequency_map(moods)
    return settings.transport_frequencies


def _apply_spotify_side_effect(layer: Layer, label: str) -> None:
    """Best-effort Spotify call for a fired command. Failures here (e.g. no
    Spotify credentials configured yet, which is expected for most of the
    build before OAuth is wired up) must never prevent the command itself
    from reaching the frontend -- the SSVEP pipeline and the Spotify
    integration are allowed to be independently broken during development.
    """
    moods = load_moods()
    if layer == Layer.MOOD:
        uri = playlist_uri_for(moods, label)
        if uri:
            spotify_client.play_playlist(uri)
        return

    if label == "play_pause":
        spotify_client.toggle_play_pause()
    elif label == "next":
        spotify_client.next_track()
    elif label == "previous":
        spotify_client.previous_track()


async def _handle_fired_command(
    label: str, target_layer: Layer | None = None, expected_revision: int | None = None,
) -> None:
    global _current_mood, _control_revision
    async with _control_lock:
        if _calibration_active:
            raise HTTPException(status_code=409, detail="Playback commands are paused during calibration")
        if expected_revision is not None and expected_revision != _control_revision:
            return  # This detection belongs to an earlier layer/source/session.
        layer = target_layer if target_layer is not None else command_bus.layer
        command_bus.layer = layer
        if layer == Layer.MOOD:
            _current_mood = label
            command_bus.switch_layer(Layer.TRANSPORT)
        elif label == "back_to_mood":
            command_bus.switch_layer(Layer.MOOD)
        command_bus.enter_refractory()
        _control_revision += 1

        await manager.broadcast(
            {"type": "command", "layer": layer.value, "target": label, "refractorySec": command_bus.refractory_sec}
        )
        await manager.broadcast(player_state())
        try:
            await asyncio.to_thread(_apply_spotify_side_effect, layer, label)
        except Exception:
            logger.exception("Spotify call failed for fired command %s (layer=%s)", label, layer.value)


class ManualCommandRequest(BaseModel):
    target: str


@app.post("/api/manual-command")
async def manual_command(req: ManualCommandRequest):
    """Manual targets identify their layer so delayed clicks retain their meaning."""
    mood_ids = set(frequency_map(load_moods()).keys())
    transport_ids = set(settings.transport_frequencies.keys())
    if req.target in mood_ids:
        target_layer = Layer.MOOD
    elif req.target in transport_ids:
        target_layer = Layer.TRANSPORT
    else:
        raise HTTPException(
            status_code=400,
            detail=f"'{req.target}' is not a valid mood or transport target; expected one of {sorted(mood_ids | transport_ids)}",
        )

    await _handle_fired_command(req.target, target_layer=target_layer)
    # Block the automatic detector from immediately re-firing the same
    # target right after a manual override.
    command_bus.enter_refractory(time.monotonic())
    return {"layer": command_bus.layer.value, "target": req.target}


RAW_DEBUG_WINDOW_SEC = 1.0  # how much history the debug panel's live graph redraws each tick


async def _broadcast_raw_debug_window() -> None:
    """Pushes a snapshot of the raw occipital channel data to any connected
    debug panels. Gated on has_raw_subscribers() so an idle/closed panel
    costs nothing -- this runs every detection-loop tick otherwise, and a
    full window several times a second to every client would add up.
    """
    if not manager.has_raw_subscribers():
        return
    raw_window, raw_fs = ingest.get_window(RAW_DEBUG_WINDOW_SEC)
    if len(raw_window) == 0:
        return
    await manager.broadcast_raw(
        {
            "type": "raw",
            "fs": raw_fs,
            "channelLabels": [ingest.channel_labels[i] for i in ingest.occipital_indices],
            "samples": raw_window.round(2).tolist(),
        }
    )


async def _detection_loop() -> None:
    was_connected = ingest.inlet is not None
    while True:
        await asyncio.sleep(0.25)
        # start() is idempotent; serialize it with source switches and keep
        # blocking LSL discovery off the API event loop.
        async with _ingest_lock:
            try:
                await asyncio.to_thread(ingest.start)
            except RuntimeError:
                command_bus.reset_dwell()
                continue

        if not ingest.is_connected():
            command_bus.reset_dwell()
            if was_connected:
                logger.error("EEG stream disconnected; detection paused until it reconnects.")
                await manager.broadcast({"type": "error", "message": "EEG stream disconnected"})
                was_connected = False
            continue
        if not was_connected:
            logger.info("EEG stream reconnected; resuming detection.")
            await manager.broadcast({"type": "info", "message": "EEG stream reconnected"})
            was_connected = True

        await _broadcast_raw_debug_window()

        if _calibration_active or _switching_stream:
            command_bus.reset_dwell()
            continue

        window, fs = ingest.get_window()
        if fs <= 0 or len(window) < int(fs * settings.window_sec):
            command_bus.reset_dwell()
            continue  # not enough buffered samples yet

        revision = _control_revision
        candidate_freqs = _current_candidate_freqs()
        label, confidence, scores = detector.detect_with_scores(window, fs, candidate_freqs)
        await manager.broadcast(
            {
                "type": "debug",
                "detectedLabel": label,
                "confidence": confidence,
                "scores": scores,  # every candidate's confidence, not just the winner's
                "layer": command_bus.layer.value,
            }
        )

        if _calibration_active or _switching_stream or revision != _control_revision:
            command_bus.reset_dwell()
            continue
        fired = command_bus.feed(label, now=time.monotonic())
        if fired:
            try:
                await _handle_fired_command(fired, expected_revision=revision)
            except Exception:
                logger.exception("Error handling fired command %s", fired)


@app.on_event("startup")
async def on_startup():
    global _detection_task
    _detection_task = asyncio.create_task(_detection_loop())


@app.on_event("shutdown")
async def on_shutdown():
    if _detection_task:
        _detection_task.cancel()
        with suppress(asyncio.CancelledError):
            await _detection_task
    async with _ingest_lock:
        await asyncio.to_thread(ingest.stop)
