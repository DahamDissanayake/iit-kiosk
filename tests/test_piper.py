import asyncio
from pathlib import Path

import pytest

MODEL = Path("models/piper/en_US-lessac-medium.onnx")


@pytest.mark.skipif(not MODEL.exists(), reason="run python -m models.download first")
def test_piper_streams_pcm16_audio():
    from core.tts_piper import PiperSpeech

    speech = PiperSpeech(MODEL)

    async def go():
        return [chunk async for chunk in speech.synthesize("Welcome to IIT.")]

    chunks = asyncio.run(go())
    total = sum(len(c) for c in chunks)
    assert speech.sample_rate == 22050
    assert total % 2 == 0
    assert total / 2 / speech.sample_rate > 0.5
