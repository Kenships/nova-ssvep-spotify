"""Phase 1 detector: Power Spectral Density Analysis (FFT peak-picking).

For each candidate frequency, score = power at the fundamental bin + power
at the 1st-harmonic bin, averaged across occipital channels. Simple, fast,
no training data needed — this is the "make it work at all" detector,
built before the CCA upgrade.
"""
import numpy as np


def _bin_power(freqs: np.ndarray, power: np.ndarray, target_hz: float, tol_hz: float) -> float:
    mask = np.abs(freqs - target_hz) <= tol_hz
    if not np.any(mask):
        return 0.0
    return float(np.max(power[mask]))


def score_frequencies(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    bin_tol_hz: float = 0.3,
) -> dict[str, float]:
    """window: (n_samples, n_channels), already bandpass+notch filtered.

    Returns a raw (unnormalized) power score per candidate label.
    """
    n_samples = window.shape[0]
    # Hann window + zero-pad for finer frequency resolution.
    hann = np.hanning(n_samples)[:, None]
    padded_len = max(int(fs * 8), n_samples)  # zero-pad toward ~0.125Hz resolution
    spectrum = np.fft.rfft(window * hann, n=padded_len, axis=0)
    power = np.mean(np.abs(spectrum) ** 2, axis=1)  # average across channels
    freqs = np.fft.rfftfreq(padded_len, d=1.0 / fs)

    scores: dict[str, float] = {}
    for label, f0 in candidate_freqs.items():
        fundamental = _bin_power(freqs, power, f0, bin_tol_hz)
        harmonic = _bin_power(freqs, power, 2 * f0, bin_tol_hz)
        scores[label] = fundamental + 0.5 * harmonic
    return scores


def detect(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    bin_tol_hz: float = 0.3,
) -> tuple[str | None, float]:
    """Returns (best_label_or_None, confidence in [0, 1]).

    Confidence is the winning score's share of total score across candidates
    — a crude but workable normalization that goes to ~1/N when nothing
    stands out (i.e. the user isn't attending anything in particular).
    """
    scores = score_frequencies(window, fs, candidate_freqs, bin_tol_hz)
    total = sum(scores.values())
    if total <= 0:
        return None, 0.0
    best_label = max(scores, key=scores.get)
    confidence = scores[best_label] / total
    return best_label, confidence
