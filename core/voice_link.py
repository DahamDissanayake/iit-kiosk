"""Service mode: kiosk-voice runs separately and talks to kiosk-core over ZeroMQ."""

import asyncio
import logging

import zmq.asyncio

from core.bus import Publisher, Subscriber
from core.runtime import Runtime

log = logging.getLogger("kiosk.voice_link")


class VoiceLink:
    def __init__(
        self,
        runtime: Runtime,
        ctx: zmq.asyncio.Context,
        voice_endpoint: str,
        core_pub: Publisher,
    ) -> None:
        self.rt = runtime
        self.core_pub = core_pub
        self.sub = Subscriber(
            ctx, [voice_endpoint], ["vad.start", "stt.partial", "stt.final", "mic.status"]
        )
        self._task: asyncio.Task | None = None
        runtime.mic_listeners.append(self._on_mute)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self.sub.close()

    def _on_mute(self, muted: bool) -> None:
        asyncio.get_running_loop().create_task(self.core_pub.publish("mic.mute", {"muted": muted}))

    async def _loop(self) -> None:
        while True:
            topic, payload = await self.sub.recv()
            try:
                if topic == "vad.start":
                    await self.rt.speech_started()
                elif topic == "stt.partial":
                    await self.rt.partial(payload["text"])
                elif topic == "stt.final":
                    await self.rt.final(payload["text"])
                elif topic == "mic.status":
                    await self.rt.mic_status(bool(payload["ok"]))
            except Exception:
                log.exception("bad voice message %s", topic)
