"""Loads backend/config/mood_playlists.json — the single source of truth
for mood -> curated playlist mapping, also served to the frontend via
GET /api/config/moods so it's never duplicated in two places.
"""
from __future__ import annotations

from functools import lru_cache

from ..config import settings


@lru_cache(maxsize=1)
def load_moods() -> list[dict]:
    """Cached: this file is static app config (edited by hand, not at
    runtime), but it's read on every detection-loop tick and polled by the
    calibration screen every second -- re-parsing JSON from disk that often
    for data that never changes mid-session is pure waste. Restart the
    backend to pick up an edit."""
    data = settings.load_mood_playlists()
    return data["moods"]


def frequency_map(moods: list[dict]) -> dict[str, float]:
    """label(id) -> freqHz, for feeding the detector's candidate set."""
    return {m["id"]: m["freqHz"] for m in moods}


def playlist_uri_for(moods: list[dict], mood_id: str) -> str | None:
    for m in moods:
        if m["id"] == mood_id:
            return m["spotify_playlist_uri"]
    return None
