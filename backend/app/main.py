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
import time

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .commands.command_bus import CommandBus, Layer
from .config import settings
from .lsl_ingest import LSLIngest
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


@app.get("/api/config/moods")
def get_moods():
    return {"moods": load_moods()}


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
    await websocket_endpoint(ws)


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


async def _handle_fired_command(label: str) -> None:
    layer = command_bus.layer

    # Broadcast first: the frontend must see the detected command regardless
    # of whether the downstream Spotify call succeeds.
    await manager.broadcast({"type": "command", "layer": layer.value, "target": label})

    if layer == Layer.MOOD:
        command_bus.switch_layer(Layer.TRANSPORT)
    elif label == "back_to_mood":
        command_bus.switch_layer(Layer.MOOD)

    try:
        _apply_spotify_side_effect(layer, label)
    except Exception:
        logger.exception("Spotify call failed for fired command %s (layer=%s)", label, layer.value)


class ManualCommandRequest(BaseModel):
    target: str


@app.post("/api/manual-command")
async def manual_command(req: ManualCommandRequest):
    """Lets the frontend fire a command by direct click/keyboard, bypassing
    SSVEP detection entirely. Tiles must always be manually operable --
    for testing without hardware, for a demo when signal quality is poor,
    and as an accessibility fallback for whoever hasn't lost all voluntary
    movement yet. Reuses _handle_fired_command so a manual click produces
    exactly the same broadcast + layer-switch + Spotify side effect as a
    real detection would.

    Validates against BOTH mood and transport target sets (mood/transport
    ids are disjoint, so this is unambiguous) rather than only whichever
    layer command_bus currently thinks it's in. The automatic detector can
    flip command_bus.layer between when the user sees a tile and when their
    click actually lands on the backend (confirmed happening in practice --
    the confidence threshold sits close enough to the noise floor that idle
    noise alone triggers real layer switches), so a manual click must be
    layer-agnostic: fire whatever the user actually clicked, and bring
    command_bus's layer in line with that rather than reject the click for
    having "the wrong layer" from the user's point of view.
    """
    mood_ids = set(frequency_map(load_moods()).keys())
    transport_ids = set(settings.transport_frequencies.keys())
    if req.target in mood_ids:
        command_bus.layer = Layer.MOOD
    elif req.target in transport_ids:
        command_bus.layer = Layer.TRANSPORT
    else:
        raise HTTPException(
            status_code=400,
            detail=f"'{req.target}' is not a valid mood or transport target; expected one of {sorted(mood_ids | transport_ids)}",
        )

    await _handle_fired_command(req.target)
    # Block the automatic detector from immediately re-firing the same
    # target right after a manual override.
    command_bus.enter_refractory(time.monotonic())
    return {"layer": command_bus.layer.value, "target": req.target}


async def _detection_loop() -> None:
    ingest.start()
    while True:
        await asyncio.sleep(0.25)
        window, fs = ingest.get_window()
        if fs <= 0 or len(window) < int(fs * settings.window_sec):
            continue  # not enough buffered samples yet

        candidate_freqs = _current_candidate_freqs()
        label, confidence = detector.detect(window, fs, candidate_freqs)
        await manager.broadcast(
            {"type": "debug", "detectedLabel": label, "confidence": confidence, "layer": command_bus.layer.value}
        )

        fired = command_bus.feed(label, now=time.monotonic())
        if fired:
            try:
                await _handle_fired_command(fired)
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
    ingest.stop()
