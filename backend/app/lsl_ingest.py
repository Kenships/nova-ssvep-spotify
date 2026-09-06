"""The sim/real swap point.

This module resolves an LSL stream BY NAME and buffers samples into a ring
buffer. It reads nominal_srate() and channel labels from the stream_info at
connect time rather than trusting any hardcoded assumption — the real
ant-neuro eego stream's sample rate and channel naming are configurable and
must not be guessed (see docs/hardware-bringup-notes.md).

Whether `settings.lsl_stream_name` points at the simulator or a real
ant-neuro eego stream is the ONLY thing that differs between dev/demo and
the one real-hardware session. Nothing below this module should ever
special-case "is this real or fake."
"""
from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np
from pylsl import StreamInlet, resolve_byprop

logger = logging.getLogger(__name__)


class RingBuffer:
    def __init__(self, max_samples: int, n_channels: int):
        self._buf: deque[np.ndarray] = deque(maxlen=max_samples)
        self.n_channels = n_channels

    def push(self, samples: list[list[float]]) -> None:
        for s in samples:
            self._buf.append(np.asarray(s, dtype=np.float64))

    def snapshot(self) -> np.ndarray:
        """Returns (n_samples, n_channels), oldest first. May be shorter
        than requested if not enough samples have arrived yet."""
        if not self._buf:
            return np.empty((0, self.n_channels))
        return np.stack(self._buf, axis=0)

    def __len__(self) -> int:
        return len(self._buf)


def resolve_channel_indices(
    channel_labels: list[str],
    preferred_labels: list[str],
    fallback_indices: list[int],
) -> list[int]:
    """Match preferred occipital labels (case-insensitive) against what the
    stream actually reports. Falls back to manual indices if no labels
    match at all — real eego streams may report raw electrode numbers
    instead of 10-20 names unless a montage file was applied.
    """
    lower_labels = [str(c).strip().lower() for c in channel_labels]
    matched = [
        lower_labels.index(pref.strip().lower())
        for pref in preferred_labels
        if pref.strip().lower() in lower_labels
    ]
    if matched:
        return matched
    if fallback_indices:
        logger.warning(
            "No occipital channel labels matched %s in stream labels %s; "
            "using manual index fallback %s",
            preferred_labels, channel_labels, fallback_indices,
        )
        return fallback_indices
    logger.warning(
        "No occipital channel labels matched and no fallback indices configured; "
        "using all channels."
    )
    return list(range(len(channel_labels)))


class LSLIngest:
    def __init__(
        self,
        stream_name: str,
        resolve_timeout_sec: float,
        window_sec: float,
        preferred_channel_labels: list[str],
        fallback_channel_indices: list[int],
    ):
        self.stream_name = stream_name
        self.resolve_timeout_sec = resolve_timeout_sec
        self.window_sec = window_sec
        self.preferred_channel_labels = preferred_channel_labels
        self.fallback_channel_indices = fallback_channel_indices

        self.inlet: StreamInlet | None = None
        self.fs: float = 0.0
        self.channel_labels: list[str] = []
        self.occipital_indices: list[int] = []
        self.buffer: RingBuffer | None = None

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def connect(self) -> None:
        streams = resolve_byprop("name", self.stream_name, timeout=self.resolve_timeout_sec)
        if not streams:
            raise RuntimeError(
                f"No LSL stream named '{self.stream_name}' found within "
                f"{self.resolve_timeout_sec}s. Is the simulator or eego "
                f"acquisition software running with LSL export enabled?"
            )
        self.inlet = StreamInlet(streams[0])
        info = self.inlet.info()

        # Never hardcode this — read it from the stream itself.
        self.fs = info.nominal_srate()
        n_channels = info.channel_count()

        self.channel_labels = self._read_channel_labels(info, n_channels)
        self.occipital_indices = resolve_channel_indices(
            self.channel_labels, self.preferred_channel_labels, self.fallback_channel_indices
        )

        max_samples = max(int(self.fs * self.window_sec * 2), 1)
        self.buffer = RingBuffer(max_samples, len(self.occipital_indices))

        logger.info(
            "Connected to LSL stream '%s': fs=%.2fHz, channels=%s, occipital_indices=%s",
            self.stream_name, self.fs, self.channel_labels, self.occipital_indices,
        )

    @staticmethod
    def _read_channel_labels(info, n_channels: int) -> list[str]:
        labels = []
        ch = info.desc().child("channels").child("channel")
        for _ in range(n_channels):
            label = ch.child_value("label")
            labels.append(label if label else str(len(labels)))
            ch = ch.next_sibling()
        if not any(labels):
            return [str(i) for i in range(n_channels)]
        return labels

    def _pull_loop(self) -> None:
        assert self.inlet is not None and self.buffer is not None
        while not self._stop.is_set():
            samples, _timestamps = self.inlet.pull_chunk(timeout=0.2)
            if samples:
                occipital_samples = [[s[i] for i in self.occipital_indices] for s in samples]
                self.buffer.push(occipital_samples)

    def start(self) -> None:
        if self.inlet is None:
            self.connect()
        self._thread = threading.Thread(target=self._pull_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def get_window(self, window_sec: float | None = None) -> tuple[np.ndarray, float]:
        """Returns (window, fs) for the most recent `window_sec` of data."""
        assert self.buffer is not None
        window_sec = window_sec if window_sec is not None else self.window_sec
        n_needed = int(self.fs * window_sec)
        snap = self.buffer.snapshot()
        if len(snap) < n_needed:
            return snap, self.fs
        return snap[-n_needed:], self.fs
