"""Speech output: the interface, an M1 stand-in, and the ordered playback queue."""

import asyncio
import base64
import logging
import random
from array import array
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

log = logging.getLogger("kiosk.speech")


class SpeechOutput(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield little-endian PCM16 mono chunks."""


class FakeSpeech:
    """Speech-like babble so the mouth moves before Piper is wired in (replaced in M2)."""

    sample_rate = 22050

    def __init__(self, seconds_per_char: float = 0.055, chunk_s: float = 0.25) -> None:
        self.seconds_per_char = seconds_per_char
        self.chunk_s = chunk_s

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        seconds = min(12.0, max(0.6, len(text) * self.seconds_per_char))
        pcm = _babble(seconds, self.sample_rate, random.Random(len(text)))
        step = int(self.chunk_s * self.sample_rate)
        for off in range(0, len(pcm), step):
            yield pcm[off : off + step].tobytes()
            await asyncio.sleep(0)


def _babble(seconds: float, rate: int, rnd: random.Random) -> array:
    """Sawtooth bursts shaped like syllables, with short and long pauses."""
    out = array("h")
    t = 0.0
    while t < seconds:
        syllable = 0.12 + rnd.random() * 0.12
        pause = 0.25 if rnd.random() < 0.18 else 0.03
        freq = 130 + rnd.random() * 60
        amp = 0.18 + rnd.random() * 0.12
        n = int(syllable * rate)
        for i in range(n):
            x = i / n
            env = x / 0.35 if x < 0.35 else (1 - x) / 0.65
            phase = (i * freq / rate) % 1.0
            out.append(int(32767 * amp * env * (2 * phase - 1)))
        out.extend([0] * int(pause * rate))
        t += syllable + pause
    return out


class SpeechQueue:
    """Synthesises one utterance at a time so sentences never interleave."""

    def __init__(
        self,
        speech: SpeechOutput,
        send: Callable[[dict], Awaitable[None]],
        on_failed: Callable[[str], Awaitable[None]],
    ) -> None:
        self.speech = speech
        self.send = send
        self.on_failed = on_failed
        self._q: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._current: asyncio.Task | None = None

    def put(self, sid: str, text: str) -> None:
        self._q.put_nowait((sid, text))

    def clear(self) -> None:
        while not self._q.empty():
            self._q.get_nowait()
        if self._current:
            self._current.cancel()

    async def run(self) -> None:
        while True:
            sid, text = await self._q.get()
            self._current = asyncio.create_task(self._speak(sid, text))
            await asyncio.wait({self._current})
            self._current = None

    async def _speak(self, sid: str, text: str) -> None:
        rate = self.speech.sample_rate
        try:
            async for pcm in self.speech.synthesize(text):
                await self.send(
                    {
                        "type": "audio",
                        "format": "pcm16",
                        "sampleRate": rate,
                        "data": base64.b64encode(pcm).decode("ascii"),
                        "id": sid,
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("speech synthesis failed")
            await self.on_failed(sid)
