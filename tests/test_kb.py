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
    k.add_qa(
        "FAQ",
        [
            ("Is there parking?", "Yes, behind the main building."),
            ("Is there Wi-Fi?", "Yes, for registered students."),
        ],
    )
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
    assert [(i.id, i.label, i.answer) for i in items] == [
        (str(a), "Where is the campus?", "In Colombo.")
    ]


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


def test_menu_items_are_not_matched_by_voice_questions_by_default():
    k = kb()
    k.add_text("Programmes", "IIT offers BSc degrees in computing and business.")
    menu_id = k.add_menu("What's on today?", "Placeholder answer about today's events.")
    assert all(h.source_id != menu_id for h in k.search("what is on today"))
    assert k.search("what is on today", include_menu=True)[0].source_id == menu_id
