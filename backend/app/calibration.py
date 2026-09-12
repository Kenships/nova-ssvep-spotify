"""Per-session calibration: a ~30s guided sequence that cues the user
through each target frequency in turn and computes per-target SNR, to
sanity-check the setup before a live segment. This is a session check, not
classifier training — CCA/PSDA need no training data.

Runs identically against simulated or real data, so it should be exercised
often before the one real-hardware session.
"""
from __future__ import annotations

import numpy as np

from .signal.filters import preprocess


def signal_to_noise_ratio(
    window: np.ndarray,
    fs: float,
    target_hz: float,
    bandpass_low_hz: float,
    bandpass_high_hz: float,
    mains_notch_hz: float,
    noise_band_hz: float = 2.0,
    bin_tol_hz: float = 0.3,
) -> float:
    """SNR = power at target frequency / mean power in a nearby noise band
    (target +/- noise_band_hz, excluding the target bin itself).
    """
    filtered = preprocess(window, fs, bandpass_low_hz, bandpass_high_hz, mains_notch_hz)
    n_samples = filtered.shape[0]
    hann = np.hanning(n_samples)[:, None]
    padded_len = max(int(fs * 8), n_samples)
    spectrum = np.fft.rfft(filtered * hann, n=padded_len, axis=0)
    power = np.mean(np.abs(spectrum) ** 2, axis=1)
    freqs = np.fft.rfftfreq(padded_len, d=1.0 / fs)

    target_mask = np.abs(freqs - target_hz) <= bin_tol_hz
    noise_mask = (np.abs(freqs - target_hz) <= noise_band_hz) & ~target_mask

    target_power = float(np.max(power[target_mask])) if np.any(target_mask) else 0.0
    noise_power = float(np.mean(power[noise_mask])) if np.any(noise_mask) else 1e-12

    return target_power / max(noise_power, 1e-12)


DEFAULT_SNR_OK_THRESHOLD = 3.0


def run_calibration_check(
    per_target_windows: dict[str, np.ndarray],
    fs: float,
    target_freqs: dict[str, float],
    bandpass_low_hz: float,
    bandpass_high_hz: float,
    mains_notch_hz: float,
    snr_threshold: float = DEFAULT_SNR_OK_THRESHOLD,
) -> dict[str, dict]:
    """per_target_windows: label -> EEG window captured while the user was
    cued to look at that target. Returns label -> {snr, ok} report.
    """
    report = {}
    for label, window in per_target_windows.items():
        snr = signal_to_noise_ratio(
            window, fs, target_freqs[label], bandpass_low_hz, bandpass_high_hz, mains_notch_hz
        )
        report[label] = {"snr": snr, "ok": snr >= snr_threshold}
    return report
