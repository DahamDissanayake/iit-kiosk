"""16 kHz mono WAV helpers for tests, benchmarks and replay. Never used on visitor audio."""

import wave
from pathlib import Path

import numpy as np

RATE = 16000


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != RATE:
            raise ValueError(f"{path}: need {RATE} Hz, got {w.getframerate()}")
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: need 16-bit PCM")
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        channels = w.getnchannels()
    audio = raw.reshape(-1, channels).mean(axis=1) if channels > 1 else raw
    return (audio / 32768.0).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def mix_at_snr(clean: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Loop or trim noise to the clean length and scale it to the requested SNR."""
    reps = int(np.ceil(len(clean) / len(noise)))
    noise = np.tile(noise, reps)[: len(clean)]
    clean_power = np.mean(clean**2)
    noise_power = np.mean(noise**2) or 1e-12
    scale = np.sqrt(clean_power / (noise_power * 10 ** (snr_db / 10)))
    return (clean + noise * scale).astype(np.float32)
