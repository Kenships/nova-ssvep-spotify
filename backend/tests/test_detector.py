import numpy as np
import pytest

from app.signal.detector import Detector

CANDIDATES = {"calm": 7.5, "happy": 60 / 7, "energetic": 10.0, "sad": 12.0}


def _sine(freq_hz: float, fs: float, duration_sec: float, n_channels: int = 4, noise: float = 0.05):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = np.sin(2 * np.pi * freq_hz * t)
    rng = np.random.default_rng(0)
    return np.tile(sig[:, None], (1, n_channels)) + rng.normal(0, noise, (len(t), n_channels))


@pytest.mark.parametrize("backend", ["psda", "cca", "fbcca"])
def test_detect_picks_attended_frequency_for_each_backend(backend):
    fs = 250.0
    detector = Detector(
        backend=backend,
        bandpass_low_hz=5.0,
        bandpass_high_hz=40.0,
        mains_notch_hz=60.0,
        confidence_threshold=0.35,
    )
    window = _sine(CANDIDATES["energetic"], fs, 2.0)
    label, confidence = detector.detect(window, fs, CANDIDATES)
    assert label == "energetic"
    assert confidence >= 0.35


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        Detector(
            backend="not-a-real-backend",
            bandpass_low_hz=5.0,
            bandpass_high_hz=40.0,
            mains_notch_hz=60.0,
            confidence_threshold=0.35,
        )


def test_low_confidence_returns_none_label():
    fs = 250.0
    detector = Detector(
        backend="psda",
        bandpass_low_hz=5.0,
        bandpass_high_hz=40.0,
        mains_notch_hz=60.0,
        # Impossibly high bar: even a clean, perfectly matched signal can't
        # clear it, so the gating branch (confidence < threshold -> None)
        # is exercised deterministically rather than relying on noise.
        confidence_threshold=1.5,
    )
    window = _sine(CANDIDATES["energetic"], fs, 2.0)
    label, confidence = detector.detect(window, fs, CANDIDATES)
    assert label is None
    assert confidence < 1.5
