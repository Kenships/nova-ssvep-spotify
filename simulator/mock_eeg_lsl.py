"""Standalone synthetic EEG source. Emits a StreamOutlet named "MockEEG"
(matches config.py's default LSL_STREAM_NAME) that looks structurally
identical to a real ant-neuro eego LSL stream to everything downstream:
same shape (n_channels float samples per tick), same nominal_srate()
reported via stream_info, same style of channel labels.

This is what makes ~29 of the 30 build days productive without hardware in
hand -- the backend's lsl_ingest.py doesn't know or care that this is fake.

Usage:
    python mock_eeg_lsl.py                     # defaults to 10Hz, idle after
    python mock_eeg_lsl.py --freq 7.5          # attend a specific frequency
    python mock_eeg_lsl.py --script scenarios/demo_script.yaml  # scripted run

While running interactively (no --script), press number keys 1-4 to switch
which target frequency is being "attended", or 0 to go idle (noise only).
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

import numpy as np
import yaml
from pylsl import StreamInfo, StreamOutlet

CHANNEL_LABELS = ["Oz", "O1", "O2", "POz"]
SAMPLE_RATE_HZ = 250.0
NOISE_AMPLITUDE = 0.3
SIGNAL_AMPLITUDE = 1.0

# Keep in sync with backend/app/config.py's mood_frequencies / transport_frequencies.
FREQUENCY_PRESETS = {
    "1": 7.5,
    "2": 60 / 7,
    "3": 10.0,
    "4": 12.0,
    "0": None,  # idle / no attended target
}


class MockEEGSource:
    def __init__(self, stream_name: str = "MockEEG", fs: float = SAMPLE_RATE_HZ):
        self.fs = fs
        self._attended_freq: float | None = None
        self._lock = threading.Lock()
        self._t = 0.0

        info = StreamInfo(
            name=stream_name,
            type="EEG",
            channel_count=len(CHANNEL_LABELS),
            nominal_srate=fs,
            channel_format="float32",
            source_id="mock-eeg-001",
        )
        channels = info.desc().append_child("channels")
        for label in CHANNEL_LABELS:
            ch = channels.append_child("channel")
            ch.append_child_value("label", label)
            ch.append_child_value("unit", "microvolts")
            ch.append_child_value("type", "EEG")

        self.outlet = StreamOutlet(info)

    def set_attended_frequency(self, freq_hz: float | None) -> None:
        with self._lock:
            self._attended_freq = freq_hz
            label = f"{freq_hz:.2f}Hz" if freq_hz else "idle"
            print(f"[mock_eeg_lsl] attending: {label}")

    def _sample(self) -> list[float]:
        with self._lock:
            freq = self._attended_freq
        noise = np.random.normal(0, NOISE_AMPLITUDE, len(CHANNEL_LABELS))
        if freq is None:
            return noise.tolist()
        signal_val = SIGNAL_AMPLITUDE * np.sin(2 * np.pi * freq * self._t)
        return (signal_val + noise).tolist()

    def run_forever(self) -> None:
        period = 1.0 / self.fs
        next_tick = time.perf_counter()
        while True:
            self.outlet.push_sample(self._sample())
            self._t += period
            next_tick += period
            sleep_for = next_tick - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)


def _keyboard_control_loop(source: MockEEGSource) -> None:
    print("Press 1=Calm/PlayPause(7.5Hz) 2=Happy/Next(8.57Hz) 3=Energetic/Prev(10Hz) "
          "4=Sad/BackToMood(12Hz) 0=idle, Ctrl+C to quit")
    while True:
        key = sys.stdin.readline().strip()
        if key in FREQUENCY_PRESETS:
            source.set_attended_frequency(FREQUENCY_PRESETS[key])


def _run_script(source: MockEEGSource, script_path: str) -> None:
    with open(script_path, encoding="utf-8") as f:
        script = yaml.safe_load(f)
    print(f"[mock_eeg_lsl] running scripted scenario: {script_path}")
    for step in script.get("steps", []):
        freq = step.get("freq_hz")
        duration = step.get("duration_sec", 3.0)
        source.set_attended_frequency(freq)
        time.sleep(duration)
    print("[mock_eeg_lsl] scripted scenario complete; going idle")
    source.set_attended_frequency(None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="MockEEG", help="LSL stream name")
    parser.add_argument("--freq", type=float, default=None, help="Initial attended frequency (Hz)")
    parser.add_argument("--script", default=None, help="Path to a scenario YAML to run non-interactively")
    args = parser.parse_args()

    source = MockEEGSource(stream_name=args.name)
    if args.freq is not None:
        source.set_attended_frequency(args.freq)

    streaming_thread = threading.Thread(target=source.run_forever, daemon=True)
    streaming_thread.start()

    if args.script:
        _run_script(source, args.script)
        streaming_thread.join()
    else:
        try:
            _keyboard_control_loop(source)
        except KeyboardInterrupt:
            print("\n[mock_eeg_lsl] stopping")


if __name__ == "__main__":
    main()
