"""YOLO11n person detection through NCNN or OpenVINO. Frames are never stored."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

SIZE = 320
PAD = 114


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float


class Detector(Protocol):
    def detect(self, rgb: np.ndarray) -> list[Box]: ...


def letterbox(rgb: np.ndarray, size: int = SIZE) -> tuple[np.ndarray, float, int, int]:
    h, w = rgb.shape[:2]
    scale = min(size / w, size / h, 1.0)
    nh, nw = round(h * scale), round(w * scale)
    if scale != 1.0:
        ys = (np.arange(nh) / scale).astype(int)
        xs = (np.arange(nw) / scale).astype(int)
        rgb = rgb[ys][:, xs]
    pad_y, pad_x = (size - nh) // 2, (size - nw) // 2
    canvas = np.full((size, size, 3), PAD, np.uint8)
    canvas[pad_y : pad_y + nh, pad_x : pad_x + nw] = rgb
    chw = np.ascontiguousarray(canvas.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return chw, scale, pad_x, pad_y


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    order = list(np.argsort(-scores))
    keep: list[int] = []
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order:
        i = order.pop(0)
        keep.append(int(i))
        rest = []
        for j in order:
            xx1 = max(boxes[i, 0], boxes[j, 0])
            yy1 = max(boxes[i, 1], boxes[j, 1])
            xx2 = min(boxes[i, 2], boxes[j, 2])
            yy2 = min(boxes[i, 3], boxes[j, 3])
            inter = max(0.0, xx2 - xx1) * max(0.0, yy2 - yy1)
            union = area[i] + area[j] - inter
            if union <= 0 or inter / union < iou:
                rest.append(j)
        order = rest
    return keep


def decode(
    output: np.ndarray,
    scale: float,
    pad_x: int,
    pad_y: int,
    conf: float = 0.4,
    iou: float = 0.5,
) -> list[Box]:
    out = output[0] if output.ndim == 3 else output
    cx, cy, w, h, person = out[0], out[1], out[2], out[3], out[4]
    valid = (
        np.isfinite(cx)
        & np.isfinite(cy)
        & np.isfinite(w)
        & np.isfinite(h)
        & (w > 0)
        & (h > 0)
        & (person >= conf)
    )
    if not valid.any():
        return []
    cx, cy, w, h, score = cx[valid], cy[valid], w[valid], h[valid], person[valid]
    boxes = np.stack(
        [
            (cx - w / 2 - pad_x) / scale,
            (cy - h / 2 - pad_y) / scale,
            (cx + w / 2 - pad_x) / scale,
            (cy + h / 2 - pad_y) / scale,
        ],
        axis=1,
    )
    return [
        Box(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(score[i]))
        for i, b in ((k, boxes[k]) for k in nms(boxes, score, iou))
    ]


class NcnnDetector:
    def __init__(self, model_dir: Path, threads: int = 2, conf: float = 0.4) -> None:
        import ncnn

        self._ncnn = ncnn
        self.conf = conf
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = threads
        self.net.load_param(str(model_dir / "model.ncnn.param"))
        self.net.load_model(str(model_dir / "model.ncnn.bin"))

    def detect(self, rgb: np.ndarray) -> list[Box]:
        chw, scale, pad_x, pad_y = letterbox(rgb)
        ex = self.net.create_extractor()
        ex.input("in0", self._ncnn.Mat(chw))
        _, out = ex.extract("out0")
        return decode(np.array(out), scale, pad_x, pad_y, self.conf)


class OpenVinoDetector:
    def __init__(self, model_dir: Path, threads: int = 2, conf: float = 0.4) -> None:
        import openvino as ov

        core = ov.Core()
        self.conf = conf
        self.model = core.compile_model(
            str(model_dir / "yolo11n.xml"), "CPU", {"INFERENCE_NUM_THREADS": threads}
        )

    def detect(self, rgb: np.ndarray) -> list[Box]:
        chw, scale, pad_x, pad_y = letterbox(rgb)
        out = self.model(chw[None])[0]
        return decode(np.asarray(out), scale, pad_x, pad_y, self.conf)


def make_detector(vision_cfg: dict, models_dir: Path) -> Detector:
    backend = vision_cfg["backend"]
    args = (vision_cfg["threads"], vision_cfg["conf"])
    if backend == "ncnn":
        return NcnnDetector(models_dir / "yolo" / "ncnn", *args)
    if backend == "openvino":
        return OpenVinoDetector(models_dir / "yolo" / "openvino", *args)
    raise ValueError(f"Unknown vision backend {backend!r}; use ncnn or openvino.")
