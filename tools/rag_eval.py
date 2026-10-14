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
