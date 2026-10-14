"""Piper text to speech (baseline 6). Synthesis runs in a thread; chunks stream as ready."""

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

from piper import PiperVoice


class PiperSpeech:
    def __init__(self, model_path: Path) -> None:
        self.voice = PiperVoice.load(str(model_path))
        self.sample_rate = self.voice.config.sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        stop = threading.Event()

        def work() -> None:
            try:
                for chunk in self.voice.synthesize(text):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.audio_int16_bytes)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except BaseException as e:  # surfaced to the caller below
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=work, name="piper", daemon=True).start()
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop.set()
