"""Settings staff can change in the dashboard. Defaults come from config.toml (baseline 9)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from core.store.db import Database


@dataclass(frozen=True)
class Field:
    type: type
    default: Callable[[dict], object]
    min: float | None = None
    max: float | None = None


FIELDS: dict[str, Field] = {
    "volume": Field(float, lambda c: 0.8, 0.0, 1.0),
    "music_on": Field(bool, lambda c: True),
    "music_volume": Field(float, lambda c: c["audio"]["music_volume"], 0.0, 1.0),
    "quiet_mode": Field(bool, lambda c: False),
    "kids_default": Field(bool, lambda c: c["engagement"]["kids_default"]),
    "greet_cooldown_s": Field(int, lambda c: c["engagement"]["greet_cooldown_s"], 5, 300),
    "dwell_s": Field(float, lambda c: c["vision"]["dwell_s"], 0.5, 5.0),
    "min_box_height_frac": Field(float, lambda c: c["vision"]["min_box_height_frac"], 0.05, 0.9),
    "centre_band": Field(float, lambda c: c["vision"]["centre_band"], 0.1, 1.0),
    "approach_growth": Field(float, lambda c: c["vision"]["approach_growth"], 0.02, 0.6),
    "mirror": Field(bool, lambda c: c["vision"]["mirror"]),
    "log_unmatched_questions": Field(bool, lambda c: c["privacy"]["log_unmatched_questions"]),
    "min_score": Field(float, lambda c: c["rag"]["min_score"], 0.0, 1.0),
}

ZONE_KEYS = ("min_box_height_frac", "centre_band", "approach_growth", "mirror")


def _coerce(key: str, value: object) -> object:
    if key not in FIELDS:
        raise ValueError(f"Unknown setting: {key}")
    f = FIELDS[key]
    if f.type is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if f.type is int:
        if float(value) != int(value):
            raise ValueError(f"{key} must be a whole number")
        value = int(value)
    else:
        value = float(value)
    if (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
        raise ValueError(f"{key} must be between {f.min} and {f.max}")
    return value


class Settings:
    def __init__(self, db: Database, cfg: dict) -> None:
        self.db = db
        self.cfg = cfg

    def defaults(self) -> dict:
        return {key: f.default(self.cfg) for key, f in FIELDS.items()}

    def all(self) -> dict:
        values = self.defaults()
        for row in self.db.execute("SELECT key, value FROM settings"):
            if row["key"] in FIELDS:
                values[row["key"]] = json.loads(row["value"])
        return values

    def update(self, changes: dict) -> dict:
        clean = {key: _coerce(key, value) for key, value in changes.items()}
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            for key, value in clean.items():
                conn.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at",
                    (key, json.dumps(value), now),
                )
        return self.all()
