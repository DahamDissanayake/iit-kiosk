import logging
import time

from core.admin.health import ErrorBuffer
from core.admin.stats import hourly, overview, start_of_today
from core.store.db import Database
from core.store.events import EventLog


def seed(db, ts):
    log = EventLog(db, clock=lambda: ts)
    for t in [
        "encounter",
        "encounter",
        "greeting",
        "conversation_start",
        "question",
        "answered",
        "question",
        "unmatched",
        "walkaway",
    ]:
        log.add(t)
    log.add("conversation_end", 40.0)
    log.add("conversation_end", 20.0)
    log.add("reply_latency_ms", 1800)
    log.add("reply_latency_ms", 2200)


def test_overview_counts_and_averages():
    db = Database(":memory:")
    now = time.time()
    seed(db, now)
    s = overview(db, start_of_today(now))
    assert s["counts"]["encounter"] == 2
    assert s["counts"]["question"] == 2
    assert s["counts"]["decline"] == 0
    assert s["avg_conversation_s"] == 30.0
    assert s["avg_reply_ms"] == 2000


def test_today_excludes_yesterday():
    db = Database(":memory:")
    now = time.time()
    seed(db, start_of_today(now) - 3600)
    assert overview(db, start_of_today(now))["counts"]["encounter"] == 0
    assert overview(db, 0)["counts"]["encounter"] == 2


def test_hourly_has_24_buckets():
    db = Database(":memory:")
    now = time.time()
    seed(db, now)
    rows = hourly(db, 0)
    assert len(rows) == 24
    assert sum(r["encounters"] for r in rows) == 2
    assert rows[time.localtime(now).tm_hour]["encounters"] == 2


def test_error_buffer_keeps_recent_warnings():
    buf = ErrorBuffer.install()
    logging.getLogger("kiosk.test").warning("camera hiccup")
    logging.getLogger("kiosk.test").info("not kept")
    messages = [e["message"] for e in buf.items()]
    assert "camera hiccup" in messages
    assert "not kept" not in messages
