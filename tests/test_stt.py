import os
from pathlib import Path

import pytest

from voice.wav import read_wav

CLIP = Path("tests/audio/what-courses.wav")


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="downloads the Moonshine model")
def test_moonshine_transcribes_a_question():
    from voice.stt import MoonshineTranscriber

    text = MoonshineTranscriber("moonshine/base").transcribe(read_wav(CLIP)).lower()
    assert "courses" in text
    assert "iit" in text.replace(".", "").replace(" ", "") or "i.i.t" in text
