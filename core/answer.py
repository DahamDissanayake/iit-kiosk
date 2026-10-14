"""Answer source interface and the M1 stand-in (RAG + LLM replace it in M2)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol


class AnswerError(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # "unmatched" or "offline"


class Answerer(Protocol):
    def answer(
        self, question: str, history: tuple[tuple[str, str], ...], kids: bool
    ) -> AsyncIterator[str]:
        """Yield spoken sentences; raise AnswerError when there is no answer."""


class CannedAnswerer:
    """Echoes the question. Set `offline` to exercise the fallback menu."""

    def __init__(self, delay_s: float = 0.8) -> None:
        self.delay_s = delay_s
        self.offline = False

    async def answer(
        self, question: str, history: tuple[tuple[str, str], ...], kids: bool
    ) -> AsyncIterator[str]:
        await asyncio.sleep(self.delay_s)
        if self.offline:
            raise AnswerError("offline")
        yield f"You asked: {question.strip().rstrip('?.!')}."
        await asyncio.sleep(self.delay_s / 2)
        yield "Real answers from the knowledge base arrive in the next milestone."
