import json
import sys
from pathlib import Path

import numpy as np
import pytest

from tools import bench_vision

NCNN = Path("models/yolo/ncnn/model.ncnn.param")


class Clock:
    """Fake monotonic clock that the fake detector advances."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Camera:
    def capture(self):
        return np.zeros((240, 320, 3), np.uint8)

    def close(self):
        pass


def test_run_reports_fps_latency_and_no_freezes():
    clock = Clock()

    class Detector:
        def detect(self, frame):
            clock.t += 0.25  # every frame takes 250 ms (exact in binary, so no rounding drift)

    out = bench_vision.run(Detector(), Camera(), seconds=5, clock=clock, perf=clock)
    assert out["frames"] == 20
    assert out["median_ms"] == 250.0
    assert out["max_fps"] == 4.0
    assert out["freezes_over_2s"] == 0


def test_run_counts_a_stall_longer_than_two_seconds_as_a_freeze():
    clock = Clock()
    calls = {"n": 0}

    class Detector:
        def detect(self, frame):
            calls["n"] += 1
            clock.t += 3.0 if calls["n"] == 5 else 0.25  # the fifth frame hangs for 3 s

    out = bench_vision.run(Detector(), Camera(), seconds=10, clock=clock, perf=clock)
    assert out["freezes_over_2s"] == 1
    assert out["max_ms"] == 3000.0  # p99 would hide a single stall; the maximum does not


def test_run_with_zero_seconds_returns_an_empty_summary_not_a_crash():
    out = bench_vision.run(object(), Camera(), seconds=0, clock=Clock(), perf=Clock())
    assert out["frames"] == 0 and out["max_fps"] == 0.0


@pytest.mark.skipif(not NCNN.exists(), reason="run tools.export_yolo first")
def test_synthetic_camera_benchmark_runs_the_real_ncnn_model(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["bench_vision", "--backend", "ncnn", "--camera", "synthetic", "--seconds", "1"],
    )
    bench_vision.main()
    row = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert row["backend"] == "ncnn" and row["frames"] > 0 and row["max_fps"] > 0
