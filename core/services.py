"""Builds the real (or, in dev, stand-in) components from config."""

import logging
from dataclasses import dataclass

import httpx

from core.answer import Answerer, CannedAnswerer, RagAnswerer
from core.controller.phrases import PHRASES
from core.llm.providers import make_provider
from core.paths import data_dir, models_dir
from core.rag.embed import Embedder, FastEmbedder
from core.rag.kb import KnowledgeBase
from core.secrets import load_env
from core.speech import FakeSpeech, SpeechOutput
from core.store.db import Database
from core.store.events import EventLog, UnmatchedLog

log = logging.getLogger("kiosk.services")


@dataclass
class Services:
    db: Database
    kb: KnowledgeBase
    events: EventLog
    unmatched: UnmatchedLog
    speech: SpeechOutput
    answerer: Answerer


def build_services(
    cfg: dict,
    *,
    dev: bool = False,
    embedder: Embedder | None = None,
    env: dict[str, str] | None = None,
) -> Services:
    data, models = data_dir(cfg), models_dir(cfg)
    env = load_env(data / ".env") if env is None else env
    rag, llm_cfg, privacy = cfg["rag"], cfg["llm"], cfg["privacy"]

    db = Database(data / "kiosk.db")
    events = EventLog(db)
    unmatched = UnmatchedLog(
        db, privacy["log_unmatched_questions"], privacy["unmatched_retention_days"]
    )
    unmatched.purge()

    embedder = embedder or FastEmbedder(rag["embed_model"], cache_dir=models / "fastembed")
    kb = KnowledgeBase(db, embedder, rag["chunk_tokens"], rag["chunk_overlap"])
    if not any(s.kind == "menu" for s in kb.list_sources()):
        for item in PHRASES.menu:
            kb.add_menu(item.label, item.answer)

    key = env.get("LLM_API_KEY", "")
    answerer: Answerer
    if key:
        answerer = RagAnswerer(
            kb,
            make_provider(llm_cfg, key, httpx.AsyncClient()),
            top_k=rag["top_k"],
            min_score=rag["min_score"],
            max_sentences=llm_cfg["max_sentences"],
            on_unmatched=unmatched.add,
        )
    elif dev:
        log.warning("LLM_API_KEY not set: using canned answers")
        answerer = CannedAnswerer()
    else:
        raise RuntimeError(f"LLM_API_KEY missing: add it to {data / '.env'}")

    voice = models / "piper" / f"{cfg['voice']['tts_voice']}.onnx"
    speech: SpeechOutput
    if voice.exists():
        from core.tts_piper import PiperSpeech

        speech = PiperSpeech(voice)
    elif dev:
        log.warning("Piper voice %s missing: using placeholder audio", voice)
        speech = FakeSpeech()
    else:
        raise RuntimeError(f"Piper voice missing: {voice} (run python -m models.download)")

    return Services(db, kb, events, unmatched, speech, answerer)
