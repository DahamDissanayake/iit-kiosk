"""Generate synthetic test clips with the local Piper voice (no microphone needed).

    uv run python -m tools.make_test_clips                       # the default clips
    uv run python -m tools.make_test_clips q01 "Where is the campus?" q02 "Is there parking?"

Writes 16 kHz mono 16-bit WAV files into tests/audio/ with 0.3 s of silence either side.
These are synthetic voices for tests and the replay benchmark; never visitor audio.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from core.config import load_config
from core.paths import models_dir
from voice.wav import RATE, write_wav

DEFAULT_CLIPS = {
    "what-courses": "What courses does IIT offer?",
    "hello": "Hello",
}
OUT = Path("tests/audio")
PAD = np.zeros(int(0.3 * RATE), np.float32)


def synthesize(voice, text: str) -> np.ndarray:
    """Piper speech for `text` as float32 mono at 16 kHz, padded with silence."""
    chunks = list(voice.synthesize(text))
    audio = np.concatenate([np.frombuffer(c.audio_int16_bytes, "<i2") for c in chunks])
    audio = audio.astype(np.float32) / 32768
    n = int(len(audio) * RATE / chunks[0].sample_rate)
    resampled = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return np.concatenate([PAD, resampled.astype(np.float32), PAD])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.make_test_clips")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("pairs", nargs="*", help="NAME TEXT pairs; default clips when omitted")
    args = parser.parse_args(argv)
    if len(args.pairs) % 2:
        print("give NAME TEXT pairs", file=sys.stderr)
        return 2
    clips = dict(zip(args.pairs[::2], args.pairs[1::2], strict=True)) or DEFAULT_CLIPS

    from piper import PiperVoice

    cfg = load_config(args.config)
    model = models_dir(cfg) / "piper" / f"{cfg['voice']['tts_voice']}.onnx"
    if not model.exists():
        print(f"Piper voice missing: {model} (run python -m models.download)", file=sys.stderr)
        return 1
    voice = PiperVoice.load(str(model))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in clips.items():
        audio = synthesize(voice, text)
        write_wav(OUT / f"{name}.wav", audio)
        print(f"{OUT / name}.wav  {len(audio) / RATE:.2f}s  {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
