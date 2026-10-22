import asyncio
import time

import numpy as np

from voice.pipeline import VoicePipeline
from voice.vad import FRAME, Segmenter


class FakeMic:
    def __init__(self):
        self.on_frame = None
        self.muted = True
        self.last_frame_at = time.monotonic()
        self.opened = 0
        self.fail = False

    def open(self):
        self.opened += 1
        if self.fail:
            raise OSError("device unplugged")

    def close(self):
        pass


class ScriptedVad:
    """Frames carry their own probability in sample 0."""

    def prob(self, frame):
        return float(frame[0])

    def reset(self):
        pass


class FakeStt:
    def transcribe(self, audio):
        return f"heard {len(audio) // FRAME} frames"


class Sink:
    def __init__(self):
        self.events = []

    async def speech_started(self):
        self.events.append(("start",))

    async def partial(self, text):
        self.events.append(("partial", text))

    async def final(self, text):
        self.events.append(("final", text))

    async def mic_status(self, ok):
        self.events.append(("mic", ok))


def frame(p):
    f = np.zeros(FRAME, np.float32)
    f[0] = p
    return f


async def until(pred, seconds=2.0):
    for _ in range(int(seconds / 0.01)):
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def make(**kw):
    mic, sink = FakeMic(), Sink()
    seg = Segmenter(start_frames=2, end_silence_frames=3, pre_roll=1)
    pipe = VoicePipeline(
        mic,
        ScriptedVad(),
        seg,
        FakeStt(),
        sink,
        asyncio.get_running_loop(),
        partial_every_s=0,
        **kw,
    )
    return mic, sink, pipe


def test_utterance_produces_start_and_final():
    async def go():
        mic, sink, pipe = make()
        pipe.start()
        pipe.set_muted(False)
        for p in [0.9] * 4 + [0.0] * 3:
            mic.on_frame(frame(p))
        assert await until(lambda: any(e[0] == "final" for e in sink.events))
        pipe.stop()
        voice = [e for e in sink.events if e[0] != "mic"]
        # pre-roll 1 + 3 voiced + 3 silent frames
        assert voice == [("start",), ("final", "heard 6 frames")]

    asyncio.run(go())


def test_frames_while_muted_are_ignored():
    async def go():
        mic, sink, pipe = make()
        pipe.start()
        for p in [0.9] * 6:
            mic.on_frame(frame(p))
        await asyncio.sleep(0.2)
        pipe.stop()
        assert [e for e in sink.events if e[0] != "mic"] == []

    asyncio.run(go())


def test_frames_queued_before_mute_are_dropped():
    async def go():
        mic, sink, pipe = make()
        pipe.set_muted(False)
        for p in [0.9] * 6:
            mic.on_frame(frame(p))
        pipe.set_muted(True)  # bot starts talking before the worker ran
        pipe.start()
        await asyncio.sleep(0.2)
        pipe.stop()
        assert [e for e in sink.events if e[0] != "mic"] == []

    asyncio.run(go())


def test_mic_stall_reports_failure_and_recovery():
    async def go():
        now = [100.0]
        mic, sink, pipe = make(
            stall_s=2.0, clock=lambda: now[0], check_every_s=0.01, reopen_every_s=0.0
        )
        mic.last_frame_at = 100.0
        pipe.start()
        assert await until(lambda: ("mic", True) in sink.events)
        sink.events.clear()
        mic.fail = True
        now[0] = 103.0
        assert await until(lambda: ("mic", False) in sink.events)
        assert mic.opened >= 1
        mic.fail = False
        mic.last_frame_at = 103.0
        assert await until(lambda: ("mic", True) in sink.events)
        pipe.stop()

    asyncio.run(go())
