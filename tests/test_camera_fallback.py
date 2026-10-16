import pytest

from vision.camera import with_fallback


class Cam:
    def __init__(self, name):
        self.name = name

    def capture(self):
        return self.name

    def close(self):
        pass


def test_uses_primary_when_it_opens():
    factory = with_fallback(lambda: Cam("pi"), lambda: Cam("webcam"))
    assert factory().name == "pi"


def test_falls_back_when_primary_missing():
    def pi():
        raise ImportError("picamera2")

    assert with_fallback(pi, lambda: Cam("webcam"))().name == "webcam"


def test_raises_fallback_error_when_both_fail():
    def pi():
        raise OSError("no pi")

    def web():
        raise OSError("no webcam")

    with pytest.raises(OSError, match="no webcam"):
        with_fallback(pi, web)()
