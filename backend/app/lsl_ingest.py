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
import time
from collections import deque

import numpy as np
from pylsl import LostError, StreamInlet, resolve_byprop, resolve_streams

logger = logging.getLogger(__name__)


def discover_streams(wait_time: float = 3.0) -> list[dict]:
    """Lists every LSL stream currently visible on the network -- powers the
    frontend's input-source picker so switching sources doesn't require
    already knowing the exact stream name in advance."""
    return [
        {
            "name": s.name(),
            "type": s.type(),
            "channel_count": s.channel_count(),
            "nominal_srate": s.nominal_srate(),
            "hostname": s.hostname(),
        }
        for s in resolve_streams(wait_time=wait_time)
    ]


class RingBuffer:
    def __init__(self, max_samples: int, n_channels: int):
        self._buf: deque[np.ndarray] = deque(maxlen=max_samples)
        self.n_channels = n_channels
        self._lock = threading.Lock()

    def push(self, samples: list[list[float]]) -> None:
        with self._lock:
            for s in samples:
                self._buf.append(np.asarray(s, dtype=np.float64))

    def snapshot(self) -> np.ndarray:
        """Returns (n_samples, n_channels), oldest first. May be shorter
        than requested if not enough samples have arrived yet."""
        with self._lock:
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
        stale_timeout_sec: float = 2.0,
    ):
        self.stream_name = stream_name
        self.resolve_timeout_sec = resolve_timeout_sec
        self.window_sec = window_sec
        self.preferred_channel_labels = preferred_channel_labels
        self.fallback_channel_indices = fallback_channel_indices
        # How long we'll tolerate zero new samples arriving before treating
        # the stream as effectively dead. liblsl's own `recover=True` (the
        # StreamInlet default, active whenever the outlet sets a source_id
        # like our mock and the real eego stream both do) silently
        # reconnects broken TCP transport without ever raising LostError --
        # confirmed by killing the mock outlet mid-session: the inlet object
        # stays alive and `connected` never flips, but no new samples land
        # for several seconds while liblsl reconnects underneath. Without
        # this check, get_window() would keep serving a frozen buffer as if
        # nothing were wrong.
        self.stale_timeout_sec = stale_timeout_sec

        self.inlet: StreamInlet | None = None
        self.fs: float = 0.0
        self.channel_labels: list[str] = []
        self.occipital_indices: list[int] = []
        self.hostname: str = ""
        self.buffer: RingBuffer | None = None
        self.connected: bool = False
        self._last_sample_time: float = 0.0

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.RLock()
        self._data_lock = threading.Lock()

    def connect(self) -> None:
        streams = resolve_byprop("name", self.stream_name, timeout=self.resolve_timeout_sec)
        if not streams:
            raise RuntimeError(
                f"No LSL stream named '{self.stream_name}' found within "
                f"{self.resolve_timeout_sec}s. Is the simulator or eego "
                f"acquisition software running with LSL export enabled?"
            )
        inlet = StreamInlet(streams[0])
        info = inlet.info()
        fs = info.nominal_srate()
        channel_labels = self._read_channel_labels(info, info.channel_count())
        indices = resolve_channel_indices(
            channel_labels, self.preferred_channel_labels, self.fallback_channel_indices
        )
        # Publish the new sample rate and buffer together: readers must not
        # interpret an old window at a newly connected source's sample rate.
        with self._data_lock:
            self.inlet = inlet
            self.fs = fs
            self.hostname = info.hostname()
            self.channel_labels = channel_labels
            self.occipital_indices = indices
            self.buffer = RingBuffer(max(int(fs * self.window_sec * 2), 1), len(indices))
            self.connected = True
            self._last_sample_time = time.monotonic()
        logger.info(
            "Connected to LSL stream '%s': fs=%.2fHz, channels=%s, occipital_indices=%s",
            self.stream_name, self.fs, self.channel_labels, self.occipital_indices,
        )

    @staticmethod
    def _read_channel_labels(info, n_channels: int) -> list[str]:
        """Falls back to a numeric index (as a string) per-channel when the
        stream doesn't report a label for it -- e.g. raw electrode indices
        instead of 10-20 names (see resolve_channel_indices)."""
        labels = []
        ch = info.desc().child("channels").child("channel")
        for _ in range(n_channels):
            label = ch.child_value("label")
            labels.append(label if label else str(len(labels)))
            ch = ch.next_sibling()
        return labels

    def _pull_loop(self) -> None:
        assert self.inlet is not None and self.buffer is not None
        while not self._stop.is_set():
            try:
                samples, _timestamps = self.inlet.pull_chunk(timeout=0.2)
            except LostError:
                # Real amplifiers/dongles can drop out mid-session; the mock
                # never does this, so this path is only exercised on hardware
                # day. Surface it via `connected` rather than dying silently
                # and leaving callers reading a frozen buffer forever.
                logger.error(
                    "LSL stream '%s' was lost; attempting to reconnect...", self.stream_name
                )
                self.connected = False
                if not self._reconnect():
                    return  # stop() was requested while waiting to reconnect
                continue
            if samples:
                occipital_samples = [[s[i] for i in self.occipital_indices] for s in samples]
                now = time.monotonic()
                with self._data_lock:
                    if now - self._last_sample_time >= self.stale_timeout_sec:
                        self.buffer = RingBuffer(max(int(self.fs * self.window_sec * 2), 1), len(self.occipital_indices))
                    self.buffer.push(occipital_samples)
                    self._last_sample_time = now

    def _reconnect(self) -> bool:
        """Blocks (polling `_stop`) until the stream reappears.

        Returns True once reconnected, False if stop() was called first.
        """
        while not self._stop.is_set():
            try:
                self.connect()
                logger.info("Reconnected to LSL stream '%s'.", self.stream_name)
                return True
            except RuntimeError:
                self._stop.wait(1.0)
        return False

    def is_connected(self) -> bool:
        """False if the inlet was lost outright, or if liblsl's own silent
        `recover` mechanism is mid-reconnect and no fresh sample has arrived
        within `stale_timeout_sec` -- either way, callers should not trust
        get_window() until this is True again.
        """
        if self._stop.is_set() or not self.connected:
            return False
        return (time.monotonic() - self._last_sample_time) < self.stale_timeout_sec

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("EEG reader is still stopping")
                return
            self._stop.clear()
            if self.inlet is None:
                self.connect()
            self._thread = threading.Thread(target=self._pull_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=self.resolve_timeout_sec + 2.0)
                if self._thread.is_alive():
                    raise RuntimeError("EEG reader has not stopped; retry after it exits")
            self.connected = False

    def switch_stream(self, new_stream_name: str) -> None:
        """Disconnects from whatever's currently connected (if anything) and
        connects to a different stream by name instead -- lets the
        frontend's input-source picker change sources live, without
        restarting the whole backend process.

        Waits for the old reader to exit, then resolves the new stream.
        Run in a worker thread to keep the API responsive. Raises RuntimeError
        (from connect()) if the new stream can't be found -- the caller is
        left fully disconnected in that case, matching the explicit intent
        to move off whatever was previously connected rather than silently
        keeping the old one.
        """
        with self._lifecycle_lock:
            self.stop()
            with self._data_lock:
                self.stream_name = new_stream_name
                self.inlet = None
                self.fs = 0.0
                self.channel_labels = []
                self.occipital_indices = []
                self.hostname = ""
                self.buffer = None
            self.start()

    def get_window(self, window_sec: float | None = None) -> tuple[np.ndarray, float]:
        """Returns (window, fs) for the most recent `window_sec` of data."""
        with self._data_lock:
            if self.buffer is None:
                return np.empty((0, len(self.occipital_indices))), self.fs
            window_sec = window_sec if window_sec is not None else self.window_sec
            n_needed = int(self.fs * window_sec)
            snap = self.buffer.snapshot()
            if len(snap) < n_needed:
                return snap, self.fs
            return snap[-n_needed:], self.fs
