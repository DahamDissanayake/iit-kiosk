"""Anonymous usage counts and timings (baseline 5.3). No names, audio or images."""

import json
import time
import uuid
from collections.abc import Callable

from core.store.db import Database


class EventLog:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db = db
        self.clock = clock

    def add(
        self,
        type: str,
        value: float | None = None,
        meta: dict | None = None,
        session_id: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO events (ts, session_id, type, value, meta) VALUES (?, ?, ?, ?, ?)",
            (self.clock(), session_id, type, value, json.dumps(meta) if meta else None),
        )


class SessionRecorder:
    """Runtime record hook: a new random session id starts with every encounter."""

    def __init__(self, events: EventLog) -> None:
        self.events = events
        self.session_id: str | None = None

    def __call__(self, kind: str, value: float | None) -> None:
        if kind == "encounter":
            self.session_id = uuid.uuid4().hex[:12]
        self.events.add(kind, value, session_id=self.session_id)


class UnmatchedLog:
    """Visitor speech, so off by default and kept only for `retention_days`."""

    def __init__(
        self,
        db: Database,
        enabled: bool,
        retention_days: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.enabled = enabled
        self.retention_days = retention_days
        self.clock = clock

    def add(self, text: str) -> None:
        if self.enabled:
            self.db.execute(
                "INSERT INTO unmatched_questions (ts, text) VALUES (?, ?)", (self.clock(), text)
            )

    def purge(self) -> int:
        cutoff = self.clock() - self.retention_days * 86400
        with self.db.transaction() as conn:
            return conn.execute("DELETE FROM unmatched_questions WHERE ts < ?", (cutoff,)).rowcount

    def list(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, ts, text FROM unmatched_questions ORDER BY ts DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]
