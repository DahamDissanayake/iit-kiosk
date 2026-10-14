from core.store.db import Database
from core.store.events import EventLog, SessionRecorder, UnmatchedLog


def test_session_recorder_groups_events_by_encounter():
    db = Database(":memory:")
    rec = SessionRecorder(EventLog(db, clock=lambda: 100.0))
    rec("encounter", None)
    first = rec.session_id
    rec("greeting", None)
    rec("reply_latency_ms", 1200)
    rec("encounter", None)
    rows = db.execute("SELECT type, value, session_id FROM events ORDER BY id")
    assert [r["type"] for r in rows] == ["encounter", "greeting", "reply_latency_ms", "encounter"]
    assert rows[1]["session_id"] == first
    assert rows[2]["value"] == 1200
    assert rows[3]["session_id"] != first


def test_unmatched_questions_are_not_stored_when_disabled():
    db = Database(":memory:")
    log = UnmatchedLog(db, enabled=False, retention_days=30)
    log.add("Where is the canteen?")
    assert log.list() == []


def test_unmatched_questions_are_stored_and_purged():
    db = Database(":memory:")
    now = [1_000_000.0]
    log = UnmatchedLog(db, enabled=True, retention_days=30, clock=lambda: now[0])
    log.add("Where is the canteen?")
    assert [q["text"] for q in log.list()] == ["Where is the canteen?"]
    now[0] += 31 * 86400
    assert log.purge() == 1
    assert log.list() == []
