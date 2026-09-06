"""Thin spotipy wrapper: OAuth (Authorization Code flow, cached refresh
token) + Spotify Connect transport calls against an already-open, logged-in
Premium client (e.g. the desktop app) on the demo machine.

Deliberately NOT using the Web Playback SDK — see plan doc for rationale
(DRM/EME + autoplay-unlock + token-lifecycle complexity that buys nothing
for a demo where Spotify is already open on some device).
"""
from __future__ import annotations

import logging

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from ..config import settings

logger = logging.getLogger(__name__)

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"


class SpotifyClient:
    """`open_browser=False` is load-bearing: spotipy's default OAuth flow
    tries to spin up its own temporary local HTTP server bound to the
    redirect URI's host:port to catch the authorization code, which
    collides with our own FastAPI server already listening on that same
    port. Instead, /api/spotify/login and /api/spotify/callback in main.py
    drive the flow explicitly against this same auth_manager instance.
    """

    def __init__(self):
        self._auth_manager: SpotifyOAuth | None = None
        self._client: spotipy.Spotify | None = None

    @property
    def auth_manager(self) -> SpotifyOAuth:
        # Built lazily, not at import time: constructing SpotifyOAuth raises
        # immediately if client_id/client_secret aren't set yet, which must
        # not prevent the rest of the backend (SSVEP pipeline against the
        # simulator, with no Spotify credentials configured at all) from
        # starting up.
        if self._auth_manager is None:
            self._auth_manager = SpotifyOAuth(
                client_id=settings.spotify_client_id,
                client_secret=settings.spotify_client_secret,
                redirect_uri=settings.spotify_redirect_uri,
                scope=SCOPES,
                cache_path=".spotify_token_cache",
                open_browser=False,
            )
        return self._auth_manager

    def is_authenticated(self) -> bool:
        if not settings.spotify_client_id or not settings.spotify_client_secret:
            return False
        return self.auth_manager.validate_token(self.auth_manager.get_cached_token()) is not None

    def get_authorize_url(self) -> str:
        return self.auth_manager.get_authorize_url()

    def complete_authorization(self, code: str) -> None:
        self.auth_manager.get_access_token(code=code, as_dict=False, check_cache=False)

    @property
    def client(self) -> spotipy.Spotify:
        if self._client is None:
            self._client = spotipy.Spotify(auth_manager=self.auth_manager)
        return self._client

    def _resolve_device_id(self) -> str | None:
        devices = self.client.devices().get("devices", [])
        if not devices:
            logger.warning("No Spotify Connect devices found. Is Spotify open and logged in?")
            return None
        if settings.spotify_device_name:
            for d in devices:
                if d["name"] == settings.spotify_device_name:
                    return d["id"]
            logger.warning(
                "Configured SPOTIFY_DEVICE_NAME '%s' not found among devices %s; using first available.",
                settings.spotify_device_name, [d["name"] for d in devices],
            )
        return devices[0]["id"]

    def play_playlist(self, playlist_uri: str) -> None:
        device_id = self._resolve_device_id()
        self.client.start_playback(device_id=device_id, context_uri=playlist_uri)

    def pause(self) -> None:
        self.client.pause_playback()

    def resume(self) -> None:
        self.client.start_playback()

    def toggle_play_pause(self) -> None:
        playback = self.client.current_playback()
        if playback and playback.get("is_playing"):
            self.pause()
        else:
            self.resume()

    def next_track(self) -> None:
        self.client.next_track()

    def previous_track(self) -> None:
        self.client.previous_track()

    def set_volume(self, percent: int) -> None:
        self.client.volume(max(0, min(100, percent)))

    def now_playing(self) -> dict | None:
        playback = self.client.current_playback()
        if not playback or not playback.get("item"):
            return None
        item = playback["item"]
        return {
            "track": item.get("name"),
            "artist": ", ".join(a["name"] for a in item.get("artists", [])),
            "album_art_url": (item.get("album", {}).get("images") or [{}])[0].get("url"),
            "is_playing": playback.get("is_playing", False),
            "progress_ms": playback.get("progress_ms", 0),
            "duration_ms": item.get("duration_ms", 0),
        }


spotify_client = SpotifyClient()
