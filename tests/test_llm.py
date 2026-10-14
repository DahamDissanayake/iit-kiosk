from core.llm.prompt import build_prompt
from core.llm.sentences import SentenceSplitter, clean_for_speech
from core.rag.kb import Hit

HITS = [
    Hit(1, 1, "Programmes", "Computing", "Computing\nIIT offers computing degrees.", 0.8),
    Hit(2, 1, "Programmes", "Business", "Business\nIIT offers business degrees.", 0.7),
]


def test_prompt_contains_rules_context_and_history():
    p = build_prompt(
        "How long is it?",
        HITS,
        (("What degrees?", "Computing and business."),),
        kids=False,
        max_sentences=3,
    )
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


def test_rupee_abbreviation_does_not_split_a_sentence():
    pieces = ["Fees are Rs", ". 150,000 per year. That includes", " the library."]
    assert feed_all(pieces) == ["Fees are Rs. 150,000 per year.", "That includes the library."]
