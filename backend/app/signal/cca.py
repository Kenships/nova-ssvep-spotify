"""Phase 2 detector: Canonical Correlation Analysis against sine/cosine
reference banks (fundamental + 1st harmonic) per candidate frequency.

Standard, robust, unsupervised SSVEP detection method — needs no per-user
training data, which matters given only one real-hardware session exists
to validate against. Drop-in replacement for psda.detect() behind
detector.py's common interface.
"""
import numpy as np
from sklearn.cross_decomposition import CCA


def _reference_signals(f0: float, n_samples: float, fs: float, n_harmonics: int = 2) -> np.ndarray:
    t = np.arange(n_samples) / fs
    cols = []
    for h in range(1, n_harmonics + 1):
        cols.append(np.sin(2 * np.pi * h * f0 * t))
        cols.append(np.cos(2 * np.pi * h * f0 * t))
    return np.stack(cols, axis=1)  # (n_samples, 2*n_harmonics)


def score_frequencies(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    n_harmonics: int = 2,
) -> dict[str, float]:
    """window: (n_samples, n_channels), already bandpass+notch filtered.

    Returns the max canonical correlation coefficient per candidate label.
    """
    n_samples = window.shape[0]
    scores: dict[str, float] = {}
    n_components = 1  # first canonical pair is what SSVEP-CCA uses
    for label, f0 in candidate_freqs.items():
        ref = _reference_signals(f0, n_samples, fs, n_harmonics)
        try:
            cca = CCA(n_components=n_components)
            x_c, y_c = cca.fit_transform(window, ref)
            corr = np.corrcoef(x_c[:, 0], y_c[:, 0])[0, 1]
        except Exception:
            corr = 0.0
        scores[label] = float(np.nan_to_num(corr))
    return scores


def detect(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    n_harmonics: int = 2,
) -> tuple[str | None, float]:
    """Returns (best_label_or_None, confidence in [0, 1]).

    Confidence here is the winning correlation coefficient directly
    (already bounded in [-1, 1], clipped to [0, 1]) rather than a
    total-share ratio like psda.detect() — CCA scores are meaningful in
    absolute terms, unlike raw FFT bin power.
    """
    scores = score_frequencies(window, fs, candidate_freqs, n_harmonics)
    if not scores:
        return None, 0.0
    best_label = max(scores, key=scores.get)
    confidence = max(0.0, min(1.0, scores[best_label]))
    return best_label, confidence
