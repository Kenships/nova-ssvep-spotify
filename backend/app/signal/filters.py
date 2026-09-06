"""Bandpass + mains-notch filtering for raw EEG windows.

Operates on arrays shaped (n_samples, n_channels). Filters are recomputed
per-call from sample rate rather than cached globally, since the real
ant-neuro stream's nominal_srate() is only known at connect time and must
never be hardcoded (see lsl_ingest.py).
"""
import numpy as np
from scipy.signal import butter, iirnotch, sosfiltfilt, tf2sos


def bandpass(data: np.ndarray, fs: float, low_hz: float, high_hz: float, order: int = 4) -> np.ndarray:
    nyq = fs / 2.0
    low = max(low_hz / nyq, 1e-4)
    high = min(high_hz / nyq, 0.999)
    sos = butter(order, [low, high], btype="bandpass", output="sos")
    return sosfiltfilt(sos, data, axis=0)


def notch(data: np.ndarray, fs: float, freq_hz: float, quality: float = 30.0) -> np.ndarray:
    if freq_hz <= 0 or freq_hz >= fs / 2.0:
        return data
    b, a = iirnotch(freq_hz, quality, fs)
    sos = tf2sos(b, a)
    return sosfiltfilt(sos, data, axis=0)


def preprocess(
    data: np.ndarray,
    fs: float,
    low_hz: float,
    high_hz: float,
    mains_hz: float,
) -> np.ndarray:
    """Bandpass then mains notch. `data` is (n_samples, n_channels)."""
    out = bandpass(data, fs, low_hz, high_hz)
    out = notch(out, fs, mains_hz)
    return out
