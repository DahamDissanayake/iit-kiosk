# M2: Knowledge Base, LLM and Piper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A typed question (dev panel) gets a spoken Piper answer drawn from the on-Pi knowledge base, with an honest "I don't have that" when nothing matches, and every encounter is counted in SQLite.

**Architecture:** One SQLite file (with sqlite-vec) holds sources, chunks, vectors, events, settings and auth. Content is extracted, chunked and embedded with FastEmbed (bge-small-en-v1.5). `RagAnswerer` replaces M1's `CannedAnswerer`: it searches the knowledge base, refuses below `rag.min_score`, and streams sentences from a cloud LLM through a provider adapter. `PiperSpeech` replaces `FakeSpeech`. `build_services()` assembles everything; `create_app()` takes the result.

**Tech Stack:** Python 3.11+, SQLite + sqlite-vec, FastEmbed (ONNX Runtime), pypdf, python-docx, markdown-it-py, httpx (SSE streaming), piper-tts.

**Spec:** `docs/superpowers/specs/2026-10-14-mvp-build-design.md` (requirements in `docs/baseline-spec.md` sections 4.3, 5, 6, 8, 9). Builds on `docs/superpowers/plans/2026-10-14-m1-skeleton-ui-controller.md`.

## Global Constraints

- Work on a branch off `dev` named `task/<KEY>-<short-slug>`; commit messages are `<KEY>: short imperative summary`.
- Never add a `Co-Authored-By` trailer, a "Generated with" line, or any AI or agent attribution anywhere.
- Never commit secrets or a `.env` file. `LLM_API_KEY` lives in `<data_dir>/.env`.
- Dependencies added in M2 (all named in baseline section 6): `httpx` (moved from dev to main), `sqlite-vec`, `fastembed`, `pypdf`, `python-docx`, `markdown-it-py`, `piper-tts`. Add nothing else.
- No PyTorch. All models run through ONNX Runtime.
- Chunking: about 250 tokens, 40-token overlap, each heading kept with its text; Q&A pairs and menu items are one chunk each (baseline 5.4).
- Retrieval: top 4 enabled chunks; below `rag.min_score` → `unmatched` (baseline 5.5).
- Store the embedding model name with every chunk and refuse to mix models (baseline 5.6).
- LLM system prompt follows the five rules in baseline 4.3 exactly.
- Spoken replies: at most `llm.max_sentences` sentences, no markdown, no URLs.
- Unmatched question text is stored only when `privacy.log_unmatched_questions` is true, and purged after `privacy.unmatched_retention_days`.
- Format and lint before each commit: `uv run ruff format . && uv run ruff check --fix .`

## Changes to the baseline data model

- `sources` gains `body TEXT`: the extracted text (or JSON for Q&A pairs and file sections), so editing and re-indexing never need the original file.
- `sources.kind` allows `menu` (already agreed in the design spec).

## Review Focus

1. **Empty or image-only uploads.** A PDF with no extractable text must be rejected with a clear message, not stored as a source with zero chunks. (Task 3: `test_pdf_without_text_is_rejected`)
2. **Embedding model changed in config.** Searching after `rag.embed_model` changes must refuse (re-index needed), not silently return wrong matches. (Task 4: `test_search_refuses_mixed_models_until_reindex`)
3. **LLM fails after the first sentence.** The visitor keeps what was already spoken and the turn ends normally; it must not flip to the offline menu mid-answer. (Task 8: `test_llm_error_after_first_sentence_ends_turn_quietly`)
4. **Abbreviations and decimals in streamed text.** "Dr. Silva teaches 3.5 credit modules." must stay one sentence even when the stream splits inside "Dr." or "3.5". (Task 6: `test_abbreviations_and_decimals_split_across_chunks`)
5. **Disabled sources.** A disabled source must never reach the LLM, even when it is the closest match. (Task 4: `test_disabled_source_is_never_returned`)

---

## File Structure

```
config.toml                    + [paths], [llm] max_output_tokens
pyproject.toml                 + deps, slow marker
core/paths.py                  data_dir(), models_dir()
core/secrets.py                load_env()
core/store/__init__.py
core/store/db.py               Database (connection, lock, transaction)
core/store/migrations.py       MIGRATIONS, migrate()
core/store/events.py           EventLog, SessionRecorder, UnmatchedLog
core/rag/__init__.py
core/rag/extract.py            Section, extract(), sections_from_*()
core/rag/chunk.py              Chunk, count_tokens(), chunk_sections(), qa_chunks()
core/rag/embed.py              Embedder protocol, FastEmbedder, HashEmbedder
core/rag/kb.py                 KnowledgeBase, Hit, SourceInfo, ModelMismatch
core/rag/ingest.py             `python -m core.rag.ingest` CLI
core/llm/__init__.py
core/llm/prompt.py             Prompt, build_prompt()
core/llm/sentences.py          SentenceSplitter, clean_for_speech()
core/llm/providers.py          LLMProvider, LLMError, Gemini/Anthropic/OpenAI, make_provider()
core/answer.py                 + RagAnswerer
core/tts_piper.py              PiperSpeech
core/services.py               Services, build_services()
core/controller/machine.py     + set_menu()
core/runtime.py                + menu_source, refresh_menu()
core/app.py                    create_app(cfg, dev, services)
models/download.py             model downloader with checksums
models/README.md
tools/rag_eval.py              threshold tuning on the test questions
tests/rag_questions.toml       test questions (IIT content added when it arrives)
tests/test_store.py, test_events.py, test_extract_chunk.py, test_kb.py,
tests/test_llm.py, test_rag_answerer.py, test_piper.py, test_services.py
```

---

### Task 1: Paths, secrets and the SQLite store

**Files:**
- Modify: `pyproject.toml`, `config.toml`, `.gitignore`
- Create: `core/paths.py`, `core/secrets.py`, `core/store/__init__.py` (empty), `core/store/db.py`, `core/store/migrations.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `data_dir(cfg) -> Path`, `models_dir(cfg) -> Path`, `load_env(path) -> dict[str, str]`, `Database(path)` with `.conn`, `.lock`, `.execute(sql, params=()) -> list[sqlite3.Row]`, `.transaction()` context manager yielding the connection; `migrate(conn)`; `SCHEMA_VERSION: int`.

- [ ] **Step 1: Add dependencies and config**

In `pyproject.toml`, set `dependencies` to:
```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "sqlite-vec>=0.1.6",
    "fastembed>=0.4",
    "pypdf>=5.0",
    "python-docx>=1.1",
    "markdown-it-py>=3.0",
    "piper-tts>=1.3",
]
```
Remove `httpx` from the dev group, and add under `[tool.pytest.ini_options]`:
```toml
markers = ["slow: needs downloaded models; run with RUN_SLOW=1"]
```

Append to `config.toml`:
```toml
[paths]
data_dir = "./.data"         # /var/lib/kiosk on the Pi (KIOSK_DATA_DIR)
models_dir = "./models"      # /opt/kiosk/models on the Pi (KIOSK_MODELS_DIR)
```
And add to `[llm]`:
```toml
max_output_tokens = 200
```

Append to `.gitignore`:
```gitignore
.data/
```

- [ ] **Step 2: Write the failing tests** `tests/test_store.py`

```python
import os

import sqlite_vec

from core.paths import data_dir
from core.secrets import load_env
from core.store.db import Database
from core.store.migrations import SCHEMA_VERSION

TABLES = {"schema_version", "sources", "chunks", "chunk_vec", "events", "settings", "auth",
          "unmatched_questions"}


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
        conn.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (1, ?)",
                     (sqlite_vec.serialize_float32([1.0] + [0.0] * 383),))
        conn.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (2, ?)",
                     (sqlite_vec.serialize_float32([0.0, 1.0] + [0.0] * 382),))
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv sync && uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.paths'`

- [ ] **Step 4: Implement**

`core/paths.py`:
```python
"""Where data and models live. Environment variables override config.toml on the Pi."""

import os
from pathlib import Path


def data_dir(cfg: dict) -> Path:
    path = Path(os.environ.get("KIOSK_DATA_DIR") or cfg["paths"]["data_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir(cfg: dict) -> Path:
    return Path(os.environ.get("KIOSK_MODELS_DIR") or cfg["paths"]["models_dir"])
```

`core/secrets.py`:
```python
"""Reads KEY=VALUE secrets from <data_dir>/.env. Real environment variables win."""

import os
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values | dict(os.environ)
```

`core/store/migrations.py`:
```python
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
```

`core/store/db.py`:
```python
"""One SQLite file for the knowledge base, stats, settings and auth (baseline 8)."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

from core.store.migrations import migrate


class Database:
    def __init__(self, path: str | Path) -> None:
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        migrate(self.conn)

    def execute(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS. If `enable_load_extension` is missing, the Python build lacks extension loading: use `uv python install 3.12` (python-build-standalone supports it) and re-run.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add pyproject.toml uv.lock config.toml .gitignore core/paths.py core/secrets.py core/store tests/test_store.py
git commit -m "<KEY>: add SQLite store with migrations and sqlite-vec"
```

---

