"""Versioned schema. Append new scripts; never edit a released one."""

import sqlite3

MIGRATIONS = [
    """
    CREATE TABLE sources (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('text', 'qa', 'file', 'menu')),
        filename TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE chunks (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        ord INTEGER NOT NULL,
        heading TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL,
        tokens INTEGER NOT NULL,
        embed_model TEXT NOT NULL
    );
    CREATE INDEX chunks_source ON chunks(source_id);
    CREATE VIRTUAL TABLE chunk_vec USING vec0(embedding float[384] distance_metric=cosine);
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        session_id TEXT,
        type TEXT NOT NULL,
        value REAL,
        meta TEXT
    );
    CREATE INDEX events_ts ON events(ts);
    CREATE INDEX events_type_ts ON events(type, ts);
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE auth (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        pin_hash TEXT,
        failed_count INTEGER NOT NULL DEFAULT 0,
        locked_until REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE unmatched_questions (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        text TEXT NOT NULL
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version VALUES (0)")
        current = 0
    else:
        current = row[0]
    for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(
            f"BEGIN; {script}; UPDATE schema_version SET version = {version}; COMMIT;"
        )
