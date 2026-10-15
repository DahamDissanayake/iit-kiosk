"""Health page data: recent warnings, internet reachability, systemd restart counts."""

import asyncio
import logging
import subprocess
import time
from collections import deque

LLM_HOSTS = {
    "gemini": "generativelanguage.googleapis.com",
    "anthropic": "api.anthropic.com",
    "openai": "api.openai.com",
}


class ErrorBuffer(logging.Handler):
    _installed: "ErrorBuffer | None" = None

    def __init__(self, size: int = 50) -> None:
        super().__init__(level=logging.WARNING)
        self._items: deque[dict] = deque(maxlen=size)

    @classmethod
    def install(cls) -> "ErrorBuffer":
        if cls._installed is None:
            cls._installed = cls()
            logging.getLogger().addHandler(cls._installed)
        return cls._installed

    def emit(self, record: logging.LogRecord) -> None:
        self._items.append(
            {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )

    def items(self) -> list[dict]:
        return list(reversed(self._items))


class NetProbe:
    def __init__(self, host: str, port: int = 443, every_s: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.every_s = every_s
        self.ok: bool | None = None
        self.checked_at: float | None = None
        self._task: asyncio.Task | None = None

    async def check(self) -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 3)
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            self.ok = await self.check()
            self.checked_at = time.time()
            await asyncio.sleep(self.every_s)


def systemd_restarts(unit: str) -> int | None:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "NRestarts", "--value"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
        return int(out) if out.isdigit() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
