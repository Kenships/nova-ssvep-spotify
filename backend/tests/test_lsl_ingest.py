"""Exercises LSLIngest against fake pylsl objects (FakeStreamInfo/FakeInlet)
patched in for resolve_byprop/StreamInlet -- no real LSL network stream is
ever created, so these tests are fast and hermetic while still exercising
the real threading, buffering, and reconnect logic.
"""
import time

import numpy as np
import pytest
from pylsl import LostError

import app.lsl_ingest as lsl_ingest_module
from app.lsl_ingest import LSLIngest, RingBuffer, resolve_channel_indices


def _wait_until(predicate, timeout=2.0, interval=0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeChannelNode:
    def __init__(self, labels, idx=0):
        self._labels = labels
        self._idx = idx

    def child_value(self, name):
        if name == "label" and self._idx < len(self._labels):
            return self._labels[self._idx]
        return ""

    def next_sibling(self):
        return FakeChannelNode(self._labels, self._idx + 1)


class FakeChannelsNode:
    def __init__(self, labels):
        self._labels = labels

    def child(self, name):
        assert name == "channel"
        return FakeChannelNode(self._labels, 0)


class FakeDesc:
    def __init__(self, labels):
        self._labels = labels

    def child(self, name):
        assert name == "channels"
        return FakeChannelsNode(self._labels)


class FakeStreamInfo:
    def __init__(self, fs, labels):
        self._fs = fs
        self._labels = labels

    def nominal_srate(self):
        return self._fs

    def channel_count(self):
        return len(self._labels)

    def desc(self):
        return FakeDesc(self._labels)


class FakeInlet:
    """Stands in for pylsl.StreamInlet. `chunks` is a list of sample-lists
    handed back one-per-pull_chunk call; once exhausted, further calls
    return an empty chunk (mimicking an idle-but-alive stream) unless
    `raise_lost_on_call` names a future call index to raise LostError on
    instead.
    """

    def __init__(self, info, chunks=None, raise_lost_on_call=None):
        self._info = info
        self._chunks = list(chunks or [])
        self._call_count = 0
        self._raise_lost_on_call = raise_lost_on_call

    def info(self):
        return self._info

    def pull_chunk(self, timeout=0.0):
        self._call_count += 1
        if self._raise_lost_on_call == self._call_count:
            raise LostError("stream lost")
        if self._chunks:
            return self._chunks.pop(0), [0.0]
        return [], []


# --- RingBuffer -------------------------------------------------------


def test_ring_buffer_push_and_snapshot_preserves_order():
    buf = RingBuffer(max_samples=10, n_channels=2)
    buf.push([[1, 2], [3, 4]])
    buf.push([[5, 6]])
    snap = buf.snapshot()
    assert snap.shape == (3, 2)
    assert snap.tolist() == [[1, 2], [3, 4], [5, 6]]
    assert len(buf) == 3


def test_ring_buffer_empty_snapshot_has_correct_channel_width():
    buf = RingBuffer(max_samples=10, n_channels=4)
    snap = buf.snapshot()
    assert snap.shape == (0, 4)


def test_ring_buffer_drops_oldest_beyond_maxlen():
    buf = RingBuffer(max_samples=3, n_channels=1)
    buf.push([[1], [2], [3], [4], [5]])
    snap = buf.snapshot()
    assert len(buf) == 3
    assert snap.tolist() == [[3], [4], [5]]


# --- resolve_channel_indices -------------------------------------------


def test_resolve_channel_indices_matches_case_insensitively():
    idx = resolve_channel_indices(["FP1", "Oz", "O1", "O2"], ["oz", "o1"], [])
    assert idx == [1, 2]


def test_resolve_channel_indices_falls_back_to_manual_indices():
    idx = resolve_channel_indices(["1", "2", "3", "4"], ["Oz", "O1"], [2, 3])
    assert idx == [2, 3]


def test_resolve_channel_indices_falls_back_to_all_channels():
    idx = resolve_channel_indices(["1", "2"], ["Oz", "O1"], [])
    assert idx == [0, 1]


# --- LSLIngest.connect() -------------------------------------------------


def test_connect_reads_fs_and_channels_from_stream_info(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz", "O1", "O2", "POz"])
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [info])
    monkeypatch.setattr(lsl_ingest_module, "StreamInlet", lambda _stream: FakeInlet(info))

    ingest = LSLIngest("Fake", 1.0, 2.0, ["Oz", "O1", "O2", "POz"], [])
    ingest.connect()

    assert ingest.fs == 250.0
    assert ingest.channel_labels == ["Oz", "O1", "O2", "POz"]
    assert ingest.occipital_indices == [0, 1, 2, 3]
    assert ingest.connected is True
    assert ingest.is_connected() is True


def test_connect_raises_when_no_stream_found(monkeypatch):
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [])
    ingest = LSLIngest("Fake", 0.01, 2.0, ["Oz"], [])
    with pytest.raises(RuntimeError):
        ingest.connect()


