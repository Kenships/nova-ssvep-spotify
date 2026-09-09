"""Central, env-driven configuration.

Nothing downstream of lsl_ingest.py should ever hardcode a sample rate,
channel name, or "am I running against real hardware" flag — all of that
comes from here (env-overridable) or from the LSL stream_info itself at
connect time.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"

# Load backend/.env (if present) into the process environment before any
# Settings field reads os.environ.get(...) below. A real env var set
# outside .env still wins, since load_dotenv() defaults to not overriding
# existing environment variables.
load_dotenv(BACKEND_DIR / ".env")


def _env_float_list(name: str, default: list[float]) -> list[float]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [float(x) for x in raw.split(",")]


@dataclass
class Settings:
    # --- LSL ---
    # Name of the LSL stream to connect to. Point this at the simulator's
    # stream name for dev/demo, or the real ant-neuro eego stream name for
    # the one hardware session. This is the ONLY place that distinction
    # should ever live.
    lsl_stream_name: str = os.environ.get("LSL_STREAM_NAME", "MockEEG")
    lsl_resolve_timeout_sec: float = float(os.environ.get("LSL_RESOLVE_TIMEOUT_SEC", "5.0"))

    # Occipital channel labels to prefer, in order of preference. If the
    # connected stream doesn't expose these labels (e.g. raw electrode
    # indices instead of 10-20 names), fall back to occipital_channel_indices.
    occipital_channel_labels: list[str] = field(
        default_factory=lambda: os.environ.get(
            "OCCIPITAL_CHANNEL_LABELS", "Oz,O1,O2,POz"
        ).split(",")
    )
    # Manual index fallback (0-based), used only if label matching fails.
    # Must be set per-montage during hardware bring-up if labels aren't 10-20 names.
    occipital_channel_indices: list[int] = field(
        default_factory=lambda: [
            int(x) for x in os.environ.get("OCCIPITAL_CHANNEL_INDICES", "").split(",") if x
        ]
    )

    # --- Signal processing ---
    bandpass_low_hz: float = float(os.environ.get("BANDPASS_LOW_HZ", "5.0"))
    bandpass_high_hz: float = float(os.environ.get("BANDPASS_HIGH_HZ", "40.0"))
    mains_notch_hz: float = float(os.environ.get("MAINS_NOTCH_HZ", "60.0"))  # 60Hz in Canada
    window_sec: float = float(os.environ.get("WINDOW_SEC", "2.0"))
    detector_backend: str = os.environ.get("DETECTOR_BACKEND", "psda")  # "psda" | "cca" | "fbcca"
    confidence_threshold: float = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.35"))

    # --- Command bus ---
    dwell_sec: float = float(os.environ.get("DWELL_SEC", "0.75"))
    refractory_sec: float = float(os.environ.get("REFRACTORY_SEC", "1.0"))

    # --- SSVEP target frequencies (Hz) ---
    # Collision-free set for a 60Hz display: avoid pairing a frequency with
    # its 2nd harmonic on screen at the same time (6&12, 7.5&15 collide).
    mood_frequencies: dict[str, float] = field(
        default_factory=lambda: {
            "calm": 7.5,
            "happy": 60 / 7,  # 8.571428... Hz
            "energetic": 10.0,
            "sad": 12.0,
        }
    )
    transport_frequencies: dict[str, float] = field(
        default_factory=lambda: {
            "play_pause": 7.5,
            "next": 60 / 7,
            "previous": 10.0,
            "back_to_mood": 12.0,
        }
    )

    # --- Spotify ---
    spotify_client_id: str = os.environ.get("SPOTIFY_CLIENT_ID", "")
    spotify_client_secret: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    spotify_redirect_uri: str = os.environ.get(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/api/spotify/callback"
    )
    spotify_device_name: str = os.environ.get("SPOTIFY_DEVICE_NAME", "")  # e.g. desktop app name
    mood_playlists_path: Path = CONFIG_DIR / "mood_playlists.json"

    def load_mood_playlists(self) -> dict:
        with open(self.mood_playlists_path, encoding="utf-8") as f:
            return json.load(f)


settings = Settings()
