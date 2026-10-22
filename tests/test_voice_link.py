import asyncio

import zmq.asyncio

from core.answer import CannedAnswerer
from core.bus import Publisher
from core.controller.machine import Controller, ControllerConfig
from core.runtime import Runtime
from core.speech import FakeSpeech
from core.voice_link import VoiceLink


async def noop(msg):
    pass


def test_service_mode_bridges_bus_to_runtime():
    async def go():
        ctx = zmq.asyncio.Context()
        voice_pub = Publisher(ctx, "inproc://voice")
        core_pub = Publisher(ctx, "inproc://core")
        rt = Runtime(
            Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0), noop, dev=True
        )
        link = VoiceLink(rt, ctx, "inproc://voice", core_pub)
        rt.start()
        link.start()
        await rt.on_ui({"type": "dev", "action": "approach"})
        await rt.on_ui({"type": "speech.ended", "id": rt.c.pending[-1]})
        for _ in range(200):
            await voice_pub.publish("stt.final", {"text": "What is IIT?"})
            await asyncio.sleep(0.01)
            if rt.c.state != "listening":
                break
        state = rt.c.state
        await link.stop()
        await rt.stop()
        voice_pub.close()
        core_pub.close()
        ctx.term()
        return state

    assert asyncio.run(go()) in ("thinking", "speaking")
