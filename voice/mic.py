"""Speakerphone capture: 16 kHz mono float32 frames of 512 samples (32 ms)."""

import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from voice.vad import FRAME, RATE


def find_input_device(name: str) -> int | None:
    """Index of the first input device whose name contains `name`; None means the default."""
    if not name:
        return None
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
            return index
    raise LookupError(f"No input device matching {name!r}")


class Microphone:
    def __init__(self, device_name: str) -> None:
        self.device_name = device_name
        self.on_frame: Callable[[np.ndarray], None] = lambda frame: None
        self.muted = True
        self.last_frame_at = 0.0
        self._stream: sd.InputStream | None = None

    def open(self) -> None:
        self.close()
        self._stream = sd.InputStream(
            device=find_input_device(self.device_name),
            channels=1,
            samplerate=RATE,
            blocksize=FRAME,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self.last_frame_at = time.monotonic()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        self.last_frame_at = time.monotonic()
        if not self.muted:
            self.on_frame(indata[:, 0].copy())
