"""Camera sources. Frames are returned in memory and never saved."""

import logging
from collections.abc import Callable
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class Camera(Protocol):
    def capture(self) -> np.ndarray: ...
    def close(self) -> None: ...


class PiCamera:
    """Pi Camera Module v2 via picamera2 (apt package python3-picamera2)."""

    def __init__(self) -> None:
        from picamera2 import Picamera2

        self.cam = Picamera2()
        config = self.cam.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameRate": 15},
            buffer_count=2,
        )
        self.cam.configure(config)
        self.cam.start()

    def capture(self) -> np.ndarray:
        frame = self.cam.capture_array("main")  # "RGB888" is stored B, G, R
        return np.ascontiguousarray(frame[::2, ::2, ::-1])

    def close(self) -> None:
        self.cam.stop()
        self.cam.close()


class WebcamCamera:
    """Laptop webcam for development (needs opencv-python-headless in the dev group)."""

    def __init__(self, index: int = 0) -> None:
        import cv2

        self._cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise OSError(f"webcam {index} not available")

    def capture(self) -> np.ndarray:
        ok, frame = self.cap.read()
        if not ok:
            raise OSError("webcam read failed")
        small = self._cv2.resize(frame, (320, 240), interpolation=self._cv2.INTER_AREA)
        return np.ascontiguousarray(small[:, :, ::-1])

    def close(self) -> None:
        self.cap.release()


def with_fallback(primary: Callable[[], Camera], fallback: Callable[[], Camera]):
    """Open the primary camera; if it is unavailable use the fallback (dev only)."""

    def open_camera() -> Camera:
        try:
            return primary()
        except Exception as e:
            log.info("primary camera unavailable (%s); trying the webcam", e)
            return fallback()

    return open_camera
