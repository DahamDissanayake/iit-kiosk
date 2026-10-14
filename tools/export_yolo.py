"""Export YOLO11n for the Pi. Runs on a laptop or CI, never on the Pi (needs PyTorch).

uv run --group export python -m tools.export_yolo
"""

import shutil
import tarfile
from pathlib import Path

from ultralytics import YOLO

OUT = Path("models/yolo")


def main() -> None:
    model = YOLO("yolo11n.pt")
    ncnn_dir = Path(model.export(format="ncnn", imgsz=320))
    ov_dir = Path(model.export(format="openvino", imgsz=320, int8=True, data="coco8.yaml"))
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(ncnn_dir, OUT / "ncnn")
    shutil.copytree(ov_dir, OUT / "openvino")
    with tarfile.open("models/yolo11n-export.tar.gz", "w:gz") as tar:
        tar.add(OUT, arcname="yolo")
    print(f"exported to {OUT} and models/yolo11n-export.tar.gz")


if __name__ == "__main__":
    main()
