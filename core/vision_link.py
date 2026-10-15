"""kiosk-core side of kiosk-vision: presence in, frame rate and zone settings out."""

import asyncio
import logging
import time
from collections.abc import Callable

from core.controller.types import CameraStatus, Presence
from core.runtime import Runtime

log = logging.getLogger("kiosk.vision_link")


def to_presence(payload: dict) -> Presence:
    tracks = payload.get("tracks", [])
    if not tracks:
        return Presence(0)
    approaching = [t for t in tracks if t.get("approaching")]
    target = max(approaching or tracks, key=lambda t: t["h"])
    return Presence(len(tracks), bool(approaching), float(target["cx"]), float(target["cy"]))


class VisionLink:
    def __init__(
        self,
        runtime: Runtime,
        sub,
        core_pub,
        heartbeat_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rt = runtime
        self.sub = sub
        self.core_pub = core_pub
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self.last_seen = clock()
        self.preview: dict | None = None
        self.fps = runtime.c.cfg.fps_idle
        self._tasks: list[asyncio.Task] = []
        runtime.vision_listeners.append(self._on_rate)

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._recv_loop()),
            asyncio.create_task(self._watch_loop()),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.sub is not None:
            self.sub.close()  # an open socket would block ZeroMQ context shutdown

    def _on_rate(self, fps: float) -> None:
        self.fps = fps
        asyncio.get_running_loop().create_task(self.core_pub.publish("vision.rate", {"fps": fps}))

    async def publish_config(self, changes: dict) -> None:
        await self.core_pub.publish("vision.config", changes)

    async def on_message(self, topic: str, payload: dict) -> None:
        if topic == "presence":
            self.last_seen = self.clock()
            if not self.rt.c.camera_ok:
                await self.rt.handle(CameraStatus(True))
            await self.rt.handle(to_presence(payload))
        elif topic == "camera" and not payload.get("ok"):
            await self.rt.handle(CameraStatus(False))
        elif topic == "vision.preview":
            self.preview = payload

    async def check_heartbeat(self) -> None:
        if self.rt.c.camera_ok and self.clock() - self.last_seen > self.heartbeat_s:
            log.warning("no presence from kiosk-vision for %.0f s", self.heartbeat_s)
            await self.rt.handle(CameraStatus(False))

    async def _recv_loop(self) -> None:
        while True:
            topic, payload = await self.sub.recv()
            try:
                await self.on_message(topic, payload)
            except Exception:
                log.exception("bad vision message %s", topic)

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self.check_heartbeat()
            # repeat the rate so a restarted kiosk-vision picks it up
            await self.core_pub.publish("vision.rate", {"fps": self.fps})
