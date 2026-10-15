"""Overview numbers for the dashboard (baseline 5.2 and 5.3)."""

import time

from core.store.db import Database

COUNTED = [
    "encounter",
    "greeting",
    "conversation_start",
    "question",
    "answered",
    "unmatched",
    "fallback",
    "walkaway",
    "decline",
]


def start_of_today(now: float | None = None) -> float:
    t = time.localtime(now if now is not None else time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _avg(db: Database, kind: str, since: float) -> float | None:
    value = db.execute(
        "SELECT avg(value) AS a FROM events WHERE type = ? AND ts >= ?", (kind, since)
    )[0]["a"]
    return round(value, 1) if value is not None else None


def overview(db: Database, since: float) -> dict:
    rows = db.execute(
        "SELECT type, count(*) AS n FROM events WHERE ts >= ? GROUP BY type", (since,)
    )
    counts = {t: 0 for t in COUNTED}
    counts.update({r["type"]: r["n"] for r in rows if r["type"] in counts})
    avg_reply = _avg(db, "reply_latency_ms", since)
    return {
        "counts": counts,
        "avg_conversation_s": _avg(db, "conversation_end", since),
        "avg_reply_ms": round(avg_reply) if avg_reply is not None else None,
    }


def hourly(db: Database, since: float) -> list[dict]:
    rows = db.execute(
        "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS h,"
        " count(*) AS n FROM events WHERE type = 'encounter' AND ts >= ? GROUP BY h",
        (since,),
    )
    by_hour = {r["h"]: r["n"] for r in rows}
    return [{"hour": h, "encounters": by_hour.get(h, 0)} for h in range(24)]
