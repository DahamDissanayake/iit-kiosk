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
