"""Exercises recorded_session_replay.py's XDF-parsing and replay-loop logic
against a fake pyxdf module and fake pylsl StreamInfo/StreamOutlet -- no real
.xdf capture or LSL network stream is needed.
"""
from types import SimpleNamespace

import numpy as np
import pytest

import recorded_session_replay as replay_module


class FakeDescNode:
    def append_child(self, name):
        return FakeDescNode()

    def append_child_value(self, name, value):
        pass


class FakeStreamInfo:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def desc(self):
        return FakeDescNode()


class FakeStreamOutlet:
    instances: list["FakeStreamOutlet"] = []

    def __init__(self, info):
        self.info = info
        self.pushed: list[list[float]] = []
        FakeStreamOutlet.instances.append(self)

    def push_sample(self, sample):
        self.pushed.append(sample)


@pytest.fixture(autouse=True)
def fake_pylsl(monkeypatch):
    monkeypatch.setattr(replay_module, "StreamInfo", FakeStreamInfo)
    monkeypatch.setattr(replay_module, "StreamOutlet", FakeStreamOutlet)
    monkeypatch.setattr(replay_module.time, "sleep", lambda s: None)
    FakeStreamOutlet.instances = []


def test_load_eeg_stream_from_xdf_raises_without_pyxdf(monkeypatch):
    monkeypatch.setattr(replay_module, "pyxdf", None)
    with pytest.raises(RuntimeError, match="pyxdf is required"):
        replay_module.load_eeg_stream_from_xdf("whatever.xdf")


def test_load_eeg_stream_from_xdf_raises_when_no_eeg_stream(monkeypatch):
    fake_pyxdf = SimpleNamespace(load_xdf=lambda path: ([{"info": {"type": ["Markers"]}}], None))
    monkeypatch.setattr(replay_module, "pyxdf", fake_pyxdf)
    with pytest.raises(RuntimeError, match="No EEG stream found"):
        replay_module.load_eeg_stream_from_xdf("whatever.xdf")


def _fake_xdf_stream():
    return {
        "info": {
            "type": ["EEG"],
            "nominal_srate": ["250.0"],
            "desc": [{"channels": [{"channel": [{"label": ["Oz"]}, {"label": ["O1"]}]}]}],
        },
        "time_series": np.array([[1.0, 2.0], [3.0, 4.0]]),
    }


def test_load_eeg_stream_from_xdf_parses_first_eeg_stream(monkeypatch):
    fake_pyxdf = SimpleNamespace(load_xdf=lambda path: ([_fake_xdf_stream()], None))
    monkeypatch.setattr(replay_module, "pyxdf", fake_pyxdf)

    samples, fs, labels = replay_module.load_eeg_stream_from_xdf("session.xdf")

    assert fs == 250.0
    assert labels == ["Oz", "O1"]
    assert samples == [[1.0, 2.0], [3.0, 4.0]]


def test_replay_pushes_all_samples_once_without_looping(monkeypatch):
    monkeypatch.setattr(
        replay_module, "load_eeg_stream_from_xdf", lambda path: ([[1.0], [2.0], [3.0]], 100.0, ["Oz"])
    )

    replay_module.replay("session.xdf", "TestStream", loop=False)

    assert len(FakeStreamOutlet.instances) == 1
    assert FakeStreamOutlet.instances[0].pushed == [[1.0], [2.0], [3.0]]


def test_replay_loops_and_reprints_until_interrupted(monkeypatch, capsys):
    monkeypatch.setattr(replay_module, "load_eeg_stream_from_xdf", lambda path: ([[1.0], [2.0]], 100.0, ["Oz"]))

    def push_sample(self, sample):
        self.pushed.append(sample)
        if len(self.pushed) >= 5:
            raise RuntimeError("stop replay")  # the only way out of replay's `while True`

    monkeypatch.setattr(FakeStreamOutlet, "push_sample", push_sample)

    with pytest.raises(RuntimeError, match="stop replay"):
        replay_module.replay("session.xdf", "TestStream", loop=True)

    assert len(FakeStreamOutlet.instances[0].pushed) == 5
    assert "reached end of capture, looping" in capsys.readouterr().out