### Task 2: Event log, sessions and unmatched questions

**Files:**
- Create: `core/store/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `Database` (Task 1). M1 `Runtime(record=...)` calls `record(kind: str, value: float | None)`.
- Produces: `EventLog(db, clock=time.time).add(type, value=None, meta=None, session_id=None)`; `SessionRecorder(events)` callable `(kind, value) -> None` with `.session_id`; `UnmatchedLog(db, enabled, retention_days, clock=time.time)` with `.enabled` (mutable), `.add(text)`, `.purge() -> int`, `.list(limit=200) -> list[dict]`.

- [ ] **Step 1: Write the failing tests** `tests/test_events.py`

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.store.events'`

- [ ] **Step 3: Implement** `core/store/events.py`

```python
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
```

- [ ] **Step 4: Run tests, commit**

Run: `uv run pytest tests/test_events.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/store/events.py tests/test_events.py
git commit -m "<KEY>: record anonymous events and opt-in unmatched questions"
```

---

### Task 3: Text extraction and chunking

**Files:**
- Create: `core/rag/__init__.py` (empty), `core/rag/extract.py`, `core/rag/chunk.py`
- Test: `tests/test_extract_chunk.py`

**Interfaces:**
- Produces: `Section(heading: str, text: str)`; `extract(path: Path) -> list[Section]` (raises `ValueError` for unsupported type or no text); `sections_from_markdown(text)`, `sections_from_text(text)`, `sections_from_docx(path)`, `sections_from_pdf(path)`; `Chunk(heading: str, text: str, tokens: int)`; `count_tokens(text) -> int`; `chunk_sections(sections, size=250, overlap=40) -> list[Chunk]`; `qa_chunks(pairs) -> list[Chunk]`.

- [ ] **Step 1: Write the failing tests** `tests/test_extract_chunk.py`

```python
import pytest
from docx import Document

from core.rag.chunk import Chunk, chunk_sections, count_tokens, qa_chunks
from core.rag.extract import Section, extract, sections_from_markdown


def minimal_pdf(text: str | None) -> bytes:
    """A one-page PDF; with text=None the page has no text at all."""
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# ---- extraction ----


def test_markdown_keeps_headings_with_their_text():
    md = "# Programmes\nWe teach **computing**.\n\n## Business\nAnd business too.\n"
    assert sections_from_markdown(md) == [
        Section("Programmes", "We teach computing."),
        Section("Business", "And business too."),
    ]


def test_markdown_without_headings_is_one_section():
    assert sections_from_markdown("Just a paragraph.\n\nAnother one.") == [
        Section("", "Just a paragraph. Another one.")
    ]


def test_docx_headings_and_paragraphs(tmp_path):
    doc = Document()
    doc.add_heading("Campus", level=1)
    doc.add_paragraph("The campus is in Colombo.")
    doc.add_heading("Library", level=2)
    doc.add_paragraph("Open until 8 pm.")
    path = tmp_path / "info.docx"
    doc.save(path)
    assert extract(path) == [
        Section("Campus", "The campus is in Colombo."),
        Section("Library", "Open until 8 pm."),
    ]


def test_pdf_text_is_extracted(tmp_path):
    path = tmp_path / "info.pdf"
    path.write_bytes(minimal_pdf("Hello campus"))
    sections = extract(path)
    assert "Hello campus" in sections[0].text


def test_pdf_without_text_is_rejected(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(minimal_pdf(None))
    with pytest.raises(ValueError, match="no text"):
        extract(path)


def test_unsupported_file_type_is_rejected(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(ValueError, match="Unsupported"):
        extract(path)


# ---- chunking ----


def test_short_section_is_one_chunk_with_heading():
    chunks = chunk_sections([Section("Campus", "The campus is in Colombo.")])
    assert chunks == [Chunk("Campus", "Campus\nThe campus is in Colombo.", 7)]


def test_long_section_is_split_with_overlap_and_heading_in_every_chunk():
    words = [f"w{i}" for i in range(600)]
    chunks = chunk_sections([Section("Research", " ".join(words))], size=250, overlap=40)
    assert len(chunks) >= 3
    for c in chunks:
        assert c.text.startswith("Research\n")
        assert c.tokens <= 250
    first = chunks[0].text.split("\n", 1)[1].split()
    second = chunks[1].text.split("\n", 1)[1].split()
    shared = [w for w in second if w in set(first)]
    assert 30 <= len(shared) <= 45
    last = chunks[-1].text.split()
    assert last[-1] == "w599"


def test_empty_sections_are_skipped():
    assert chunk_sections([Section("Empty", "   ")]) == []


def test_qa_pairs_are_one_chunk_each():
    chunks = qa_chunks([("Where is IIT?", "In Colombo."), ("Is there parking?", "Yes.")])
    assert [c.text for c in chunks] == [
        "Q: Where is IIT?\nA: In Colombo.",
        "Q: Is there parking?\nA: Yes.",
    ]


def test_count_tokens_counts_words_and_punctuation():
    assert count_tokens("Hello, world!") == 4
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_extract_chunk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.rag'`

- [ ] **Step 3: Implement** `core/rag/extract.py`

```python
"""Turns uploaded files and pasted text into (heading, text) sections."""

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from markdown_it import MarkdownIt
from pypdf import PdfReader


@dataclass(frozen=True)
class Section:
    heading: str
    text: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _group(items: list[tuple[str, str]]) -> list[Section]:
    """items are ("h", heading) or ("p", paragraph); paragraphs join under the last heading."""
    sections: list[Section] = []
    heading, body = "", []
    for kind, value in items:
        if kind == "h":
            if body:
                sections.append(Section(heading, _norm(" ".join(body))))
            heading, body = _norm(value), []
        elif value.strip():
            body.append(value)
    if body:
        sections.append(Section(heading, _norm(" ".join(body))))
    return sections


def sections_from_markdown(text: str) -> list[Section]:
    tokens = MarkdownIt().parse(text)
    items: list[tuple[str, str]] = []
    in_heading = False
    for tok in tokens:
        if tok.type == "heading_open":
            in_heading = True
        elif tok.type == "heading_close":
            in_heading = False
        elif tok.type == "inline":
            plain = "".join(
                c.content for c in (tok.children or []) if c.type in ("text", "code_inline")
            )
            items.append(("h" if in_heading else "p", plain))
    return _group(items)


def sections_from_text(text: str) -> list[Section]:
    return _group([("p", p) for p in re.split(r"\n\s*\n", text)])


def sections_from_docx(path: Path) -> list[Section]:
    doc = Document(str(path))
    items: list[tuple[str, str]] = []
    for p in doc.paragraphs:
        style = (p.style.name or "") if p.style is not None else ""
        kind = "h" if style.startswith(("Heading", "Title")) else "p"
        items.append((kind, p.text))
    for table in doc.tables:
        for row in table.rows:
            items.append(("p", " | ".join(cell.text for cell in row.cells)))
    return _group(items)


def sections_from_pdf(path: Path) -> list[Section]:
    reader = PdfReader(str(path))
    return [
        Section("", _norm(text))
        for page in reader.pages
        if (text := page.extract_text() or "").strip()
    ]


def extract(path: Path) -> list[Section]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        sections = sections_from_pdf(path)
    elif suffix == ".docx":
        sections = sections_from_docx(path)
    elif suffix in (".md", ".markdown"):
        sections = sections_from_markdown(path.read_text(encoding="utf-8"))
    elif suffix == ".txt":
        sections = sections_from_text(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported file type: {suffix or 'none'}. Use PDF, DOCX, MD or TXT.")
    if not sections:
        raise ValueError("The file has no text that can be read (is it a scanned image?).")
    return sections
```

- [ ] **Step 4: Implement** `core/rag/chunk.py`

```python
"""Splits sections into ~250-token chunks with 40-token overlap (baseline 5.4)."""

import re
from dataclasses import dataclass

from core.rag.extract import Section

TOKEN_RE = re.compile(r"\w+|[^\w\s]")


@dataclass(frozen=True)
class Chunk:
    heading: str
    text: str
    tokens: int


def count_tokens(text: str) -> int:
    """Word-and-punctuation count; close enough to model tokens for sizing chunks."""
    return len(TOKEN_RE.findall(text))


def chunk_sections(sections: list[Section], size: int = 250, overlap: int = 40) -> list[Chunk]:
    chunks: list[Chunk] = []
    for sec in sections:
        words = sec.text.split()
        if not words:
            continue
        budget = max(20, size - count_tokens(sec.heading) - 1)
        start = 0
        while start < len(words):
            end, used = start, 0
            while end < len(words):
                cost = count_tokens(words[end])
                if used + cost > budget and end > start:
                    break
                used += cost
                end += 1
            body = " ".join(words[start:end])
            text = f"{sec.heading}\n{body}" if sec.heading else body
            chunks.append(Chunk(sec.heading, text, count_tokens(text)))
            if end >= len(words):
                break
            back, carried = end, 0
            while back > start + 1 and carried < overlap:
                back -= 1
                carried += count_tokens(words[back])
            start = back
    return chunks


def qa_chunks(pairs: list[tuple[str, str]]) -> list[Chunk]:
    out = []
    for question, answer in pairs:
        text = f"Q: {question.strip()}\nA: {answer.strip()}"
        out.append(Chunk("", text, count_tokens(text)))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract_chunk.py -v`
