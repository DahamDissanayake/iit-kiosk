import asyncio

from core.answer import CannedAnswerer
from core.controller.machine import Controller, ControllerConfig
from core.controller.phrases import MenuItem
from core.runtime import Runtime
from core.speech import FakeSpeech


class Collect:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(msg)


class FailingSpeech:
    sample_rate = 22050

    async def synthesize(self, text):
        raise RuntimeError("tts down")
        yield b""  # makes this an async generator


async def wait_for(pred, seconds=2.0):
    for _ in range(int(seconds / 0.01)):
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def make(speech=None, dev=True):
    sent = Collect()
    rt = Runtime(
        Controller(ControllerConfig()),
        speech or FakeSpeech(),
        CannedAnswerer(delay_s=0),
        sent,
        dev=dev,
    )
    return rt, sent


def test_dev_approach_greets_and_streams_pcm_audio():
    async def go():
        rt, sent = make()
        rt.start()
        await rt.on_ui({"type": "dev", "action": "approach"})
        assert await wait_for(lambda: any(m["type"] == "audio" for m in sent.msgs))
        await rt.stop()
        audio = next(m for m in sent.msgs if m["type"] == "audio")
        assert audio["format"] == "pcm16"
        assert audio["sampleRate"] == 22050
        assert audio["id"] == rt.c.pending[-1]
        assert rt.c.state == "greeting"
        assert rt.mic_muted is True

    asyncio.run(go())


def test_typed_question_gets_canned_spoken_answer():
    async def go():
        rt, sent = make()
        rt.start()
        await rt.on_ui({"type": "dev", "action": "approach"})
        await rt.on_ui({"type": "speech.ended", "id": rt.c.pending[-1]})
        assert rt.c.state == "listening"
        await rt.on_ui({"type": "dev", "action": "ask", "text": "What is IIT?"})
        assert await wait_for(lambda: rt.c.state == "speaking")
        await rt.stop()
        says = [m["text"] for m in sent.msgs if m["type"] == "say"]
        assert says[-1].startswith("You asked: What is IIT.")

    asyncio.run(go())


def test_internet_failure_switches_to_menu():
    async def go():
        rt, sent = make()
        rt.start()
        await rt.on_ui({"type": "dev", "action": "internet", "ok": False})
        await rt.on_ui({"type": "dev", "action": "approach"})
        await rt.on_ui({"type": "speech.ended", "id": rt.c.pending[-1]})
        await rt.on_ui({"type": "dev", "action": "ask", "text": "What is IIT?"})
        assert await wait_for(lambda: any(m["type"] == "menu" for m in sent.msgs))
        await rt.stop()

    asyncio.run(go())


def test_tts_failure_does_not_stall_conversation():
    async def go():
        rt, _ = make(speech=FailingSpeech())
        rt.start()
        await rt.on_ui({"type": "dev", "action": "approach"})
        assert await wait_for(lambda: rt.c.state == "listening")
        await rt.stop()

    asyncio.run(go())


def test_dev_actions_are_ignored_outside_dev_mode():
    async def go():
        rt, _ = make(dev=False)
        await rt.on_ui({"type": "dev", "action": "approach"})
        assert rt.c.state == "idle"

    asyncio.run(go())


def test_snapshot_ends_with_current_state():
    rt, _ = make()
    snap = rt.snapshot()
    assert snap[-1] == {"type": "state", "state": "idle"}
    assert {"type": "dev", "enabled": True} in snap
    assert {"type": "camera", "ok": True} in snap


def test_runtime_loads_menu_from_source_on_start():
    async def go():
        sent = Collect()
        items = [MenuItem("1", "Label", "Answer")]
        rt = Runtime(
            Controller(ControllerConfig()),
            FakeSpeech(),
            CannedAnswerer(delay_s=0),
            sent,
            menu_source=lambda: items,
        )
        rt.start()
        assert rt.c.menu == tuple(items)
        await rt.stop()

    asyncio.run(go())
