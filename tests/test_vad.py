from pathlib import Path

import numpy as np
import pytest

from voice.vad import FRAME, Segmenter, SileroVad


def frames(n, value=0.0):
    return [np.full(FRAME, value, np.float32) for _ in range(n)]


def run(seg, probs):
    events = []
    for i, p in enumerate(probs):
        ev = seg.push(np.full(FRAME, i, np.float32), p)
        if ev is not None:
            events.append(ev)
    return events


def test_speech_start_and_end_with_pre_roll():
    seg = Segmenter(start_frames=3, end_silence_frames=5, pre_roll=4)
    probs = [0.1] * 6 + [0.9] * 10 + [0.0] * 5
    events = run(seg, probs)
    assert events[0] == "start"
    kind, audio = events[1]
    assert kind == "end"
    first_sample = audio[0]
    assert first_sample == 5  # pre-roll keeps frames 5..8 before speech was confirmed at frame 8
    assert len(audio) == (4 + 7 + 5) * FRAME
    assert not seg.active


def test_short_noise_does_not_start_speech():
    seg = Segmenter(start_frames=3)
    assert run(seg, [0.1, 0.9, 0.9, 0.1, 0.9, 0.1] * 5) == []


def test_brief_dip_does_not_end_speech():
    seg = Segmenter(start_frames=2, end_silence_frames=4)
    events = run(seg, [0.9] * 5 + [0.2, 0.2] + [0.9] * 5 + [0.0] * 4)
    assert [e if isinstance(e, str) else e[0] for e in events] == ["start", "end"]


def test_long_speech_is_cut_at_the_cap():
    seg = Segmenter(start_frames=2, max_frames=20)
    events = run(seg, [0.9] * 60)
    ends = [e for e in events if isinstance(e, tuple)]
    assert len(ends) >= 2
    assert all(len(a) <= 20 * FRAME for _, a in ends)


def test_current_audio_grows_while_active():
    seg = Segmenter(start_frames=2, pre_roll=2)
    run(seg, [0.9] * 6)
    assert seg.active
    assert len(seg.current_audio()) == 6 * FRAME


MODEL = Path("models/silero_vad.onnx")


@pytest.mark.skipif(not MODEL.exists(), reason="run python -m models.download first")
def test_silero_scores_silence_low():
    vad = SileroVad(MODEL)
    scores = [vad.prob(f) for f in frames(10)]
    assert max(scores) < 0.2