Expected: PASS. If `test_pdf_text_is_extracted` fails because pypdf cannot read the generated file, print `extract(path)` and fix the helper's offsets; do not weaken the assertion.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/rag tests/test_extract_chunk.py
git commit -m "<KEY>: extract text from documents and split into chunks"
```

---

### Task 4: Embeddings and the knowledge base

**Files:**
- Create: `core/rag/embed.py`, `core/rag/kb.py`
- Test: `tests/test_kb.py`

**Interfaces:**
- Consumes: `Database`, `Section`, `extract`, `sections_from_markdown`, `chunk_sections`, `qa_chunks`, M1 `MenuItem`.
- Produces:
  - `Embedder` protocol: `name: str`, `dim: int`, `passages(texts: list[str]) -> list[list[float]]`, `query(text: str) -> list[float]`; `FastEmbedder(name, cache_dir=None)`; `HashEmbedder(name="test-hash")` (tests and dev only).
  - `Hit(chunk_id, source_id, title, heading, text, score)` where score is cosine similarity (1 = identical).
  - `SourceInfo(id, title, kind, filename, enabled, chunk_count, created_at, updated_at)`.
  - `ModelMismatch(Exception)`.
  - `KnowledgeBase(db, embedder, chunk_tokens=250, chunk_overlap=40)` with `add_text(title, text) -> int`, `add_qa(title, pairs) -> int`, `add_file(title, filename, data: bytes) -> int`, `add_menu(label, answer) -> int`, `update(source_id, *, title=None, enabled=None, text=None, pairs=None) -> None`, `delete(source_id) -> None`, `reindex() -> int`, `needs_reindex() -> bool`, `list_sources() -> list[SourceInfo]`, `get_body(source_id) -> str`, `menu_items() -> list[MenuItem]`, `search(query, k=4) -> list[Hit]`.

- [ ] **Step 1: Write the failing tests** `tests/test_kb.py`

```python
import os

import pytest

from core.rag.embed import FastEmbedder, HashEmbedder
from core.rag.kb import KnowledgeBase, ModelMismatch
from core.store.db import Database


def kb(db=None, name="test-hash"):
    return KnowledgeBase(db or Database(":memory:"), HashEmbedder(name))


def test_search_finds_the_matching_source():
    k = kb()
    k.add_text("Campus", "# Library\nThe library opens at eight in the morning.")
    k.add_text("LeapGen", "LeapGen helps students launch startups.")
    hits = k.search("When does the library open?")
    assert hits[0].title == "Campus"
    assert hits[0].heading == "Library"
    assert 0 < hits[0].score <= 1


def test_disabled_source_is_never_returned():
    k = kb()
    sid = k.add_text("Campus", "The library opens at eight.")
    k.add_text("Other", "Unrelated words about sports.")
    k.update(sid, enabled=False)
    assert all(h.source_id != sid for h in k.search("library opens at eight"))


def test_qa_and_menu_sources_are_one_chunk_per_pair():
    k = kb()
    k.add_qa("FAQ", [("Is there parking?", "Yes, behind the main building."),
                     ("Is there Wi-Fi?", "Yes, for registered students.")])
    k.add_menu("What is LeapGen?", "LeapGen is IIT's startup programme.")
    counts = {s.title: s.chunk_count for s in k.list_sources()}
    assert counts == {"FAQ": 2, "What is LeapGen?": 1}
    assert k.search("parking")[0].text == "Q: Is there parking?\nA: Yes, behind the main building."


def test_menu_items_are_enabled_menu_sources_in_order():
    k = kb()
    a = k.add_menu("Where is the campus?", "In Colombo.")
    b = k.add_menu("What is LeapGen?", "A startup programme.")
    k.update(b, enabled=False)
    items = k.menu_items()
    assert [(i.id, i.label, i.answer) for i in items] == [(str(a), "Where is the campus?", "In Colombo.")]


def test_editing_a_source_reembeds_only_that_source():
    k = kb()
    sid = k.add_text("Campus", "The library opens at eight.")
    other = k.add_text("LeapGen", "LeapGen helps startups.")
    before = k.db.execute("SELECT id FROM chunks WHERE source_id = ?", (other,))
    k.update(sid, text="The cafeteria serves lunch at noon.")
    assert k.search("cafeteria lunch")[0].source_id == sid
    assert k.db.execute("SELECT id FROM chunks WHERE source_id = ?", (other,)) == before


def test_delete_removes_chunks_and_vectors():
    k = kb()
    sid = k.add_text("Campus", "The library opens at eight.")
    k.delete(sid)
    assert k.list_sources() == []
    assert k.db.execute("SELECT count(*) AS n FROM chunk_vec")[0]["n"] == 0
    assert k.search("library") == []


def test_file_upload_is_extracted_and_body_kept():
    k = kb()
    sid = k.add_file("Guide", "guide.md", b"# Fees\nFees are paid each semester.")
    assert k.list_sources()[0].filename == "guide.md"
    assert "semester" in k.get_body(sid)
    assert k.search("fees semester")[0].heading == "Fees"


def test_bad_file_is_rejected_without_creating_a_source():
    k = kb()
    with pytest.raises(ValueError):
        k.add_file("Photo", "photo.png", b"\x89PNG")
    assert k.list_sources() == []


def test_search_refuses_mixed_models_until_reindex():
    db = Database(":memory:")
    kb(db, name="model-a").add_text("Campus", "The library opens at eight.")
    newer = kb(db, name="model-b")
    assert newer.needs_reindex()
    with pytest.raises(ModelMismatch):
        newer.search("library")
    with pytest.raises(ModelMismatch):
        newer.add_text("More", "More text.")
    assert newer.reindex() == 1
    assert not newer.needs_reindex()
    assert newer.search("library")[0].title == "Campus"


def test_empty_knowledge_base_returns_no_hits():
    assert kb().search("anything") == []


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="downloads the embedding model")
def test_fastembed_bge_small_produces_384_dim_vectors(tmp_path):
    e = FastEmbedder("BAAI/bge-small-en-v1.5", cache_dir=tmp_path)
    assert len(e.query("hello")) == 384
    assert len(e.passages(["a", "b"])) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_kb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.rag.embed'`

- [ ] **Step 3: Implement** `core/rag/embed.py`

```python
"""Embedding models. FastEmbed runs ONNX on the CPU; HashEmbedder is for tests and dev."""

import math
import re
import zlib
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    name: str
    dim: int

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedder:
    dim = 384

    def __init__(self, name: str, cache_dir: Path | None = None) -> None:
        from fastembed import TextEmbedding

        self.name = name
        self._model = TextEmbedding(
            model_name=name, cache_dir=str(cache_dir) if cache_dir else None
        )

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class HashEmbedder:
    """Bag-of-words hashed into 384 buckets. Deterministic, no download."""

    dim = 384

    def __init__(self, name: str = "test-hash") -> None:
        self.name = name

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[zlib.crc32(word.encode()) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def query(self, text: str) -> list[float]:
        return self._vec(text)
```

- [ ] **Step 4: Implement** `core/rag/kb.py`

