import asyncio

import numpy as np

from vision.detect import Box
from vision.presence import ZoneConfig
from vision.service import VisionService
from vision.track import IouTracker


class FakeCam:
    def __init__(self, fail_after=None):
        self.n = 0
        self.fail_after = fail_after

    def capture(self):
        self.n += 1
        if self.fail_after is not None and self.n > self.fail_after:
            raise OSError("cable pulled")
        return np.zeros((240, 320, 3), np.uint8)

    def close(self):
        pass


class FakeDetector:
    def detect(self, rgb):
        return [Box(140, 100, 180, 240, 0.9)]


class FakePub:
    def __init__(self):
        self.msgs = []

    async def publish(self, topic, payload):
        self.msgs.append((topic, payload))


def run_for(service, seconds):
    async def go():
        task = asyncio.create_task(service.run())
        await asyncio.sleep(seconds)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())


def test_publishes_presence_and_preview_without_pixels():
    pub = FakePub()
    svc = VisionService(
        lambda: FakeCam(), FakeDetector(), IouTracker(), ZoneConfig(mirror=False), pub, fps=50
    )
    run_for(svc, 0.3)
    presence = [p for t, p in pub.msgs if t == "presence"]
    previews = [p for t, p in pub.msgs if t == "vision.preview"]
    assert presence and presence[-1]["count"] == 1
    assert previews and previews[0]["boxes"][0][:4] == [140, 100, 180, 240]
    assert ("camera", {"ok": True}) in pub.msgs
    assert all(not isinstance(v, (bytes, np.ndarray)) for _, p in pub.msgs for v in p.values())


def test_camera_failure_is_reported_and_retried():
    pub = FakePub()
    cams = iter([FakeCam(fail_after=2), FakeCam()])
    svc = VisionService(
        lambda: next(cams), FakeDetector(), IouTracker(), ZoneConfig(), pub, fps=50, retry_s=0.05
    )
    run_for(svc, 0.5)
    camera = [p["ok"] for t, p in pub.msgs if t == "camera"]
    assert camera[:3] == [True, False, True]


def test_rate_and_zone_updates_apply():
    class Sub:
        def __init__(self, items):
            self.items = list(items)

        async def recv(self):
            if self.items:
                return self.items.pop(0)
            await asyncio.sleep(10)

    svc = VisionService(lambda: FakeCam(), FakeDetector(), IouTracker(), ZoneConfig(), FakePub())

    async def go():
        task = asyncio.create_task(
            svc.control(Sub([("vision.rate", {"fps": 2}), ("vision.config", {"centre_band": 0.8})]))
        )
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(go())
    assert svc.fps == 2
    assert svc.zone.centre_band == 0.8
