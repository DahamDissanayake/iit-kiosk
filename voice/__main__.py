"""kiosk-voice: mic, VAD and STT as a separate service (used when [voice] mode = "service")."""

import argparse
import asyncio
import logging
import time

import zmq.asyncio

from core.bus import Publisher, Subscriber, use_selector_loop_on_windows
from core.config import load_config
from core.paths import models_dir
from voice.mic import Microphone
from voice.pipeline import VoicePipeline
from voice.stt import make_transcriber
from voice.vad import FRAME, RATE, Segmenter, SileroVad


class BusSink:
    def __init__(self, pub: Publisher) -> None:
        self.pub = pub

    async def speech_started(self) -> None:
        await self.pub.publish("vad.start", {"ts": time.time()})

    async def partial(self, text: str) -> None:
        await self.pub.publish("stt.partial", {"text": text})

    async def final(self, text: str) -> None:
        await self.pub.publish("vad.end", {"ts": time.time()})
        await self.pub.publish("stt.final", {"text": text})

    async def mic_status(self, ok: bool) -> None:
        await self.pub.publish("mic.status", {"ok": ok})


def build_pipeline(cfg: dict, sink, loop, mic_device: str | None = None) -> VoicePipeline:
    v = cfg["voice"]
    frame_ms = FRAME * 1000 / RATE
    return VoicePipeline(
        Microphone(v["mic_device"] if mic_device is None else mic_device),
        SileroVad(models_dir(cfg) / "silero_vad.onnx"),
        Segmenter(
            threshold=v["vad_threshold"], end_silence_frames=round(v["end_silence_ms"] / frame_ms)
        ),
        make_transcriber(v),
        sink,
        loop,
        partial_every_s=v["partial_every_s"],
    )


async def serve(cfg: dict) -> None:
    ctx = zmq.asyncio.Context()
    pub = Publisher(ctx, cfg["bus"]["voice_pub"])
    sub = Subscriber(ctx, [cfg["bus"]["core_pub"]], ["mic.mute"])
    pipeline = build_pipeline(cfg, BusSink(pub), asyncio.get_running_loop())
    pipeline.start()
    try:
        while True:
            _, payload = await sub.recv()
            pipeline.set_muted(bool(payload["muted"]))
    finally:
        pipeline.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m voice")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    use_selector_loop_on_windows()
    asyncio.run(serve(load_config(args.config)))


if __name__ == "__main__":
    main()
