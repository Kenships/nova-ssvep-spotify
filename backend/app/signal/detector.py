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
        filtered = preprocess(
            window, fs, self.bandpass_low_hz, self.bandpass_high_hz, self.mains_notch_hz
        )
        label, confidence = _IMPLS[self.backend].detect(filtered, fs, candidate_freqs)
        if confidence < self.confidence_threshold:
            return None, confidence
        return label, confidence
