"""Benchmarks for the bench Pi (baseline 11.4). Prints one JSON object per result.

uv run python -m tools.bench embed
uv run python -m tools.bench stt tests/audio/what-courses.wav
uv run python -m tools.bench vad
uv run python -m tools.bench system --seconds 600 --every 5 > system.jsonl
"""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np

from core.config import load_config
from core.paths import models_dir


def emit(**values) -> None:
    print(json.dumps(values), flush=True)


def bench_embed(cfg: dict) -> None:
    from core.rag.embed import FastEmbedder

    t0 = time.perf_counter()
    e = FastEmbedder(cfg["rag"]["embed_model"], cache_dir=models_dir(cfg) / "fastembed")
    emit(test="embed.load", seconds=round(time.perf_counter() - t0, 3))
    passages = [
        f"IIT offers programme number {i} in computing and business." * 8 for i in range(50)
    ]
    t0 = time.perf_counter()
    e.passages(passages)
    emit(test="embed.passages", n=50, seconds=round(time.perf_counter() - t0, 3))
    times = []
    for i in range(20):
        t0 = time.perf_counter()
        e.query(f"What programmes does IIT offer {i}?")
        times.append(time.perf_counter() - t0)
    emit(test="embed.query", median_ms=round(statistics.median(times) * 1000, 1))


def bench_stt(cfg: dict, wav: Path) -> None:
    from voice.stt import make_transcriber
    from voice.wav import read_wav

    audio = read_wav(wav)
    stt = make_transcriber(cfg["voice"])
    stt.transcribe(audio)  # warm up
    times, text = [], ""
    for _ in range(5):
        t0 = time.perf_counter()
        text = stt.transcribe(audio)
        times.append(time.perf_counter() - t0)
    emit(
        test="stt",
        model=cfg["voice"]["stt_model"],
        audio_s=round(len(audio) / 16000, 2),
        median_ms=round(statistics.median(times) * 1000),
        text=text,
    )


def bench_vad(cfg: dict) -> None:
    from voice.vad import FRAME, SileroVad

    vad = SileroVad(models_dir(cfg) / "silero_vad.onnx")
    frame = np.zeros(FRAME, np.float32)
    t0 = time.perf_counter()
    for _ in range(500):
        vad.prob(frame)
    per = (time.perf_counter() - t0) / 500
    emit(test="vad", ms_per_frame=round(per * 1000, 3), realtime_factor=round(0.032 / per, 1))


def read_temp() -> float | None:
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    return int(path.read_text()) / 1000 if path.exists() else None


def read_mem_mb() -> tuple[int, int] | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    info = dict(line.split(":", 1) for line in path.read_text().splitlines())
    total = int(info["MemTotal"].split()[0]) // 1024
    avail = int(info["MemAvailable"].split()[0]) // 1024
    return total, avail


def bench_system(seconds: int, every: int) -> None:
    end = time.time() + seconds
    while time.time() < end:
        mem = read_mem_mb()
        emit(
            test="system",
            ts=round(time.time()),
            temp_c=read_temp(),
            load1=os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
            mem_used_mb=(mem[0] - mem[1]) if mem else None,
        )
        time.sleep(every)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.bench")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("embed")
    sub.add_parser("vad")
    stt = sub.add_parser("stt")
    stt.add_argument("wav", type=Path)
    system = sub.add_parser("system")
    system.add_argument("--seconds", type=int, default=600)
    system.add_argument("--every", type=int, default=5)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.cmd == "embed":
        bench_embed(cfg)
    elif args.cmd == "stt":
        bench_stt(cfg, args.wav)
    elif args.cmd == "vad":
        bench_vad(cfg)
    else:
        bench_system(args.seconds, args.every)


if __name__ == "__main__":
    main()
