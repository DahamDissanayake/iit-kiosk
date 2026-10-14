"""Answer sources: the interface, the dev stand-in, and the knowledge-base + LLM answerer."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Protocol

from core.llm.prompt import build_prompt
from core.llm.providers import LLMError, LLMProvider
from core.llm.sentences import SentenceSplitter
from core.rag.kb import KnowledgeBase, ModelMismatch

log = logging.getLogger("kiosk.answer")


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
            # aclosing: stopping at the sentence cap must close the HTTP stream, or the model keeps
            # generating (and billing) a reply nobody will hear.
            async with aclosing(self.llm.stream(prompt)) as stream:
                async for piece in stream:
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
