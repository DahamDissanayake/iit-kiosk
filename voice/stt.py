"""Speech to text on the device (no audio leaves the Pi)."""

from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class MoonshineTranscriber:
    def __init__(self, model_name: str = "moonshine/base") -> None:
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

        self.model = MoonshineOnnxModel(model_name=model_name)
        self.tokenizer = load_tokenizer()

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < 1600:  # under 0.1 s: nothing worth decoding
            return ""
        tokens = self.model.generate(audio[np.newaxis, :].astype(np.float32))
        return self.tokenizer.decode_batch(tokens)[0].strip()


def make_transcriber(voice_cfg: dict) -> Transcriber:
    return MoonshineTranscriber(voice_cfg["stt_model"])
