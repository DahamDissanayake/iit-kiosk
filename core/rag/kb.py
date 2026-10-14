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
            Hit(
                r["id"],
                r["source_id"],
                r["title"],
                r["heading"],
                r["text"],
                1.0 - distance[r["id"]],
            )
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
        conn.execute("UPDATE sources SET chunk_count = ? WHERE id = ?", (len(chunks), source_id))
