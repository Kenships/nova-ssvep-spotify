"""Exercises mock_eeg_lsl.py against fake pylsl StreamInfo/StreamOutlet -- no
real LSL network stream is ever created, matching backend/tests/
test_lsl_ingest.py's convention of keeping unit tests hermetic.
"""
import sys

import numpy as np
import pytest

import mock_eeg_lsl


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
    def __init__(self, info):
        self.info = info
        self.pushed: list[list[float]] = []

    def push_sample(self, sample):
        self.pushed.append(sample)


@pytest.fixture(autouse=True)
def fake_pylsl(monkeypatch):
    monkeypatch.setattr(mock_eeg_lsl, "StreamInfo", FakeStreamInfo)
    monkeypatch.setattr(mock_eeg_lsl, "StreamOutlet", FakeStreamOutlet)


def test_source_init_builds_outlet():
    source = mock_eeg_lsl.MockEEGSource(stream_name="test-stream", fs=100.0)
    assert source.fs == 100.0
    assert isinstance(source.outlet, FakeStreamOutlet)


def test_set_attended_frequency_prints_hz_label(capsys):
    source = mock_eeg_lsl.MockEEGSource()
    source.set_attended_frequency(7.5)
    assert source._attended_freq == 7.5
    assert "7.50Hz" in capsys.readouterr().out


def test_set_attended_frequency_none_prints_idle(capsys):
    source = mock_eeg_lsl.MockEEGSource()
    source.set_attended_frequency(None)
    assert source._attended_freq is None
    assert "idle" in capsys.readouterr().out


def test_sample_is_pure_noise_when_idle(monkeypatch):
    monkeypatch.setattr(np.random, "normal", lambda mean, std, size: np.zeros(size))
    source = mock_eeg_lsl.MockEEGSource()
    source.set_attended_frequency(None)
    assert source._sample() == [0.0] * len(mock_eeg_lsl.CHANNEL_LABELS)


def test_sample_includes_signal_when_attending(monkeypatch):
    monkeypatch.setattr(np.random, "normal", lambda mean, std, size: np.zeros(size))
    source = mock_eeg_lsl.MockEEGSource()
    freq = 10.0
    source.set_attended_frequency(freq)
    source._t = 1.0 / (4 * freq)  # quarter period -> sin(2*pi*f*t) == 1

    sample = source._sample()

    assert sample == pytest.approx([mock_eeg_lsl.SIGNAL_AMPLITUDE] * len(mock_eeg_lsl.CHANNEL_LABELS))


def test_run_forever_pushes_samples_and_advances_time(monkeypatch):
    monkeypatch.setattr(mock_eeg_lsl.time, "sleep", lambda s: None)
    source = mock_eeg_lsl.MockEEGSource(fs=1000.0)

    calls = {"n": 0}
    real_push = source.outlet.push_sample

    def counting_push(sample):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("stop loop")  # the only way out of run_forever's `while True`
        real_push(sample)

    monkeypatch.setattr(source.outlet, "push_sample", counting_push)

    with pytest.raises(RuntimeError, match="stop loop"):
        source.run_forever()

    assert calls["n"] == 3
    assert source._t > 0


class _FakeStdinLines:
    """Hands back each line in order, then raises to break the infinite
    `while True` in _keyboard_control_loop once the script is exhausted."""

    def __init__(self, lines):
        self._lines = iter(lines)

    def readline(self):
        try:
            return next(self._lines)
        except StopIteration:
            raise EOFError("no more fake input") from None


def test_keyboard_control_loop_dispatches_known_keys_and_ignores_unknown(monkeypatch, capsys):
    calls = []

    class FakeSource:
        def set_attended_frequency(self, freq):
            calls.append(freq)

    monkeypatch.setattr(mock_eeg_lsl.sys, "stdin", _FakeStdinLines(["1\n", "not-a-key\n", "0\n"]))

    with pytest.raises(EOFError):
        mock_eeg_lsl._keyboard_control_loop(FakeSource())

    assert calls == [mock_eeg_lsl.FREQUENCY_PRESETS["1"], None]
    assert "Press 1=Calm" in capsys.readouterr().out


def test_run_script_walks_steps_in_order_then_goes_idle(tmp_path, monkeypatch, capsys):
    script_path = tmp_path / "scenario.yaml"
    script_path.write_text(
        "steps:\n"
        "  - freq_hz: 7.5\n"
        "    duration_sec: 0.01\n"
        "  - freq_hz: 12.0\n"
        "    duration_sec: 0.02\n",
        encoding="utf-8",
    )
    sleeps = []
    monkeypatch.setattr(mock_eeg_lsl.time, "sleep", lambda s: sleeps.append(s))

    calls = []

    class FakeSource:
        def set_attended_frequency(self, freq):
            calls.append(freq)

    mock_eeg_lsl._run_script(FakeSource(), str(script_path))

    assert calls == [7.5, 12.0, None]
    assert sleeps == [0.01, 0.02]
    assert "scripted scenario complete" in capsys.readouterr().out


class _FakeThread:
    """Stands in for threading.Thread so run_forever's real `while True`
    never actually starts running in the background during tests."""

    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        pass

    def join(self):
        pass


def test_main_runs_scripted_scenario(tmp_path, monkeypatch):
    script_path = tmp_path / "scenario.yaml"
    script_path.write_text("steps: []\n", encoding="utf-8")
    monkeypatch.setattr(mock_eeg_lsl.threading, "Thread", _FakeThread)
    monkeypatch.setattr(mock_eeg_lsl.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["mock_eeg_lsl.py", "--script", str(script_path)])

    mock_eeg_lsl.main()  # must return promptly, not hang


def test_main_sets_initial_frequency_and_stops_on_keyboard_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(mock_eeg_lsl.threading, "Thread", _FakeThread)
    monkeypatch.setattr(
        mock_eeg_lsl,
        "_keyboard_control_loop",
        lambda source: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(sys, "argv", ["mock_eeg_lsl.py", "--freq", "9.0"])

    calls = []
    original = mock_eeg_lsl.MockEEGSource.set_attended_frequency

    def spy(self, freq):
        calls.append(freq)
        return original(self, freq)

    monkeypatch.setattr(mock_eeg_lsl.MockEEGSource, "set_attended_frequency", spy)

    mock_eeg_lsl.main()

    assert calls == [9.0]
    assert "stopping" in capsys.readouterr().out
