from pathlib import Path

import numpy as np
import pytest

from vision.detect import Box, decode, letterbox, nms


def output_with(*columns, n=20):
    """YOLO11 output (84, n): rows 0-3 are cx, cy, w, h; row 4 is 'person'."""
    out = np.zeros((84, n), np.float32)
    for i, (cx, cy, w, h, person, other) in enumerate(columns):
        out[:4, i] = (cx, cy, w, h)
        out[4, i] = person
        out[5, i] = other
    return out


def test_letterbox_pads_320x240_to_square():
    rgb = np.full((240, 320, 3), 200, np.uint8)
    chw, scale, pad_x, pad_y = letterbox(rgb)
    assert chw.shape == (3, 320, 320)
    assert (scale, pad_x, pad_y) == (1.0, 0, 40)
    assert chw[0, 0, 0] == pytest.approx(114 / 255)
    assert chw[0, 100, 100] == pytest.approx(200 / 255)


def test_letterbox_downscales_larger_frames():
    chw, scale, pad_x, pad_y = letterbox(np.zeros((480, 640, 3), np.uint8))
    assert chw.shape == (3, 320, 320)
    assert (scale, pad_x, pad_y) == (0.5, 0, 40)


def test_decode_keeps_people_maps_back_and_suppresses_overlaps():
    out = output_with(
        (160, 160, 40, 120, 0.9, 0.0),  # person
        (162, 161, 40, 118, 0.8, 0.0),  # same person, lower score
        (60, 100, 30, 30, 0.1, 0.95),  # a car
    )
    boxes = decode(out, scale=1.0, pad_x=0, pad_y=40)
    assert boxes == [Box(140.0, 60.0, 180.0, 180.0, pytest.approx(0.9))]


def test_decode_accepts_batched_output():
    out = output_with((160, 160, 40, 120, 0.9, 0.0))[None]
    assert len(decode(out, 1.0, 0, 40)) == 1


def test_decode_ignores_invalid_boxes():
    out = output_with((np.nan, 160, 40, 120, 0.9, 0), (160, 160, -5, 120, 0.9, 0))
    assert decode(out, 1.0, 0, 40) == []


def test_nms_keeps_highest_of_overlapping():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
    assert nms(boxes, np.array([0.5, 0.9, 0.7]), 0.5) == [1, 2]


NCNN = Path("models/yolo/ncnn/model.ncnn.param")


@pytest.mark.skipif(not NCNN.exists(), reason="run tools.export_yolo first")
def test_ncnn_detector_runs_on_a_blank_frame():
    from vision.detect import NcnnDetector

    assert NcnnDetector(NCNN.parent).detect(np.zeros((240, 320, 3), np.uint8)) == []
