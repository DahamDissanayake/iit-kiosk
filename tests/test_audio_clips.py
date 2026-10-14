from pathlib import Path

import numpy as np
import pytest

from voice.wav import read_wav

CLIPS = sorted(Path("tests/audio").glob("*.wav"))


def test_there_are_test_clips():
    assert {c.stem for c in CLIPS} >= {"what-courses", "hello"}


@pytest.mark.parametrize("clip", CLIPS, ids=lambda c: c.name)
def test_clip_is_16khz_mono_speech(clip):
    audio = read_wav(clip)  # raises unless 16 kHz, 16-bit
    seconds = len(audio) / 16000
    assert 0.5 <= seconds <= 10, seconds
    assert np.abs(audio).max() > 0.1, "clip is silent"
    assert np.abs(audio[:2000]).max() < 0.01, "clip should start with silence"
