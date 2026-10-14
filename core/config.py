"""Loads config.toml. Dashboard overrides stored in SQLite are layered on top in M5."""

import tomllib
from pathlib import Path


def load_config(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)
