import asyncio

from core.answer import CannedAnswerer
from core.controller.machine import Controller, ControllerConfig
from core.controller.types import Tick
from core.runtime import Runtime
from core.speech import FakeSpeech
from core.vision_link import VisionLink, to_presence


class FakePub:
    def __init__(self):
        self.msgs = []

    async def publish(self, topic, payload):
        self.msgs.append((topic, payload))


async def noop(msg):
    pass


def make():
    now = [0.0]
    rt = Runtime(
        Controller(ControllerConfig()),
        FakeSpeech(),
        CannedAnswerer(delay_s=0),
        noop,
        clock=lambda: now[0],
    )
    link = VisionLink(rt, sub=None, core_pub=FakePub(), heartbeat_s=5.0, clock=lambda: now[0])
    return rt, link, now


def msg(*tracks):
    return {"ts": 0, "count": len(tracks), "tracks": list(tracks)}


def tr(tid, cx, h, approaching=False):
    return {"id": tid, "cx": cx, "cy": -0.5, "h": h, "approaching": approaching}


def test_target_prefers_the_approaching_track():
    p = to_presence(msg(tr(1, -0.4, 0.6), tr(2, 0.3, 0.3, approaching=True)))
    assert (p.count, p.approaching, p.cx) == (2, True, 0.3)


def test_largest_track_is_target_when_nobody_approaches():
    p = to_presence(msg(tr(1, -0.4, 0.3), tr(2, 0.3, 0.6)))
    assert (p.approaching, p.cx) == (False, 0.3)


def test_empty_zone():
    p = to_presence(msg())
    assert (p.count, p.approaching) == (0, False)


def test_presence_messages_drive_the_controller():
    async def go():
        rt, link, now = make()
        now[0] = 1.0
        await link.on_message("presence", msg(tr(1, 0.0, 0.5, approaching=True)))
        return rt.c.state

    assert asyncio.run(go()) == "greeting"


def test_heartbeat_loss_reports_camera_down_without_walkaway():
    async def go():
        rt, link, now = make()
        now[0] = 1.0
        await link.on_message("presence", msg(tr(1, 0.0, 0.5, approaching=True)))
        await rt.on_ui({"type": "speech.ended", "id": rt.c.pending[-1]})
        assert rt.c.state == "listening"
        now[0] = 6.5
        await link.check_heartbeat()
        assert rt.c.camera_ok is False
        await rt.handle(Tick())
        state_after = rt.c.state
        now[0] = 7.0
        await link.on_message("presence", msg(tr(1, 0.0, 0.5)))
        return state_after, rt.c.camera_ok

    assert asyncio.run(go()) == ("listening", True)


def test_engaged_rate_is_published_to_vision():
    async def go():
        rt, link, now = make()
        now[0] = 1.0
        await link.on_message("presence", msg(tr(1, 0.0, 0.5, approaching=True)))
        await asyncio.sleep(0)
        return link.core_pub.msgs

    assert ("vision.rate", {"fps": 2.0}) in asyncio.run(go())


def test_preview_is_kept_for_the_dashboard():
    async def go():
        _, link, _ = make()
        await link.on_message("vision.preview", {"w": 320, "h": 240, "boxes": []})
        return link.preview

    assert asyncio.run(go())["w"] == 320


def test_stop_closes_the_subscriber_so_zeromq_can_shut_down():
    class Sub:
        closed = False

        async def recv(self):
            await asyncio.sleep(60)

        def close(self):
            self.closed = True

    async def go():
        rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0), noop)
        sub = Sub()
        link = VisionLink(rt, sub=sub, core_pub=FakePub())
        link.start()
        await asyncio.sleep(0)
        await link.stop()
        return sub.closed

    assert asyncio.run(go()) is True


def test_zone_settings_are_republished_to_vision_every_second():
    async def go():
        rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0), noop)
        pub = FakePub()
        link = VisionLink(rt, sub=None, core_pub=pub, zone_source=lambda: {"centre_band": 0.7})
        task = asyncio.create_task(link._watch_loop())
        await asyncio.sleep(1.3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return pub.msgs

    assert ("vision.config", {"centre_band": 0.7}) in asyncio.run(go())


def test_dev_presence_overrides_camera_for_a_while():
    async def go():
        now = [0.0]
        rt = Runtime(
            Controller(ControllerConfig()),
            FakeSpeech(),
            CannedAnswerer(delay_s=0),
            noop,
            dev=True,
            clock=lambda: now[0],
        )
        link = VisionLink(rt, sub=None, core_pub=FakePub(), clock=lambda: now[0])
        now[0] = 1.0
        await rt.on_ui({"type": "dev", "action": "approach"})
        await link.on_message("presence", msg())  # real camera sees nobody
        now[0] = 5.0
        await rt.handle(Tick())
        held = rt.c.state
        now[0] = 31.5
        await link.on_message("presence", msg())  # override expired
        now[0] = 35.0
        await rt.handle(Tick())
        return held, rt.c.state

    held, later = asyncio.run(go())
    assert held == "greeting"
    assert later == "farewell"
