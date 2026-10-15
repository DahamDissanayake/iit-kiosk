"""Pi system readings (None on laptops)."""

import os
from pathlib import Path


def read_temp() -> float | None:
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    return int(path.read_text()) / 1000 if path.exists() else None


def read_mem_mb() -> tuple[int, int] | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    info = dict(line.split(":", 1) for line in path.read_text().splitlines())
    return int(info["MemTotal"].split()[0]) // 1024, int(info["MemAvailable"].split()[0]) // 1024


def load1() -> float | None:
    return os.getloadavg()[0] if hasattr(os, "getloadavg") else None
