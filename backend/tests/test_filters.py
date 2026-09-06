import numpy as np

from app.signal.filters import bandpass, notch, preprocess


def _sine(freq_hz: float, fs: float, duration_sec: float, n_channels: int = 2, amp: float = 1.0):
    t = np.arange(int(fs * duration_sec)) / fs
    sig = amp * np.sin(2 * np.pi * freq_hz * t)
    return np.tile(sig[:, None], (1, n_channels))


def test_bandpass_attenuates_out_of_band_signal():
    fs = 250.0
    low_hz, high_hz = 5.0, 40.0
    in_band = _sine(10.0, fs, 4.0)
    out_of_band = _sine(1.0, fs, 4.0)  # below passband

    filtered_in_band = bandpass(in_band, fs, low_hz, high_hz)
    filtered_out_of_band = bandpass(out_of_band, fs, low_hz, high_hz)

    assert np.std(filtered_in_band) > 5 * np.std(filtered_out_of_band)


def test_notch_attenuates_mains_frequency():
    fs = 250.0
    mains = _sine(60.0, fs, 4.0)
    filtered = notch(mains, fs, 60.0)
    assert np.std(filtered) < 0.5 * np.std(mains)


def test_preprocess_runs_end_to_end():
    fs = 250.0
    signal = _sine(10.0, fs, 4.0) + _sine(60.0, fs, 4.0, amp=0.3)
    out = preprocess(signal, fs, 5.0, 40.0, 60.0)
    assert out.shape == signal.shape
    assert np.all(np.isfinite(out))
