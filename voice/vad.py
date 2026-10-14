"""Voice activity: Silero VAD v5 scores 32 ms frames; Segmenter turns scores into utterances."""

from collections import deque
from pathlib import Path

import numpy as np
import onnxruntime as ort

RATE = 16000
FRAME = 512
CONTEXT = 64  # Silero v5 expects the previous 64 samples in front of each frame


class SileroVad:
    def __init__(self, model_path: Path) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.sr = np.array(RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        out, self.state = self.sess.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -CONTEXT:]
        return float(out[0][0])


class Segmenter:
    """Speech starts after `start_frames` voiced frames and ends after `end_silence_frames`
    quiet ones (with hysteresis), or at `max_frames`. Pre-roll keeps the first syllable."""

    def __init__(
        self,
        threshold: float = 0.5,
        start_frames: int = 3,
        end_silence_frames: int = 22,
        max_frames: int = 470,
        pre_roll: int = 8,
    ) -> None:
        self.threshold = threshold
        self.start_frames = start_frames
        self.end_silence_frames = end_silence_frames
        self.max_frames = max_frames
        self.pre_roll = pre_roll
        self.reset()

    def reset(self) -> None:
        self.active = False
        self._voiced = 0
        self._silent = 0
        self._buf: list[np.ndarray] = []
        self._pre: deque[np.ndarray] = deque(maxlen=self.pre_roll)

    def current_audio(self) -> np.ndarray:
        return np.concatenate(self._buf) if self._buf else np.zeros(0, np.float32)

    def push(self, frame: np.ndarray, prob: float) -> None | str | tuple[str, np.ndarray]:
        if not self.active:
            self._pre.append(frame)
            self._voiced = self._voiced + 1 if prob >= self.threshold else 0
            if self._voiced >= self.start_frames:
                self.active = True
                self._buf = list(self._pre)
                self._silent = 0
                return "start"
            return None
        self._buf.append(frame)
        quiet = prob < self.threshold - 0.15
        self._silent = self._silent + 1 if quiet else 0
        if self._silent >= self.end_silence_frames or len(self._buf) >= self.max_frames:
            audio = self.current_audio()
            self.reset()
            return ("end", audio)
        return None
