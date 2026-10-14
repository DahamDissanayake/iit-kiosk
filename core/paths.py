"""Where data and models live. Environment variables override config.toml on the Pi."""

import os
from pathlib import Path


def data_dir(cfg: dict) -> Path:
    path = Path(os.environ.get("KIOSK_DATA_DIR") or cfg["paths"]["data_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir(cfg: dict) -> Path:
    return Path(os.environ.get("KIOSK_MODELS_DIR") or cfg["paths"]["models_dir"])
