"""Optional detector upgrade: Filter-Bank CCA (Chen et al. 2015, "Filter
bank canonical correlation analysis for implementing a high-speed
SSVEP-based brain-computer interface", J. Neural Eng. 12 046008).

Implements their best-performing "M3" filter bank design: a SHARED bank of
n_subbands, built once from the raw window, then correlated against every
candidate frequency's CCA reference signal -- not a fresh filter per
candidate (an earlier version of this file did that; a different,
unvalidated design that also filtered n_subbands x n_candidates times
instead of just n_subbands times). The nth sub-band spans
[n * f0_base - 2, high_hz], where f0_base is the lowest candidate
frequency -- matching the paper's use of their lowest stimulus frequency as
the shared base unit for a filter bank reused across all candidates.

Defaults (n_subbands=7, n_harmonics=5, weight w(n) = n^-a + b with
a=1.25, b=0.25) match the paper's own grid-search-optimized parameters for
M3, and high_hz=88 matches their empirical finding that SSVEP harmonic SNR
(not amplitude, which drops fast) stays usable up to roughly that frequency
-- see their figure 5. That specific number came from their setup, not a
law of nature; worth re-validating against this project's own hardware if
accuracy matters enough to chase further. BANDPASS_HIGH_HZ (config.py) must
be >= high_hz or the outer preprocessing step truncates sub-bands before
this module ever sees them.

Same no-training-data property as cca.py. CCA fit count is still
n_subbands x n_candidates per window (unchanged from before) -- the shared
filter bank only saves the bandpass filtering step, not the dominant CCA
cost.
"""
import numpy as np
from sklearn.cross_decomposition import CCA

from .cca import _reference_signals
from .filters import bandpass


def _subband_weight(m: int, a: float = 1.25, b: float = 0.25) -> float:
    return m ** (-a) + b


def _build_filter_bank(
    window: np.ndarray, fs: float, f0_base: float, n_subbands: int, high_hz: float
) -> list[np.ndarray]:
    """Shared sub-bands, computed once from the raw window and reused for
    every candidate's CCA correlation below."""
    subbands = []
    for m in range(1, n_subbands + 1):
        low_hz = max(f0_base * m - 2.0, 1.0)
        try:
            subbands.append(bandpass(window, fs, low_hz, high_hz))
        except Exception:
            subbands.append(np.zeros_like(window))
    return subbands


def score_frequencies(
    window: np.ndarray,
    fs: float,
    candidate_freqs: dict[str, float],
    n_harmonics: int = 5,
    n_subbands: int = 7,
    high_hz: float = 88.0,
) -> dict[str, float]:
    """window: (n_samples, n_channels), already bandpass+notch filtered.

    Returns each candidate's weighted sum of squared sub-band correlations,
    normalized to [0, 1] by the max achievable weight sum so it's comparable
    to cca.py's confidence scale.
    """
    if not candidate_freqs:
        return {}
    n_samples = window.shape[0]
    n_components = 1  # first canonical pair is what SSVEP-CCA uses
    weight_sum = sum(_subband_weight(m) for m in range(1, n_subbands + 1))
    f0_base = min(candidate_freqs.values())
    subbands = _build_filter_bank(window, fs, f0_base, n_subbands, high_hz)

    scores: dict[str, float] = {}
    for label, f0 in candidate_freqs.items():
        ref = _reference_signals(f0, n_samples, fs, n_harmonics)
        total = 0.0
        for m, sub in enumerate(subbands, start=1):
            try:
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
    n_harmonics: int = 5,
    n_subbands: int = 7,
) -> tuple[str | None, float]:
    """Returns (best_label_or_None, confidence in [0, 1])."""
    scores = score_frequencies(window, fs, candidate_freqs, n_harmonics, n_subbands)
    if not scores:
        return None, 0.0
    best_label = max(scores, key=scores.get)
    confidence = max(0.0, min(1.0, scores[best_label]))
    return best_label, confidence
