"""Phase 5 asset: replays a real captured ant-neuro session (an .xdf file
recorded via LabRecorder during the one hardware day) back through a mock
LSL outlet, so a "looks-like-real" run is reproducible on judging day
without depending on live electrodes or noisy demo-hall conditions.

Not usable until an .xdf capture exists from the Phase 4 hardware session --
this is a stub with the intended interface filled in ahead of time so
Phase 5 is a fast wire-up, not a fresh design.

Usage (once a real capture exists):
    python recorded_session_replay.py --xdf path/to/session.xdf --name MockEEG
"""
from __future__ import annotations

import argparse
import time

from pylsl import StreamInfo, StreamOutlet

try:
    import pyxdf
except ImportError:
    pyxdf = None


def load_eeg_stream_from_xdf(xdf_path: str) -> tuple[list[list[float]], float, list[str]]:
    """Returns (samples, fs, channel_labels) for the EEG stream in the file.

    Requires `pyxdf` (pip install pyxdf) -- not in backend/requirements.txt
    since it's only needed for this Phase 5 replay tool, not the live path.
    """
    if pyxdf is None:
        raise RuntimeError("pyxdf is required for replay: pip install pyxdf")

    streams, _header = pyxdf.load_xdf(xdf_path)
    eeg_streams = [s for s in streams if s["info"]["type"][0].upper() == "EEG"]
    if not eeg_streams:
        raise RuntimeError(f"No EEG stream found in {xdf_path}")
    stream = eeg_streams[0]

    fs = float(stream["info"]["nominal_srate"][0])
    channels_info = stream["info"]["desc"][0]["channels"][0]["channel"]
    labels = [c["label"][0] for c in channels_info]
    samples = stream["time_series"].tolist()
    return samples, fs, labels


def replay(xdf_path: str, stream_name: str, loop: bool) -> None:
    samples, fs, labels = load_eeg_stream_from_xdf(xdf_path)

    info = StreamInfo(
        name=stream_name,
        type="EEG",
        channel_count=len(labels),
        nominal_srate=fs,
        channel_format="float32",
        source_id="replay-session-001",
    )
    channels = info.desc().append_child("channels")
    for label in labels:
        channels.append_child("channel").append_child_value("label", label)
    outlet = StreamOutlet(info)

    period = 1.0 / fs
    print(f"[replay] streaming {len(samples)} samples at {fs}Hz as '{stream_name}'")
    while True:
        next_tick = time.perf_counter()
        for sample in samples:
            outlet.push_sample(sample)
            next_tick += period
            sleep_for = next_tick - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
        if not loop:
            break
        print("[replay] reached end of capture, looping")


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xdf", required=True, help="Path to the recorded .xdf session")
    parser.add_argument("--name", default="MockEEG", help="LSL stream name to emit")
    parser.add_argument("--loop", action="store_true", help="Loop the recording continuously")
    args = parser.parse_args()
    replay(args.xdf, args.name, args.loop)