```python
"""Knowledge base: sources, chunks and vectors in SQLite (baseline 5)."""

import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlite_vec import serialize_float32

from core.controller.phrases import MenuItem
from core.rag.chunk import Chunk, chunk_sections, qa_chunks
from core.rag.embed import Embedder
from core.rag.extract import Section, extract, sections_from_markdown
from core.store.db import Database


class ModelMismatch(Exception):
    """Stored vectors come from a different embedding model; re-index first."""


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    source_id: int
    title: str
    heading: str
    text: str
    score: float


@dataclass(frozen=True)
class SourceInfo:
    id: int
    title: str
    kind: str
    filename: str | None
    enabled: bool
    chunk_count: int
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class KnowledgeBase:
    def __init__(
        self,
        db: Database,
        embedder: Embedder,
        chunk_tokens: int = 250,
        chunk_overlap: int = 40,
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.chunk_tokens = chunk_tokens
        self.chunk_overlap = chunk_overlap

    # ---- adding ----

    def add_text(self, title: str, text: str) -> int:
        return self._add("text", title, text)

    def add_qa(self, title: str, pairs: list[tuple[str, str]]) -> int:
        return self._add("qa", title, json.dumps([[q, a] for q, a in pairs]))

    def add_file(self, title: str, filename: str, data: bytes) -> int:
        suffix = Path(filename).suffix
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"upload{suffix}"
            path.write_bytes(data)
            sections = extract(path)
        body = json.dumps([[s.heading, s.text] for s in sections])
        return self._add("file", title or filename, body, filename=filename)

    def add_menu(self, label: str, answer: str) -> int:
        return self._add("menu", label, answer)

    def _add(self, kind: str, title: str, body: str, filename: str | None = None) -> int:
        chunks = self._chunk(kind, title, body)
        vectors = self.embedder.passages([c.text for c in chunks]) if chunks else []
        now = _now()
        with self.db.transaction() as conn:
            self._require_same_model(conn)
            cur = conn.execute(
                "INSERT INTO sources (title, kind, filename, enabled, chunk_count, body,"
                " created_at, updated_at) VALUES (?, ?, ?, 1, 0, ?, ?, ?)",
                (title, kind, filename, body, now, now),
            )
            source_id = cur.lastrowid
            self._store_chunks(conn, source_id, chunks, vectors)
        return source_id

    # ---- changing ----

    def update(
        self,
        source_id: int,
        *,
        title: str | None = None,
        enabled: bool | None = None,
        text: str | None = None,
        pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        row = self._row(source_id)
        kind = row["kind"]
        new_title = title if title is not None else row["title"]
        if pairs is not None:
            body = json.dumps([[q, a] for q, a in pairs])
        elif text is not None:
            body = text
        else:
            body = row["body"]
        rechunk = body != row["body"] or (kind == "menu" and new_title != row["title"])
        chunks = self._chunk(kind, new_title, body) if rechunk else []
        vectors = self.embedder.passages([c.text for c in chunks]) if chunks else []
        with self.db.transaction() as conn:
            if rechunk:
                self._require_same_model(conn)
                self._delete_chunks(conn, source_id)
                self._store_chunks(conn, source_id, chunks, vectors)
            conn.execute(
                "UPDATE sources SET title = ?, body = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (
                    new_title,
                    body,
                    int(enabled) if enabled is not None else row["enabled"],
                    _now(),
                    source_id,
                ),
            )

    def delete(self, source_id: int) -> None:
        self._row(source_id)
        with self.db.transaction() as conn:
            self._delete_chunks(conn, source_id)
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def reindex(self) -> int:
        """Re-embed every source with the current model. Returns the number of sources."""
        rows = self.db.execute("SELECT id, kind, title, body FROM sources ORDER BY id")
        for row in rows:
            chunks = self._chunk(row["kind"], row["title"], row["body"])
            vectors = self.embedder.passages([c.text for c in chunks]) if chunks else []
            with self.db.transaction() as conn:
                self._delete_chunks(conn, row["id"])
                self._store_chunks(conn, row["id"], chunks, vectors)
        return len(rows)

    # ---- reading ----

    def needs_reindex(self) -> bool:
        rows = self.db.execute(
            "SELECT 1 FROM chunks WHERE embed_model != ? LIMIT 1", (self.embedder.name,)
        )
        return bool(rows)

    def list_sources(self) -> list[SourceInfo]:
        rows = self.db.execute(
            "SELECT id, title, kind, filename, enabled, chunk_count, created_at, updated_at"
            " FROM sources ORDER BY id"
        )
        return [SourceInfo(**{**dict(r), "enabled": bool(r["enabled"])}) for r in rows]

    def get_body(self, source_id: int) -> str:
        return self._row(source_id)["body"]

    def menu_items(self) -> list[MenuItem]:
        rows = self.db.execute(
            "SELECT id, title, body FROM sources WHERE kind = 'menu' AND enabled = 1 ORDER BY id"
        )
        return [MenuItem(str(r["id"]), r["title"], r["body"]) for r in rows]

    def search(self, query: str, k: int = 4) -> list[Hit]:
        if self.needs_reindex():
            raise ModelMismatch("Embedding model changed: re-index the knowledge base.")
        vec = serialize_float32(self.embedder.query(query))
        with self.db.lock:
            nearest = self.db.conn.execute(
                "SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? AND k = ?"
                " ORDER BY distance",
                (vec, k * 5),
            ).fetchall()
            if not nearest:
                return []
            distance = {r["rowid"]: r["distance"] for r in nearest}
            marks = ",".join("?" * len(distance))
            rows = self.db.conn.execute(
                "SELECT c.id, c.source_id, s.title, c.heading, c.text FROM chunks c"
                " JOIN sources s ON s.id = c.source_id"
                f" WHERE s.enabled = 1 AND c.id IN ({marks})",
                list(distance),
            ).fetchall()
        hits = [
            Hit(r["id"], r["source_id"], r["title"], r["heading"], r["text"],
                1.0 - distance[r["id"]])
            for r in rows
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    # ---- helpers ----

    def _chunk(self, kind: str, title: str, body: str) -> list[Chunk]:
        if kind == "text":
            return chunk_sections(
                sections_from_markdown(body), self.chunk_tokens, self.chunk_overlap
            )
        if kind == "file":
            sections = [Section(h, t) for h, t in json.loads(body)]
            return chunk_sections(sections, self.chunk_tokens, self.chunk_overlap)
        if kind == "qa":
            return qa_chunks([(q, a) for q, a in json.loads(body)])
        if kind == "menu":
            return qa_chunks([(title, body)])
        raise ValueError(f"unknown source kind {kind}")

    def _row(self, source_id: int) -> sqlite3.Row:
        rows = self.db.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        if not rows:
            raise KeyError(source_id)
        return rows[0]

    def _require_same_model(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT 1 FROM chunks WHERE embed_model != ? LIMIT 1", (self.embedder.name,)
        ).fetchone()
        if row:
            raise ModelMismatch("Embedding model changed: re-index the knowledge base.")

    def _delete_chunks(self, conn: sqlite3.Connection, source_id: int) -> None:
        conn.execute(
            "DELETE FROM chunk_vec WHERE rowid IN (SELECT id FROM chunks WHERE source_id = ?)",
            (source_id,),
        )
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))

    def _store_chunks(
        self,
        conn: sqlite3.Connection,
        source_id: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> None:
        for ord_, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            cur = conn.execute(
                "INSERT INTO chunks (source_id, ord, heading, text, tokens, embed_model)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (source_id, ord_, chunk.heading, chunk.text, chunk.tokens, self.embedder.name),
            )
            conn.execute(
                "INSERT INTO chunk_vec (rowid, embedding) VALUES (?, ?)",
                (cur.lastrowid, serialize_float32(vector)),
            )
        conn.execute(
            "UPDATE sources SET chunk_count = ? WHERE id = ?", (len(chunks), source_id)
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_kb.py -v`
Expected: PASS (the slow test is skipped). Then once with the real model: `RUN_SLOW=1 uv run pytest tests/test_kb.py -k fastembed -v` → PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/rag/embed.py core/rag/kb.py tests/test_kb.py
git commit -m "<KEY>: add knowledge base with embeddings and vector search"
```

---

### Task 5: Menu from the knowledge base and the ingest CLI

**Files:**
- Modify: `core/controller/machine.py`, `core/runtime.py`
- Create: `core/rag/ingest.py`
- Test: `tests/test_controller.py` (append), `tests/test_runtime.py` (append), `tests/test_ingest.py`

**Interfaces:**
- Consumes: `KnowledgeBase`, `MenuItem`, `Runtime`.
- Produces: `Controller.set_menu(items: list[MenuItem]) -> None` and `Controller.menu`; `Runtime(..., menu_source: Callable[[], list[MenuItem]] | None = None)` and `Runtime.refresh_menu()`; CLI `python -m core.rag.ingest [--config PATH] {list,add-text,add-file,add-qa,add-menu,reindex}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_controller.py`:
```python
from core.controller.phrases import MenuItem


def test_menu_comes_from_set_menu():
    s = Sim()
    s.c.set_menu([MenuItem("7", "Where is IIT?", "In Colombo.")])
    s.to_listening()
    s.ask(5.0, "q")
    s.at(6.0, AnswerFailed("unmatched"))
    assert s.ui("menu", s.out)[0]["items"] == [{"id": "7", "label": "Where is IIT?"}]
    s.end_speech(8.0)
    s.at(9.0, Touch("menu_item", "7"))
    assert s.spoken()[-1] == "In Colombo."
```

Append to `tests/test_runtime.py`:
```python
from core.controller.phrases import MenuItem


def test_runtime_loads_menu_from_source_on_start():
    async def go():
        sent = Collect()
        items = [MenuItem("1", "Label", "Answer")]
        rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0),
                     sent, menu_source=lambda: items)
        rt.start()
        assert rt.c.menu == tuple(items)
        await rt.stop()

    asyncio.run(go())
```

Create `tests/test_ingest.py`:
```python
from core.rag.embed import HashEmbedder
from core.rag.ingest import main
from core.rag.kb import KnowledgeBase
from core.store.db import Database


