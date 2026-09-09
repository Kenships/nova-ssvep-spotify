"""Optional detector upgrade: Filter-Bank CCA (Chen et al. 2015).

Same no-training-data property as cca.py, but splits the window into
sub-bands (fundamental, 2nd harmonic range, 3rd...) and combines each
sub-band's canonical correlation with the standard weighting that favours
the lower, stronger-SNR sub-bands. Reuses cca.py's reference-signal and CCA
machinery and filters.py's bandpass — this is a scoring strategy on top of
existing pieces, not a new signal-processing stack.

~n_subbands x more CCA calls than plain cca.py per window. Only worth
switching to once ANT Neuro's extra channels/SNR give the bank something
real to separate — on noisy/short setups it can underperform plain CCA.
"""
import numpy as np
from sklearn.cross_decomposition import CCA

from .cca import _reference_signals
from .filters import bandpass


def _subband_weight(m: int, a: float = 1.25, b: float = 0.25) -> float:
    return m ** (-a) + b


def score_frequencies(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    n_harmonics: int = 2,
    n_subbands: int = 3,
    high_hz: float = 45.0,
) -> dict[str, float]:
    """window: (n_samples, n_channels), already bandpass+notch filtered.

    Returns each candidate's weighted sum of squared sub-band correlations,
    normalized to [0, 1] by the max achievable weight sum so it's comparable
    to cca.py's confidence scale.
    """
    n_samples = window.shape[0]
    n_components = 1  # first canonical pair is what SSVEP-CCA uses
    weight_sum = sum(_subband_weight(m) for m in range(1, n_subbands + 1))

    scores: dict[str, float] = {}
    for label, f0 in candidate_freqs.items():
        ref = _reference_signals(f0, n_samples, fs, n_harmonics)
        total = 0.0
        for m in range(1, n_subbands + 1):
            low_hz = max(f0 * m - 2.0, 1.0)
            try:
                sub = bandpass(window, fs, low_hz, high_hz)
                cca = CCA(n_components=n_components)
                x_c, y_c = cca.fit_transform(sub, ref)
                rho = np.corrcoef(x_c[:, 0], y_c[:, 0])[0, 1]
            except Exception:
                rho = 0.0
            total += _subband_weight(m) * np.nan_to_num(rho) ** 2
        scores[label] = float(total / weight_sum)
    return scores


def detect(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    n_harmonics: int = 2,
    n_subbands: int = 3,
) -> tuple[str | None, float]:
    """Returns (best_label_or_None, confidence in [0, 1])."""
    scores = score_frequencies(window, fs, candidate_freqs, n_harmonics, n_subbands)
    if not scores:
        return None, 0.0
    best_label = max(scores, key=scores.get)
    confidence = max(0.0, min(1.0, scores[best_label]))
    return best_label, confidence
