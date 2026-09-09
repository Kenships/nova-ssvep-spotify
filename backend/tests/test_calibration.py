import numpy as np

from app.calibration import run_calibration_check, signal_to_noise_ratio

CANDIDATES = {"calm": 7.5, "happy": 60 / 7, "energetic": 10.0, "sad": 12.0}


def _sine(freq_hz: float, fs: float, duration_sec: float, n_channels: int = 4, amp: float = 1.0, noise: float = 0.02):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = amp * np.sin(2 * np.pi * freq_hz * t)
    rng = np.random.default_rng(0)
    return np.tile(sig[:, None], (1, n_channels)) + rng.normal(0, noise, (len(t), n_channels))


def test_snr_high_for_clean_target_signal():
    fs = 250.0
    window = _sine(CANDIDATES["energetic"], fs, 2.0)
    snr = signal_to_noise_ratio(window, fs, CANDIDATES["energetic"], 5.0, 40.0, 60.0)
    assert snr > 3.0


def test_snr_low_for_pure_noise():
    fs = 250.0
    rng = np.random.default_rng(1)
    window = rng.normal(0, 1.0, (int(fs * 2.0), 4))
    snr = signal_to_noise_ratio(window, fs, CANDIDATES["energetic"], 5.0, 40.0, 60.0)
    assert snr < 3.0


def test_run_calibration_check_reports_ok_and_not_ok_per_target():
    fs = 250.0
    per_target_windows = {
        "energetic": _sine(CANDIDATES["energetic"], fs, 2.0),
        "sad": _sine(2.0, fs, 2.0),  # attending nothing close to "sad"'s 12Hz target
    }
    report = run_calibration_check(
        per_target_windows, fs, CANDIDATES, bandpass_low_hz=5.0, bandpass_high_hz=40.0, mains_notch_hz=60.0
    )
    assert report["energetic"]["ok"] is True
    assert report["sad"]["ok"] is False
    assert set(report.keys()) == {"energetic", "sad"}
