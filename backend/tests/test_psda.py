import numpy as np

from app.signal.psda import detect, score_frequencies

CANDIDATES = {"calm": 7.5, "happy": 60 / 7, "energetic": 10.0, "sad": 12.0}


def _sine(freq_hz: float, fs: float, duration_sec: float, n_channels: int = 4, noise: float = 0.05):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = np.sin(2 * np.pi * freq_hz * t)
    rng = np.random.default_rng(0)
    return np.tile(sig[:, None], (1, n_channels)) + rng.normal(0, noise, (len(t), n_channels))


def test_detect_picks_attended_frequency():
    fs = 250.0
    for label, freq in CANDIDATES.items():
        window = _sine(freq, fs, 2.0)
        detected, confidence = detect(window, fs, CANDIDATES)
        assert detected == label, f"expected {label} ({freq}Hz), got {detected}"
        assert confidence > 0.25


def test_score_frequencies_favors_matching_target():
    fs = 250.0
    window = _sine(CANDIDATES["energetic"], fs, 2.0)
    scores = score_frequencies(window, fs, CANDIDATES)
    assert scores["energetic"] == max(scores.values())


def test_detect_handles_pure_noise_without_crashing():
    fs = 250.0
    rng = np.random.default_rng(1)
    window = rng.normal(0, 1.0, (int(fs * 2.0), 4))
    label, confidence = detect(window, fs, CANDIDATES)
    assert confidence >= 0.0
