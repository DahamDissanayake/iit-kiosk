import json
import sys
from pathlib import Path

import pytest

from core.config import load_config
from tools import bench

VAD = Path("models/silero_vad.onnx")


def test_emit_prints_one_json_object_per_line(capsys):
    bench.emit(test="x", ms=1.5)
    assert json.loads(capsys.readouterr().out) == {"test": "x", "ms": 1.5}


def test_system_readers_return_none_or_numbers_never_raise():
    temp, mem = bench.read_temp(), bench.read_mem_mb()
    assert temp is None or isinstance(temp, float)
    assert mem is None or (len(mem) == 2 and mem[0] >= mem[1] > 0)


def test_system_command_samples_and_stops(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bench", "system", "--seconds", "0", "--every", "1"])
    bench.main()
    assert capsys.readouterr().out == ""  # zero seconds: no samples, no crash


@pytest.mark.skipif(not VAD.exists(), reason="run python -m models.download first")
def test_vad_benchmark_reports_realtime_factor(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bench", "vad"])
    bench.main()
    row = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert row["test"] == "vad" and row["realtime_factor"] > 1  # faster than real time
    assert load_config("config.toml")  # the benchmark reads the same config as the kiosk