def test_is_connected_false_before_any_connect_attempt():
    ingest = LSLIngest("Fake", 0.01, 2.0, ["Oz"], [])
    assert ingest.is_connected() is False


# --- LSLIngest start/stop/pull loop --------------------------------------


def test_start_buffers_pulled_samples_for_get_window(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz", "O1", "O2", "POz"])
    inlet = FakeInlet(info, chunks=[[[1, 2, 3, 4]] * 10, [[5, 6, 7, 8]] * 10])
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [info])
    monkeypatch.setattr(lsl_ingest_module, "StreamInlet", lambda _stream: inlet)

    ingest = LSLIngest("Fake", 1.0, 2.0, ["Oz", "O1", "O2", "POz"], [])
    ingest.start()
    try:
        assert _wait_until(lambda: len(ingest.buffer) >= 20, timeout=2.0)
        window, fs = ingest.get_window(window_sec=20 / 250.0)
        assert fs == 250.0
        assert window.shape == (20, 4)
        assert window[-1].tolist() == [5, 6, 7, 8]
    finally:
        ingest.stop()


def test_get_window_returns_short_window_when_not_enough_buffered(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz"])
    inlet = FakeInlet(info, chunks=[[[1]]])
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [info])
    monkeypatch.setattr(lsl_ingest_module, "StreamInlet", lambda _stream: inlet)

    ingest = LSLIngest("Fake", 1.0, 2.0, ["Oz"], [])
    ingest.start()
    try:
        assert _wait_until(lambda: len(ingest.buffer) >= 1, timeout=2.0)
        window, fs = ingest.get_window(window_sec=2.0)  # needs 500 samples, only 1 buffered
        assert fs == 250.0
        assert window.shape[0] < int(fs * 2.0)
    finally:
        ingest.stop()


def test_is_connected_goes_stale_when_samples_stop_arriving(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz"])
    inlet = FakeInlet(info, chunks=[[[1]]])  # one sample, then the well runs dry
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [info])
    monkeypatch.setattr(lsl_ingest_module, "StreamInlet", lambda _stream: inlet)

    ingest = LSLIngest("Fake", 1.0, 2.0, ["Oz"], [], stale_timeout_sec=0.1)
    ingest.start()
    try:
        assert _wait_until(lambda: ingest.is_connected() is True, timeout=2.0)
        assert _wait_until(lambda: ingest.is_connected() is False, timeout=2.0)
    finally:
        ingest.stop()


def test_lost_error_triggers_reconnect_and_data_resumes(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz"])
    inlets = [
        FakeInlet(info, raise_lost_on_call=1),  # dies on the very first pull
        FakeInlet(info, chunks=[[[42]]]),  # the reconnect's fresh inlet
    ]
    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", lambda *a, **k: [info])
    monkeypatch.setattr(lsl_ingest_module, "StreamInlet", lambda _stream: inlets.pop(0))

    ingest = LSLIngest("Fake", 1.0, 2.0, ["Oz"], [], stale_timeout_sec=5.0)
    ingest.start()
    try:
        # Proves the pull thread survived the LostError (didn't die
        # silently) and is receiving data through the newly-reconnected inlet.
        assert _wait_until(lambda: len(ingest.buffer) >= 1, timeout=2.0)
        assert ingest.is_connected() is True
    finally:
        ingest.stop()


def test_stop_interrupts_reconnect_wait_promptly(monkeypatch):
    info = FakeStreamInfo(250.0, ["Oz"])
    call_count = {"n": 0}

    def fake_resolve(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [info]
        return []  # every reconnect attempt fails once the stream drops

    monkeypatch.setattr(lsl_ingest_module, "resolve_byprop", fake_resolve)
    monkeypatch.setattr(
        lsl_ingest_module, "StreamInlet", lambda _stream: FakeInlet(info, raise_lost_on_call=1)
    )

    ingest = LSLIngest("Fake", 0.01, 2.0, ["Oz"], [])
    ingest.start()
    assert _wait_until(lambda: ingest.connected is False, timeout=2.0)

    # _reconnect() is now looping with a 1s wait between failed attempts;
    # stop() must interrupt that wait rather than block for it.
    start = time.monotonic()
    ingest.stop()
    elapsed = time.monotonic() - start

    assert elapsed < 0.9
    assert not ingest._thread.is_alive()
