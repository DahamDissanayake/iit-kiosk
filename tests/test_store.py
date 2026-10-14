import os

import sqlite_vec

from core.paths import data_dir
from core.secrets import load_env
from core.store.db import Database
from core.store.migrations import SCHEMA_VERSION

TABLES = {
    "schema_version",
    "sources",
    "chunks",
    "chunk_vec",
    "events",
    "settings",
    "auth",
    "unmatched_questions",
}


def test_new_database_has_every_table():
    db = Database(":memory:")
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names
    assert db.execute("SELECT version FROM schema_version")[0]["version"] == SCHEMA_VERSION


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "kiosk.db"
    Database(path).execute("INSERT INTO settings VALUES ('a', '1', 'now')")
    db = Database(path)
    assert db.execute("SELECT value FROM settings WHERE key='a'")[0]["value"] == "1"
    assert len(db.execute("SELECT * FROM schema_version")) == 1


def test_vector_search_works():
    db = Database(":memory:")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (1, ?)",
            (sqlite_vec.serialize_float32([1.0] + [0.0] * 383),),
        )
        conn.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (2, ?)",
            (sqlite_vec.serialize_float32([0.0, 1.0] + [0.0] * 382),),
        )
    rows = db.execute(
        "SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? AND k = 1",
        (sqlite_vec.serialize_float32([0.9, 0.1] + [0.0] * 382),),
    )
    assert rows[0]["rowid"] == 1


def test_transaction_rolls_back_on_error():
    db = Database(":memory:")
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO settings VALUES ('x', '1', 'now')")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.execute("SELECT * FROM settings") == []


def test_load_env_reads_file_and_env_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# secrets\nLLM_API_KEY="abc"\nSESSION_SECRET=s1\n\n', encoding="utf-8")
    monkeypatch.setenv("SESSION_SECRET", "s2")
    values = load_env(env)
    assert values["LLM_API_KEY"] == "abc"
    assert values["SESSION_SECRET"] == "s2"


def test_load_env_missing_file_returns_only_environment(tmp_path):
    assert load_env(tmp_path / "nope.env") == dict(os.environ)


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "d"))
    assert data_dir({"paths": {"data_dir": "./ignored"}}) == tmp_path / "d"
    assert (tmp_path / "d").is_dir()
