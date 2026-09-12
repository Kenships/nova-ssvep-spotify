"""Common detector interface. Everything downstream (command_bus, ws_server)
talks to this module only — it doesn't know or care whether PSDA, CCA, or
FBCCA is active. Toggle via config.detector_backend or the DETECTOR_BACKEND
env var, so backends can be A/B'd live if one turns out to be flaky on
hardware day.
"""
from __future__ import annotations

import numpy as np

from . import cca, fbcca, psda
from .filters import preprocess

_IMPLS = {"psda": psda, "cca": cca, "fbcca": fbcca}


class Detector:
    def __init__(
        self,
        backend: str,
        bandpass_low_hz: float,
        bandpass_high_hz: float,
        mains_notch_hz: float,
        confidence_threshold: float,
    ):
        if backend not in _IMPLS:
            raise ValueError(f"unknown detector backend: {backend}")
        self.backend = backend
        self.bandpass_low_hz = bandpass_low_hz
        self.bandpass_high_hz = bandpass_high_hz
        self.mains_notch_hz = mains_notch_hz
        self.confidence_threshold = confidence_threshold

    def _normalize(self, raw_scores: dict[str, float]) -> dict[str, float]:
        """Puts every backend's per-candidate scores on the same [0, 1]-ish
        confidence scale detect() has always reported for the winner alone:
        psda's raw scores are unbounded FFT bin power, so its "confidence"
        is each candidate's share of total power; cca/fbcca scores are
        already bounded canonical-correlation values, just clipped."""
        if self.backend == "psda":
            total = sum(raw_scores.values())
            if total <= 0:
                return {label: 0.0 for label in raw_scores}
            return {label: score / total for label, score in raw_scores.items()}
        return {label: max(0.0, min(1.0, score)) for label, score in raw_scores.items()}

    def detect_with_scores(
        self,
        window: np.ndarray,
        fs: float,
        candidate_freqs: dict[str, float],
    ) -> tuple[str | None, float, dict[str, float]]:
        """Like detect(), but also returns every candidate's confidence, not
        just the winner's -- e.g. for the debug panel to show how close a
        detection was across all targets. Computed from a single backend
        pass so getting the full breakdown doesn't double the (real, for
        cca/fbcca) per-tick compute cost versus calling detect() alone.
        """
        filtered = preprocess(
            window, fs, self.bandpass_low_hz, self.bandpass_high_hz, self.mains_notch_hz
        )
        raw_scores = _IMPLS[self.backend].score_frequencies(filtered, fs, candidate_freqs)
        scores = self._normalize(raw_scores)
        if not scores:
            return None, 0.0, {}
        best_label = max(scores, key=scores.get)
        confidence = scores[best_label]
        if confidence < self.confidence_threshold:
            return None, confidence, scores
        return best_label, confidence, scores

    def detect(
        self,
        window: np.ndarray,
        fs: float,
        candidate_freqs: dict[str, float],
    ) -> tuple[str | None, float]:
        """window: (n_samples, n_channels) raw EEG. Returns (label_or_None, confidence).

        Returns (None, confidence) if the winning confidence doesn't clear
        `confidence_threshold` — an ALS user who is resting/blinking and not
        attending any target should not spuriously trigger a command.
        """
        label, confidence, _ = self.detect_with_scores(window, fs, candidate_freqs)
        return label, confidence
