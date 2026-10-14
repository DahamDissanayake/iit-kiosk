"""kiosk-vision: `uv run python -m vision` (Pi camera) or `--webcam 0` (laptop)."""

import argparse
import asyncio
import logging

import zmq.asyncio

from core.bus import Publisher, Subscriber, use_selector_loop_on_windows
from core.config import load_config
from core.paths import models_dir
from core.sdnotify import notify
from vision.detect import make_detector
from vision.presence import ZoneConfig
from vision.service import VisionService
from vision.track import IouTracker


async def serve(cfg: dict, webcam: int | None) -> None:
    v = cfg["vision"]
    if webcam is None:
        from vision.camera import PiCamera as factory
    else:
        from vision.camera import WebcamCamera

        def factory():
            return WebcamCamera(webcam)

    ctx = zmq.asyncio.Context()
    service = VisionService(
        factory,
        make_detector(v, models_dir(cfg)),
        IouTracker(),
        ZoneConfig.from_config(v),
        Publisher(ctx, cfg["bus"]["vision_pub"]),
        fps=v["fps_idle"],
        preview_hz=v["preview_hz"],
    )
    sub = Subscriber(ctx, [cfg["bus"]["core_pub"]], ["vision.rate", "vision.config"])
    notify("READY=1")
    await asyncio.gather(service.run(), service.control(sub))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m vision")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--webcam", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    use_selector_loop_on_windows()
    asyncio.run(serve(load_config(args.config), args.webcam))


if __name__ == "__main__":
    main()
