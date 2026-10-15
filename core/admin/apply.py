"""Applies dashboard settings to the running kiosk without a restart."""

import dataclasses
import logging
import subprocess
from collections.abc import Callable

from core.runtime import Runtime

log = logging.getLogger("kiosk.settings")


def set_system_volume(level: float) -> None:
    """Speaker volume through PipeWire; a no-op where wpctl is missing (laptops, CI)."""
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"],
            check=False,
            timeout=3,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.info("wpctl not available; volume %.2f not applied", level)


class SettingsApplier:
    def __init__(
        self,
        runtime: Runtime,
        services,
        music_url: str,
        set_volume: Callable[[float], None] = set_system_volume,
    ) -> None:
        self.runtime = runtime
        self.services = services
        self.music_url = music_url
        self.set_volume = set_volume

    async def apply(self, s: dict) -> None:
        c = self.runtime.c
        c.cfg = dataclasses.replace(
            c.cfg,
            greet_cooldown_s=s["greet_cooldown_s"],
            dwell_s=s["dwell_s"],
            kids_default=s["kids_default"],
        )
        if hasattr(self.services.answerer, "min_score"):
            self.services.answerer.min_score = s["min_score"]
        self.services.unmatched.enabled = s["log_unmatched_questions"]
        quiet = s["quiet_mode"]
        url = self.music_url if (s["music_on"] and not quiet) else ""
        self.runtime.music = {"url": url, "volume": s["music_volume"]}
        await self.runtime.send({"type": "music", **self.runtime.music})
        self.set_volume(s["volume"] * (0.5 if quiet else 1.0))
