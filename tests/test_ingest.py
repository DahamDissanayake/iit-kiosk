from core.rag.embed import HashEmbedder
from core.rag.ingest import main
from core.rag.kb import KnowledgeBase
from core.store.db import Database


def test_cli_adds_qa_csv_and_lists(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.rag.ingest.make_embedder", lambda cfg: HashEmbedder())
    csv = tmp_path / "faq.csv"
    csv.write_text(
        "question,answer\nIs there parking?,Yes.\nIs there Wi-Fi?,Yes.\n", encoding="utf-8"
    )
    main(["add-qa", str(csv), "--title", "FAQ"])
    main(["list"])
    out = capsys.readouterr().out
    assert "FAQ" in out and "qa" in out and "2 chunks" in out
    kb = KnowledgeBase(Database(tmp_path / "kiosk.db"), HashEmbedder())
    assert kb.search("parking")[0].title == "FAQ"
