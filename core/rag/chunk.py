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
