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
    ans = RagAnswerer(
        kb, llm, top_k=4, min_score=min_score, max_sentences=3, on_unmatched=unmatched.append
    )
    return ans, unmatched


def collect(ans, question, history=()):
    async def go():
        return [s async for s in ans.answer(question, history, False)]

    return asyncio.run(go())


def test_matching_question_streams_capped_sentences():
    llm = FakeLLM(
        [
            "IIT offers computing",
            " degrees. It also offers business. ",
            "Both are in Colombo. Extra sentence.",
        ]
    )
    ans, _ = make(llm)
    assert collect(ans, "What degrees does IIT offer?") == [
        "IIT offers computing degrees.",
        "It also offers business.",
        "Both are in Colombo.",
    ]
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


def test_llm_stream_is_closed_when_the_sentence_cap_is_reached():
    closed = []

    class TrackedLLM:
        async def stream(self, prompt):
            try:
                for piece in ["One. ", "Two. ", "Three. ", "Four. ", "Five. "]:
                    yield piece
            finally:
                closed.append(True)

    ans, _ = make(TrackedLLM())

    async def go():
        sentences = [s async for s in ans.answer("What degrees does IIT offer?", (), False)]
        return sentences, list(closed)  # checked at once, before any garbage collection

    sentences, closed_at_end = asyncio.run(go())
    assert sentences == ["One.", "Two.", "Three."]
    assert closed_at_end == [True]
