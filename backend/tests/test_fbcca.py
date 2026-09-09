import numpy as np

import app.signal.fbcca as fbcca_module
from app.signal.fbcca import detect, score_frequencies

CANDIDATES = {"calm": 7.5, "happy": 60 / 7, "energetic": 10.0, "sad": 12.0}


def _sine(freq_hz: float, fs: float, duration_sec: float, n_channels: int = 4, noise: float = 0.1):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = np.sin(2 * np.pi * freq_hz * t)
    rng = np.random.default_rng(0)
    return np.tile(sig[:, None], (1, n_channels)) + rng.normal(0, noise, (len(t), n_channels))


def test_fbcca_detect_picks_attended_frequency():
    fs = 250.0
    for label, freq in CANDIDATES.items():
        window = _sine(freq, fs, 2.0)
        detected, confidence = detect(window, fs, CANDIDATES)
        assert detected == label, f"expected {label} ({freq}Hz), got {detected}"
        assert confidence > 0.3


def test_detect_returns_none_for_empty_candidate_set():
    fs = 250.0
    window = _sine(10.0, fs, 2.0)
    label, confidence = detect(window, fs, {})
    assert label is None
    assert confidence == 0.0


class _RaisingCCA:
    """See test_cca.py's _RaisingCCA -- forces the per-subband except branch
    deterministically rather than relying on sklearn's numerical behavior."""

    def __init__(self, n_components: int = 1):
        self.n_components = n_components

    def fit_transform(self, x, y):
        raise ValueError("boom")


def test_score_frequencies_handles_cca_failure_gracefully(monkeypatch):
    fs = 250.0
    window = _sine(10.0, fs, 2.0)
    monkeypatch.setattr(fbcca_module, "CCA", _RaisingCCA)
    scores = score_frequencies(window, fs, CANDIDATES)
    assert all(score == 0.0 for score in scores.values())