def test_cli_adds_qa_csv_and_lists(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.rag.ingest.make_embedder", lambda cfg: HashEmbedder())
    csv = tmp_path / "faq.csv"
    csv.write_text("question,answer\nIs there parking?,Yes.\nIs there Wi-Fi?,Yes.\n",
                   encoding="utf-8")
    main(["add-qa", str(csv), "--title", "FAQ"])
    main(["list"])
    out = capsys.readouterr().out
    assert "FAQ" in out and "qa" in out and "2 chunks" in out
    kb = KnowledgeBase(Database(tmp_path / "kiosk.db"), HashEmbedder())
    assert kb.search("parking")[0].title == "FAQ"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_controller.py tests/test_runtime.py tests/test_ingest.py -v`
Expected: FAIL (`AttributeError: 'Controller' object has no attribute 'set_menu'`, `TypeError: ... 'menu_source'`, `ModuleNotFoundError: core.rag.ingest`)

- [ ] **Step 3: Change the controller**

In `core/controller/machine.py`, add `MenuItem` to the phrases import:
```python
from core.controller.phrases import PHRASES, MenuItem, Phrases, is_decline
```
In `Controller.__init__`, after `self.p = phrases`, add:
```python
        self.menu: tuple[MenuItem, ...] = phrases.menu
```
Add the method after `__init__`:
```python
    def set_menu(self, items: list[MenuItem]) -> None:
        self.menu = tuple(items)
```
Replace both uses of `self.p.menu` with `self.menu` (in `_on_touch` and `_fail`).

- [ ] **Step 4: Change the runtime**

In `core/runtime.py`, add the import and the parameter:
```python
from core.controller.phrases import MenuItem
```
Add `menu_source: Callable[[], list[MenuItem]] | None = None,` after `record` in `Runtime.__init__`'s keyword arguments, store it as `self.menu_source = menu_source`, and add:
```python
    def refresh_menu(self) -> None:
        if self.menu_source:
            self.c.set_menu(self.menu_source())
```
Call `self.refresh_menu()` as the first line of `start()`.

- [ ] **Step 5: Implement** `core/rag/ingest.py`

```python
"""Load content into the knowledge base from the command line (before the dashboard exists).

    uv run python -m core.rag.ingest add-file docs/iit/programmes.pdf --title Programmes
    uv run python -m core.rag.ingest add-qa faq.csv --title "Top FAQs"   # columns: question,answer
    uv run python -m core.rag.ingest list
"""

import argparse
import csv
from pathlib import Path

from core.config import load_config
from core.paths import data_dir, models_dir
from core.rag.embed import Embedder, FastEmbedder
from core.rag.kb import KnowledgeBase
from core.store.db import Database


def make_embedder(cfg: dict) -> Embedder:
    return FastEmbedder(cfg["rag"]["embed_model"], cache_dir=models_dir(cfg) / "fastembed")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m core.rag.ingest")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("reindex")
    for name in ("add-text", "add-file", "add-qa"):
        p = sub.add_parser(name)
        p.add_argument("path")
        p.add_argument("--title", default="")
    menu = sub.add_parser("add-menu")
    menu.add_argument("label")
    menu.add_argument("answer")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    kb = KnowledgeBase(
        Database(data_dir(cfg) / "kiosk.db"),
        make_embedder(cfg),
        cfg["rag"]["chunk_tokens"],
        cfg["rag"]["chunk_overlap"],
    )

    if args.cmd == "list":
        for s in kb.list_sources():
            state = "on" if s.enabled else "off"
            print(f"{s.id:4}  {s.kind:5} {state:3}  {s.chunk_count} chunks  {s.title}")
    elif args.cmd == "reindex":
        print(f"re-indexed {kb.reindex()} sources")
    elif args.cmd == "add-menu":
        print(f"added source {kb.add_menu(args.label, args.answer)}")
    else:
        path = Path(args.path)
        title = args.title or path.stem
        if args.cmd == "add-text":
            sid = kb.add_text(title, path.read_text(encoding="utf-8"))
        elif args.cmd == "add-file":
            sid = kb.add_file(title, path.name, path.read_bytes())
        else:
            with path.open(encoding="utf-8", newline="") as f:
                pairs = [(r["question"], r["answer"]) for r in csv.DictReader(f)]
            sid = kb.add_qa(title, pairs)
        print(f"added source {sid}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests, commit**

Run: `uv run pytest -v` → all PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/controller/machine.py core/runtime.py core/rag/ingest.py tests
git commit -m "<KEY>: load touch menu from the knowledge base and add ingest CLI"
```

---

### Task 6: Prompt builder and sentence splitter

**Files:**
- Create: `core/llm/__init__.py` (empty), `core/llm/prompt.py`, `core/llm/sentences.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Hit` (Task 4).
- Produces: `Prompt(system: str, messages: list[dict])` where messages are `{"role": "user"|"assistant", "content": str}`; `build_prompt(question, hits, history, kids, max_sentences) -> Prompt`; `SentenceSplitter` with `.feed(text) -> list[str]` and `.flush() -> list[str]`; `clean_for_speech(text) -> str`.

- [ ] **Step 1: Write the failing tests** `tests/test_llm.py`

```python
from core.llm.prompt import build_prompt
from core.llm.sentences import SentenceSplitter, clean_for_speech
from core.rag.kb import Hit

HITS = [Hit(1, 1, "Programmes", "Computing", "Computing\nIIT offers computing degrees.", 0.8),
        Hit(2, 1, "Programmes", "Business", "Business\nIIT offers business degrees.", 0.7)]


def test_prompt_contains_rules_context_and_history():
    p = build_prompt("How long is it?", HITS, (("What degrees?", "Computing and business."),),
                     kids=False, max_sentences=3)
    assert "Answer only from the context" in p.system
    assert "3 short spoken sentences" in p.system
    assert "Never ask for or repeat personal information" in p.system
    assert "[1] Computing\nIIT offers computing degrees." in p.system
    assert "child" not in p.system
    assert p.messages == [
        {"role": "user", "content": "What degrees?"},
        {"role": "assistant", "content": "Computing and business."},
        {"role": "user", "content": "How long is it?"},
    ]


def test_kids_prompt_adds_kids_rules():
    p = build_prompt("What is a startup?", HITS, (), kids=True, max_sentences=3)
    assert "The visitor is a child" in p.system
    assert "never promise success" in p.system


def feed_all(pieces):
    s = SentenceSplitter()
    out = []
    for piece in pieces:
        out += s.feed(piece)
    return out + s.flush()


def test_sentences_are_released_as_soon_as_complete():
    s = SentenceSplitter()
    assert s.feed("IIT offers computing") == []
    assert s.feed(" degrees. It also") == ["IIT offers computing degrees."]
    assert s.flush() == ["It also"]


def test_abbreviations_and_decimals_split_across_chunks():
    pieces = ["Dr", ". Silva teaches 3", ".5 credit modules. Come", " visit!"]
    assert feed_all(pieces) == ["Dr. Silva teaches 3.5 credit modules.", "Come visit!"]


def test_question_and_exclamation_marks_end_sentences():
    assert feed_all(["Ready? Let's go! Great."]) == ["Ready?", "Let's go!", "Great."]


def test_clean_for_speech_removes_markdown_urls_and_lists():
    text = "- **Computing** at https://iit.ac.lk/courses and `code`"
    assert clean_for_speech(text) == "Computing at and code"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.llm'`

- [ ] **Step 3: Implement** `core/llm/prompt.py`

```python
"""System prompt and messages for one answer (rules from baseline 4.3)."""

from dataclasses import dataclass

from core.rag.kb import Hit

RULES = """You are the IIT visitor assistant on a kiosk at an exhibition. Your replies are spoken aloud.
Rules:
1. Answer only from the context below. If it does not contain the answer, say briefly that you don't have that information.
2. Reply in 2 or {max_sentences} short spoken sentences at most. No lists, no markdown, no URLs, no emojis.
3. Be warm, respectful and professional.
4. Never ask for or repeat personal information such as names, phone numbers, emails or addresses.
5. Only talk about IIT, LeapGen, programmes, campus, research, startups and events. Politely decline anything else."""

KIDS = (
    "The visitor is a child. Use simple words, be encouraging, celebrate their curiosity and "
    "effort, and never promise success. Never ask them for any personal details."
)


@dataclass(frozen=True)
class Prompt:
    system: str
    messages: list[dict]


def build_prompt(
    question: str,
    hits: list[Hit],
    history: tuple[tuple[str, str], ...],
    kids: bool,
    max_sentences: int,
) -> Prompt:
    context = "\n\n".join(f"[{i}] {h.text}" for i, h in enumerate(hits, start=1))
    parts = [RULES.format(max_sentences=max_sentences)]
    if kids:
        parts.append(KIDS)
    parts.append(f"Context:\n{context}")
    messages: list[dict] = []
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})
    return Prompt("\n\n".join(parts), messages)
```

The rule text says "2 or {max_sentences}"; with the default of 3 it reads "2 or 3 short spoken sentences", which is what the first test checks via the substring "3 short spoken sentences".

- [ ] **Step 4: Implement** `core/llm/sentences.py`

```python
"""Splits streamed LLM text into speakable sentences as soon as each one is complete."""

import re

ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "e.g", "i.e", "etc", "vs", "no", "dept"}
END = re.compile(r"[.!?]+[\"')\]]*\s")


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"^\s*([-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceSplitter:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        start = 0
        for m in END.finditer(self._buf):
            candidate = self._buf[start : m.end()]
            last_word = re.findall(r"[\w.]+(?=[.!?]+[\"')\]]*\s$)", candidate)
            if last_word and last_word[-1].lower().rstrip(".") in ABBREVIATIONS:
                continue
            sentence = clean_for_speech(candidate)
            if sentence:
                out.append(sentence)
            start = m.end()
        self._buf = self._buf[start:]
        return out

    def flush(self) -> list[str]:
        rest = clean_for_speech(self._buf)
        self._buf = ""
        return [rest] if rest else []
```

A sentence ends only at `.`, `!` or `?` followed by whitespace, so a stream cut inside "3.5" or "Dr." waits for the next piece before deciding.

- [ ] **Step 5: Run tests, commit**

Run: `uv run pytest tests/test_llm.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/llm tests/test_llm.py
git commit -m "<KEY>: build LLM prompt and split streamed replies into sentences"
```

---

### Task 7: LLM provider adapters

**Files:**
- Create: `core/llm/providers.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Prompt` (Task 6).
- Produces: `LLMError(Exception)`; `LLMProvider` protocol `stream(prompt: Prompt) -> AsyncIterator[str]`; `GeminiProvider`, `AnthropicProvider`, `OpenAIProvider`, each `(client: httpx.AsyncClient, api_key: str, model: str, max_tokens: int, timeout_s: float)`; `make_provider(llm_cfg: dict, api_key: str, client: httpx.AsyncClient) -> LLMProvider`; `DEFAULT_MODELS: dict[str, str]`.

- [ ] **Step 1: Write the failing tests** `tests/test_providers.py`

```python
import asyncio
import json

import httpx
import pytest

from core.llm.prompt import Prompt
from core.llm.providers import LLMError, make_provider

PROMPT = Prompt("SYSTEM", [{"role": "user", "content": "Hi"}])


def sse(events, done=False):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def run(provider_name, response_body, status=200):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["json"] = json.loads(request.content)
        return httpx.Response(status, content=response_body,
                              headers={"content-type": "text/event-stream"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            p = make_provider({"provider": provider_name, "model": "m1", "timeout_s": 6,
                               "max_output_tokens": 200}, "KEY", client)
            return "".join([t async for t in p.stream(PROMPT)])

    return asyncio.run(go()), seen


def test_gemini_streams_text():
    body = sse([{"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]},
                {"candidates": [{"content": {"parts": [{"text": "there."}]}}]}])
    text, seen = run("gemini", body)
    assert text == "Hello there."
    assert seen["url"].endswith("/models/m1:streamGenerateContent?alt=sse")
    assert seen["headers"]["x-goog-api-key"] == "KEY"
    assert seen["json"]["systemInstruction"] == {"parts": [{"text": "SYSTEM"}]}
    assert seen["json"]["contents"] == [{"role": "user", "parts": [{"text": "Hi"}]}]


def test_anthropic_streams_text():
    body = sse([{"type": "message_start"},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi "}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "you."}},
                {"type": "message_stop"}])
    text, seen = run("anthropic", body)
    assert text == "Hi you."
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "KEY"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["json"]["system"] == "SYSTEM"
    assert seen["json"]["stream"] is True
    assert seen["json"]["max_tokens"] == 200


def test_openai_streams_text():
    body = sse([{"choices": [{"delta": {"content": "Yes"}}]},
                {"choices": [{"delta": {"content": "."}}]}], done=True)
    text, seen = run("openai", body)
    assert text == "Yes."
    assert seen["headers"]["authorization"] == "Bearer KEY"
    assert seen["json"]["messages"][0] == {"role": "system", "content": "SYSTEM"}


def test_http_error_raises_llm_error():
    with pytest.raises(LLMError):
        run("anthropic", b'{"error": "bad key"}', status=401)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        make_provider({"provider": "other", "model": "", "timeout_s": 6,
                       "max_output_tokens": 200}, "KEY", httpx.AsyncClient())
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.llm.providers'`

- [ ] **Step 3: Implement** `core/llm/providers.py`

```python
"""Streaming adapters for Gemini, Anthropic and OpenAI (provider chosen in config.toml)."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from core.llm.prompt import Prompt

# Used when [llm] model is empty. Confirm the final choice with IIT before handover.
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4.1-mini",
}


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    def stream(self, prompt: Prompt) -> AsyncIterator[str]: ...


class _Base:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_tokens: int,
        timeout_s: float,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = httpx.Timeout(timeout_s, connect=3.0)

    async def _events(self, url: str, headers: dict, body: dict) -> AsyncIterator[dict]:
        try:
            async with self.client.stream(
                "POST", url, headers=headers, json=body, timeout=self.timeout
            ) as res:
                if res.status_code != 200:
                    detail = (await res.aread())[:200]
                    raise LLMError(f"HTTP {res.status_code}: {detail!r}")
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    if payload:
                        yield json.loads(payload)
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e


class GeminiProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:streamGenerateContent?alt=sse"
        )
        body = {
            "systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]}
                for m in prompt.messages
            ],
            "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": 0.3},
        }
        async for event in self._events(url, {"x-goog-api-key": self.api_key}, body):
            for cand in event.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        yield part["text"]


class AnthropicProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": prompt.system,
            "messages": prompt.messages,
            "stream": True,
        }
        async for event in self._events("https://api.anthropic.com/v1/messages", headers, body):
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
            elif event.get("type") == "error":
                raise LLMError(str(event.get("error")))


class OpenAIProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        headers = {"authorization": f"Bearer {self.api_key}"}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": prompt.system}, *prompt.messages],
            "max_completion_tokens": self.max_tokens,
            "stream": True,
        }
        url = "https://api.openai.com/v1/chat/completions"
        async for event in self._events(url, headers, body):
            for choice in event.get("choices", []):
                text = choice.get("delta", {}).get("content")
                if text:
                    yield text


PROVIDERS = {"gemini": GeminiProvider, "anthropic": AnthropicProvider, "openai": OpenAIProvider}


def make_provider(llm_cfg: dict, api_key: str, client: httpx.AsyncClient) -> LLMProvider:
    name = llm_cfg["provider"]
    if name not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {name!r}; use gemini, anthropic or openai.")
    return PROVIDERS[name](
        client,
        api_key,
        llm_cfg["model"] or DEFAULT_MODELS[name],
        llm_cfg["max_output_tokens"],
        llm_cfg["timeout_s"],
    )
```

- [ ] **Step 4: Run tests, commit**

Run: `uv run pytest tests/test_providers.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/llm/providers.py tests/test_providers.py
git commit -m "<KEY>: add streaming adapters for Gemini, Anthropic and OpenAI"
```

---

### Task 8: RAG answerer

**Files:**
- Modify: `core/answer.py`
- Test: `tests/test_rag_answerer.py`

**Interfaces:**
- Consumes: `KnowledgeBase.search`, `ModelMismatch`, `build_prompt`, `SentenceSplitter`, `LLMProvider`, `LLMError`, M1 `AnswerError`.
- Produces: `RagAnswerer(kb, llm, *, top_k, min_score, max_sentences, on_unmatched=None)` with mutable `min_score` and `offline`, implementing M1's `Answerer` protocol.

- [ ] **Step 1: Write the failing tests** `tests/test_rag_answerer.py`

```python
import asyncio

import pytest

from core.answer import AnswerError, RagAnswerer
from core.llm.providers import LLMError
from core.rag.embed import HashEmbedder
from core.rag.kb import KnowledgeBase
from core.store.db import Database


class FakeLLM:
    def __init__(self, pieces, fail_after=None):
        self.pieces = pieces
        self.fail_after = fail_after
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        for i, piece in enumerate(self.pieces):
            if self.fail_after is not None and i == self.fail_after:
                raise LLMError("connection dropped")
            yield piece


def make(llm, min_score=0.2):
    kb = KnowledgeBase(Database(":memory:"), HashEmbedder())
    kb.add_text("Programmes", "IIT offers computing and business degrees in Colombo.")
    unmatched = []
    ans = RagAnswerer(kb, llm, top_k=4, min_score=min_score, max_sentences=3,
                      on_unmatched=unmatched.append)
    return ans, unmatched


def collect(ans, question, history=()):
    async def go():
        return [s async for s in ans.answer(question, history, False)]

    return asyncio.run(go())


def test_matching_question_streams_capped_sentences():
    llm = FakeLLM(["IIT offers computing", " degrees. It also offers business. ",
                   "Both are in Colombo. Extra sentence."])
    ans, _ = make(llm)
    assert collect(ans, "What degrees does IIT offer?") == [
        "IIT offers computing degrees.", "It also offers business.", "Both are in Colombo."]
    assert "[1] IIT offers computing and business degrees" in llm.prompts[0].system


def test_unmatched_question_raises_and_is_reported():
    ans, unmatched = make(FakeLLM(["never used."]), min_score=0.9)
    with pytest.raises(AnswerError) as e:
        collect(ans, "What is the weather on Mars?")
    assert e.value.kind == "unmatched"
    assert unmatched == ["What is the weather on Mars?"]


def test_llm_error_before_any_sentence_is_offline():
    ans, _ = make(FakeLLM(["never"], fail_after=0))
    with pytest.raises(AnswerError) as e:
        collect(ans, "What degrees does IIT offer?")
    assert e.value.kind == "offline"


def test_llm_error_after_first_sentence_ends_turn_quietly():
    ans, _ = make(FakeLLM(["IIT offers degrees. ", "More"], fail_after=1))
    assert collect(ans, "What degrees does IIT offer?") == ["IIT offers degrees."]


def test_short_follow_up_is_searched_with_previous_question():
    ans, _ = make(FakeLLM(["They take three years."]))
    seen = []
    real = ans.kb.search
    ans.kb.search = lambda q, k: seen.append(q) or real(q, k)
    collect(ans, "How long?", history=(("What degrees does IIT offer?", "Computing."),))
    assert seen == ["What degrees does IIT offer? How long?"]


def test_offline_flag_raises_offline():
    ans, _ = make(FakeLLM(["x."]))
    ans.offline = True
    with pytest.raises(AnswerError) as e:
        collect(ans, "What degrees does IIT offer?")
    assert e.value.kind == "offline"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rag_answerer.py -v`
Expected: FAIL with `ImportError: cannot import name 'RagAnswerer'`

- [ ] **Step 3: Implement** — append to `core/answer.py`

Add imports at the top:
```python
import logging
from collections.abc import Callable

from core.llm.prompt import build_prompt
from core.llm.providers import LLMError, LLMProvider
from core.llm.sentences import SentenceSplitter
from core.rag.kb import KnowledgeBase, ModelMismatch

log = logging.getLogger("kiosk.answer")
```

Append the class:
```python
class RagAnswerer:
    """Search the knowledge base, refuse below the threshold, stream sentences from the LLM."""

    def __init__(
        self,
        kb: KnowledgeBase,
        llm: LLMProvider,
        *,
        top_k: int,
        min_score: float,
        max_sentences: int,
        on_unmatched: Callable[[str], None] | None = None,
    ) -> None:
        self.kb = kb
        self.llm = llm
        self.top_k = top_k
        self.min_score = min_score
        self.max_sentences = max_sentences
        self.on_unmatched = on_unmatched
        self.offline = False

    async def answer(
        self, question: str, history: tuple[tuple[str, str], ...], kids: bool
    ) -> AsyncIterator[str]:
        if self.offline:
            raise AnswerError("offline")
        query = question
        if history and len(question.split()) < 5:
            query = f"{history[-1][0]} {question}"
        try:
            hits = await asyncio.to_thread(self.kb.search, query, self.top_k)
        except ModelMismatch:
            log.error("knowledge base needs re-indexing")
            raise AnswerError("offline") from None
        if not hits or hits[0].score < self.min_score:
            if self.on_unmatched:
                self.on_unmatched(question)
            raise AnswerError("unmatched")
        prompt = build_prompt(question, hits, history, kids, self.max_sentences)
        splitter = SentenceSplitter()
        spoken = 0
        try:
            async for piece in self.llm.stream(prompt):
                for sentence in splitter.feed(piece):
                    yield sentence
                    spoken += 1
                    if spoken >= self.max_sentences:
                        return
            for sentence in splitter.flush()[: self.max_sentences - spoken]:
                yield sentence
        except LLMError as e:
            log.warning("LLM failed after %d sentences: %s", spoken, e)
            if spoken == 0:
                raise AnswerError("offline") from e
```

- [ ] **Step 4: Run tests, commit**

Run: `uv run pytest tests/test_rag_answerer.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/answer.py tests/test_rag_answerer.py
git commit -m "<KEY>: answer questions from the knowledge base through the LLM"
```

---

### Task 9: Piper speech and the model downloader

**Files:**
- Create: `core/tts_piper.py`, `models/download.py`, `models/README.md`
- Test: `tests/test_piper.py`

**Interfaces:**
- Consumes: M1 `SpeechOutput` protocol.
- Produces: `PiperSpeech(model_path: Path)` with `sample_rate` and `async synthesize(text) -> AsyncIterator[bytes]`; `python -m models.download [--dest DIR] [--record]`; `models/checksums.sha256`.

- [ ] **Step 1: Confirm the piper-tts API on this machine**

Run:
```bash
uv run python -c "import piper, inspect; from piper import PiperVoice; print(inspect.signature(PiperVoice.synthesize))"
```
Expected: a signature taking `text` (piper-tts 1.3+), whose results are `AudioChunk` objects with `audio_int16_bytes` and `sample_rate`. If the installed version differs, pin `piper-tts==1.3.0` in `pyproject.toml` and re-run.

- [ ] **Step 2: Write `models/download.py`**

```python
"""Download model files into the models directory and verify their checksums.

    uv run python -m models.download                 # verify against models/checksums.sha256
    uv run python -m models.download --record        # first trusted download: write checksums
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import httpx

PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"
FILES = {
    "piper/en_US-lessac-medium.onnx": f"{PIPER}/en_US-lessac-medium.onnx",
    "piper/en_US-lessac-medium.onnx.json": f"{PIPER}/en_US-lessac-medium.onnx.json",
}
CHECKSUMS = Path(__file__).with_name("checksums.sha256")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as res:
        res.raise_for_status()
        with tmp.open("wb") as f:
            for block in res.iter_bytes():
                f.write(block)
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m models.download")
    parser.add_argument("--dest", default=os.environ.get("KIOSK_MODELS_DIR", "models"))
    parser.add_argument("--record", action="store_true", help="write checksums.sha256")
    args = parser.parse_args(argv)
    dest = Path(args.dest)

    expected = {}
    if CHECKSUMS.exists():
        for line in CHECKSUMS.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            expected[name] = digest

    recorded, bad = [], []
    for name, url in FILES.items():
        path = dest / name
        if not path.exists():
            print(f"downloading {name}")
            download(url, path)
        digest = sha256(path)
        recorded.append(f"{digest}  {name}")
        if not args.record and expected.get(name) != digest:
            bad.append(name)

    if args.record:
        CHECKSUMS.write_text("\n".join(recorded) + "\n")
        print(f"wrote {CHECKSUMS}")
    elif bad:
        print(f"checksum mismatch or not recorded: {', '.join(bad)}", file=sys.stderr)
        return 1
    print("models ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Create an empty `models/__init__.py` so `python -m models.download` resolves.

`models/README.md`:
```markdown
# Models

Model files are not in git. `python -m models.download` fetches them into
`$KIOSK_MODELS_DIR` (default `./models`) and checks them against `checksums.sha256`.

The first time, on a trusted network, run with `--record` and commit the updated
`checksums.sha256`. FastEmbed downloads its own model into `<models>/fastembed`
the first time the knowledge base starts.
```

- [ ] **Step 3: Download and record checksums**

Run: `uv run python -m models.download --record`
Expected: two files under `models/piper/`, and `models/checksums.sha256` written with two lines.

- [ ] **Step 4: Write the failing test** `tests/test_piper.py`

```python
import asyncio
from pathlib import Path

import pytest

MODEL = Path("models/piper/en_US-lessac-medium.onnx")


@pytest.mark.skipif(not MODEL.exists(), reason="run python -m models.download first")
def test_piper_streams_pcm16_audio():
    from core.tts_piper import PiperSpeech

    speech = PiperSpeech(MODEL)

    async def go():
        return [chunk async for chunk in speech.synthesize("Welcome to IIT.")]

    chunks = asyncio.run(go())
    total = sum(len(c) for c in chunks)
    assert speech.sample_rate == 22050
    assert total % 2 == 0
    assert total / 2 / speech.sample_rate > 0.5
```

- [ ] **Step 5: Run to verify it fails**

Run: `uv run pytest tests/test_piper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.tts_piper'`

- [ ] **Step 6: Implement** `core/tts_piper.py`

```python
"""Piper text to speech (baseline 6). Synthesis runs in a thread; chunks stream as ready."""

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

from piper import PiperVoice


class PiperSpeech:
    def __init__(self, model_path: Path) -> None:
        self.voice = PiperVoice.load(str(model_path))
        self.sample_rate = self.voice.config.sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        stop = threading.Event()

        def work() -> None:
            try:
                for chunk in self.voice.synthesize(text):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.audio_int16_bytes)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except BaseException as e:  # surfaced to the caller below
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=work, name="piper", daemon=True).start()
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop.set()
```

- [ ] **Step 7: Run tests, commit**

Run: `uv run pytest tests/test_piper.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/tts_piper.py models/__init__.py models/download.py models/README.md models/checksums.sha256 tests/test_piper.py
git commit -m "<KEY>: speak with Piper and download models with checksums"
```

---

### Task 10: Wire services into the app and add the RAG eval tool

**Files:**
- Create: `core/services.py`, `tools/__init__.py` (empty), `tools/rag_eval.py`, `tests/rag_questions.toml`
- Modify: `core/app.py`, `tests/test_app.py`, `README.md`
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `Services(db, kb, events, unmatched, speech, answerer)`; `build_services(cfg, *, dev=False, embedder=None, env=None) -> Services`; `create_app(cfg, dev=False, services=None)`; `python -m tools.rag_eval`.

- [ ] **Step 1: Write the failing tests** `tests/test_services.py`

```python
import pytest

from core.answer import CannedAnswerer, RagAnswerer
from core.config import load_config
from core.rag.embed import HashEmbedder
from core.services import build_services
from core.speech import FakeSpeech


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))
    return load_config("config.toml")


def test_dev_without_key_or_voice_uses_fakes_and_seeds_menu(cfg):
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    assert isinstance(s.answerer, CannedAnswerer)
    assert isinstance(s.speech, FakeSpeech)
    assert [m.label for m in s.kb.menu_items()][:1] == ["What can I study at IIT?"]


def test_menu_is_seeded_only_once(cfg):
    build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    assert len(s.kb.menu_items()) == 4


def test_key_gives_rag_answerer(cfg):
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={"LLM_API_KEY": "k"})
    assert isinstance(s.answerer, RagAnswerer)


def test_production_refuses_to_start_without_key(cfg):
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        build_services(cfg, dev=False, embedder=HashEmbedder(), env={})
```

Update `tests/test_app.py`: replace its `app()` helper and add a fixture:
```python
import pytest

from core.rag.embed import HashEmbedder
from core.services import build_services


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))


def app(dev=True):
    cfg = load_config(ROOT / "config.toml")
    services = build_services(cfg, dev=dev, embedder=HashEmbedder(), env={})
    return create_app(cfg, dev=dev, services=services)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_services.py tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services'`

- [ ] **Step 3: Implement** `core/services.py`

```python
"""Builds the real (or, in dev, stand-in) components from config."""

import logging
from dataclasses import dataclass

import httpx

from core.answer import Answerer, CannedAnswerer, RagAnswerer
from core.controller.phrases import PHRASES
from core.llm.providers import make_provider
from core.paths import data_dir, models_dir
from core.rag.embed import Embedder, FastEmbedder
from core.rag.kb import KnowledgeBase
from core.secrets import load_env
from core.speech import FakeSpeech, SpeechOutput
from core.store.db import Database
from core.store.events import EventLog, UnmatchedLog

log = logging.getLogger("kiosk.services")


@dataclass
class Services:
    db: Database
    kb: KnowledgeBase
    events: EventLog
    unmatched: UnmatchedLog
    speech: SpeechOutput
    answerer: Answerer


def build_services(
    cfg: dict,
    *,
    dev: bool = False,
    embedder: Embedder | None = None,
    env: dict[str, str] | None = None,
) -> Services:
    data, models = data_dir(cfg), models_dir(cfg)
    env = load_env(data / ".env") if env is None else env
    rag, llm_cfg, privacy = cfg["rag"], cfg["llm"], cfg["privacy"]

    db = Database(data / "kiosk.db")
    events = EventLog(db)
    unmatched = UnmatchedLog(
        db, privacy["log_unmatched_questions"], privacy["unmatched_retention_days"]
    )
    unmatched.purge()

    embedder = embedder or FastEmbedder(rag["embed_model"], cache_dir=models / "fastembed")
    kb = KnowledgeBase(db, embedder, rag["chunk_tokens"], rag["chunk_overlap"])
    if not any(s.kind == "menu" for s in kb.list_sources()):
        for item in PHRASES.menu:
            kb.add_menu(item.label, item.answer)

    key = env.get("LLM_API_KEY", "")
    answerer: Answerer
    if key:
        answerer = RagAnswerer(
            kb,
            make_provider(llm_cfg, key, httpx.AsyncClient()),
            top_k=rag["top_k"],
            min_score=rag["min_score"],
            max_sentences=llm_cfg["max_sentences"],
            on_unmatched=unmatched.add,
        )
    elif dev:
        log.warning("LLM_API_KEY not set: using canned answers")
        answerer = CannedAnswerer()
    else:
        raise RuntimeError(f"LLM_API_KEY missing: add it to {data / '.env'}")

    voice = models / "piper" / f"{cfg['voice']['tts_voice']}.onnx"
    speech: SpeechOutput
    if voice.exists():
        from core.tts_piper import PiperSpeech

        speech = PiperSpeech(voice)
    elif dev:
        log.warning("Piper voice %s missing: using placeholder audio", voice)
        speech = FakeSpeech()
    else:
        raise RuntimeError(f"Piper voice missing: {voice} (run python -m models.download)")

    return Services(db, kb, events, unmatched, speech, answerer)
```

- [ ] **Step 4: Update** `core/app.py`

Replace the imports of `CannedAnswerer`, `FakeSpeech` with:
```python
from core.services import Services, build_services
from core.store.events import SessionRecorder
```
Change the signature and runtime construction:
```python
def create_app(cfg: dict, dev: bool = False, services: Services | None = None) -> FastAPI:
    services = services or build_services(cfg, dev=dev)
    hub = Hub()
    music_url = cfg["ui"].get("music_url")
    music = {"url": music_url, "volume": cfg["audio"]["music_volume"]} if music_url else None
    runtime = Runtime(
        Controller(ControllerConfig.from_config(cfg)),
        services.speech,
        services.answerer,
        hub.broadcast,
        dev=dev,
        music=music,
        record=SessionRecorder(services.events),
        menu_source=services.kb.menu_items,
    )
```
Keep the rest of `create_app` unchanged, and add `app.state.services = services` next to `app.state.runtime = runtime`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Write the eval tool** `tools/rag_eval.py`

```python
"""Tune rag.min_score: run the test questions against the real knowledge base.

    uv run python -m tools.rag_eval            # uses tests/rag_questions.toml

Each IIT question names the source title that should match. Off-topic questions
should score below the threshold. The tool suggests the midpoint between the
weakest correct match and the strongest off-topic match.
"""

import argparse
import tomllib

from core.config import load_config
from core.paths import data_dir
from core.rag.ingest import make_embedder
from core.rag.kb import KnowledgeBase
from core.store.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.rag_eval")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--questions", default="tests/rag_questions.toml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    kb = KnowledgeBase(Database(data_dir(cfg) / "kiosk.db"), make_embedder(cfg))
    with open(args.questions, "rb") as f:
        spec = tomllib.load(f)

    correct_scores, misses = [], 0
    for q in spec.get("question", []):
        hits = kb.search(q["text"], cfg["rag"]["top_k"])
        top = hits[0] if hits else None
        ok = top is not None and top.title == q["source"]
        score = top.score if top else 0.0
        if ok:
            correct_scores.append(score)
        else:
            misses += 1
        got = top.title if top else "-"
        print(f"{'ok ' if ok else 'MISS'} {score:.3f}  {q['text']}  -> {got}")

    off_scores = []
    for q in spec.get("off_topic", []):
        hits = kb.search(q["text"], 1)
        score = hits[0].score if hits else 0.0
        off_scores.append(score)
        print(f"off  {score:.3f}  {q['text']}")

    print(f"\n{len(correct_scores)} matched, {misses} missed")
    if correct_scores and off_scores:
        low, high = min(correct_scores), max(off_scores)
        print(f"weakest correct {low:.3f}, strongest off-topic {high:.3f}")
        if low > high:
            print(f"suggested rag.min_score = {(low + high) / 2:.2f}")
        else:
            print("ranges overlap: improve content for the missed or weak questions first")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`tests/rag_questions.toml`:
```toml
# Threshold tuning for rag.min_score (baseline 5.5).
# When IIT's approved content and top 20 FAQs arrive (due 16 Oct), add one
# [[question]] per FAQ with the title of the source that should answer it.
#
# [[question]]
# text = "What undergraduate programmes does IIT offer?"
# source = "Programmes"

[[off_topic]]
text = "What's the weather like on Mars?"

[[off_topic]]
text = "Can you recommend a good pizza place?"

[[off_topic]]
text = "Who won the cricket match yesterday?"

[[off_topic]]
text = "How do I fix my car's engine?"

[[off_topic]]
text = "Tell me a joke about cats."
```

- [ ] **Step 7: Manual check**

1. Put a real key in `.data/.env` (`LLM_API_KEY=...`; `.data/` is git-ignored).
2. `uv run python -m core.rag.ingest add-text README.md --title "Readme"` (any text works for now).
3. `uv run python -m core --dev`, open http://localhost:8765/?dev=1, then Approach and ask "What is this project?".
   Expected: a Piper voice answers in at most 3 sentences, the mouth follows the voice, then the bot is back to Listening.
4. Ask "What's the weather on Mars?". Expected: "Sorry, I don't have that information" and the menu sheet.
5. `sqlite3 .data/kiosk.db "select type, count(*) from events group by type"` shows encounter, greeting, question, answered or unmatched counts.

- [ ] **Step 8: Update README and commit**

Add to `README.md` under "Run on a laptop":
````markdown
First time only:

```bash
uv run python -m models.download          # Piper voice
echo "LLM_API_KEY=your-key" > .data/.env   # never commit this file
uv run python -m core.rag.ingest add-file path/to/content.pdf --title "Programmes"
```

Without a key or voice, `--dev` falls back to canned answers and placeholder audio.
````

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/services.py core/app.py tools tests README.md
git commit -m "<KEY>: wire knowledge base, LLM and Piper into the kiosk"
```

---

## After M2

Merge to `dev` by pull request. Content from IIT goes in with `core.rag.ingest`; once the 20 FAQs arrive, add them to `tests/rag_questions.toml` and run `python -m tools.rag_eval` to set `rag.min_score`.
