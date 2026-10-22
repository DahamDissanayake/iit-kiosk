"""kiosk-vision main loop: capture, detect, track, publish presence (the heartbeat)."""

import asyncio
import dataclasses
import logging
import time
from collections.abc import Callable

from core.sdnotify import notify
from vision.camera import Camera
from vision.detect import Detector
from vision.presence import ZoneConfig, presence
from vision.track import IouTracker

log = logging.getLogger("kiosk.vision")


class VisionService:
    def __init__(
        self,
        camera_factory: Callable[[], Camera],
        detector: Detector,
        tracker: IouTracker,
        zone: ZoneConfig,
        pub,
        fps: float = 8.0,
        preview_hz: float = 4.0,
        retry_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.camera_factory = camera_factory
        self.detector = detector
        self.tracker = tracker
        self.zone = zone
        self.pub = pub
        self.fps = fps
        self.preview_hz = preview_hz
        self.retry_s = retry_s
        self.clock = clock
        self._camera_ok: bool | None = None

    async def _set_camera(self, ok: bool) -> None:
        if ok != self._camera_ok:
            self._camera_ok = ok
            await self.pub.publish("camera", {"ok": ok})

    async def run(self) -> None:
        camera: Camera | None = None
        last_try = -1e9
        last_preview = -1e9
        while True:
            start = self.clock()
            notify("WATCHDOG=1")
            if camera is None:
                if start - last_try < self.retry_s:
                    await asyncio.sleep(min(0.5, self.retry_s))
                    continue
                last_try = start
                try:
                    camera = await asyncio.to_thread(self.camera_factory)
                    await self._set_camera(True)
                except Exception as e:
                    log.warning("camera unavailable: %s", e)
                    await self._set_camera(False)
                    continue
            try:
                frame = await asyncio.to_thread(camera.capture)
            except Exception as e:
                log.warning("camera failed: %s", e)
                await asyncio.to_thread(camera.close)
                camera = None
                last_try = start
                await self._set_camera(False)
                continue
            h, w = frame.shape[:2]
            boxes = await asyncio.to_thread(self.detector.detect, frame)
            del frame  # never kept beyond detection
            tracks = self.tracker.update(boxes, start)
            await self.pub.publish("presence", presence(tracks, w, h, self.zone, start))
            if start - last_preview >= 1 / self.preview_hz:
                last_preview = start
                await self.pub.publish(
                    "vision.preview",
                    {
                        "w": w,
                        "h": h,
                        "boxes": [
                            [round(b.x1), round(b.y1), round(b.x2), round(b.y2), round(b.score, 2)]
                            for b in boxes
                        ],
                        "zone": dataclasses.asdict(self.zone),
                    },
                )
            await asyncio.sleep(max(0.0, 1 / self.fps - (self.clock() - start)))

    async def control(self, sub) -> None:
        fields = {f.name for f in dataclasses.fields(ZoneConfig)}
        while True:
            topic, payload = await sub.recv()
            if topic == "vision.rate":
                self.fps = max(0.5, float(payload["fps"]))
            elif topic == "vision.config":
                changes = {k: v for k, v in payload.items() if k in fields}
                self.zone = dataclasses.replace(self.zone, **changes)
