"""Day-one detector benchmark on the Pi: fps, latency and freezes (baseline 11.4).

    uv run python -m tools.bench_vision --backend ncnn --minutes 30
    uv run python -m tools.bench_vision --backend openvino --minutes 30
    uv run python -m tools.bench_vision --backend ncnn --camera synthetic --seconds 5   # no camera

Prints one JSON object. Frames are used in memory only; nothing is written to disk.
"""

import argparse
import json
import statistics
import time
from collections.abc import Callable

import numpy as np

from core.config import load_config
from core.paths import models_dir
from tools.bench import read_temp
from vision.detect import make_detector


class SyntheticCamera:
    """Blank 320x240 frames, so the detector speed can be measured without a camera."""

    def capture(self) -> np.ndarray:
        return np.full((240, 320, 3), 128, np.uint8)

    def close(self) -> None:
        pass


def run(
    detector,
    camera,
    seconds: float,
    clock: Callable[[], float] = time.monotonic,
    perf: Callable[[], float] = time.perf_counter,
) -> dict:
    """Capture and detect for `seconds`. A gap of over 2 s between frames counts as a freeze."""
    times: list[float] = []
    freezes = 0
    max_temp = 0.0
    end = clock() + seconds
    last = clock()
    while clock() < end:
        frame = camera.capture()
        t0 = perf()
        detector.detect(frame)
        times.append(perf() - t0)
        now = clock()
        if now - last > 2.0:
            freezes += 1
        last = now
        max_temp = max(max_temp, read_temp() or 0.0)
    if not times:
        return {
            "frames": 0,
            "median_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "max_fps": 0.0,
            "freezes_over_2s": 0,
            "max_temp_c": max_temp,
        }
    median = statistics.median(times)
    return {
        "frames": len(times),
        "median_ms": round(median * 1000, 1),
        "p99_ms": round(sorted(times)[int(len(times) * 0.99)] * 1000, 1),
        "max_ms": round(max(times) * 1000, 1),  # p99 hides a single stall; the maximum shows it
        "max_fps": round(1 / median, 1) if median else 0.0,
        "freezes_over_2s": freezes,
        "max_temp_c": max_temp,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.bench_vision")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--backend", choices=["ncnn", "openvino"], required=True)
    parser.add_argument("--camera", choices=["pi", "synthetic"], default="pi")
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--seconds", type=float, default=None, help="overrides --minutes")
    args = parser.parse_args()
    cfg = load_config(args.config)
    detector = make_detector({**cfg["vision"], "backend": args.backend}, models_dir(cfg))
    if args.camera == "pi":
        from vision.camera import PiCamera

        camera = PiCamera()
    else:
        camera = SyntheticCamera()
    seconds = args.seconds if args.seconds is not None else args.minutes * 60
    try:
        result = run(detector, camera, seconds)
    finally:
        camera.close()
    print(json.dumps({"backend": args.backend, "camera": args.camera, **result}))


if __name__ == "__main__":
    main()
