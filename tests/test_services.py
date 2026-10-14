import pytest

from core.answer import CannedAnswerer, RagAnswerer
from core.config import load_config
from core.rag.embed import HashEmbedder
from core.services import build_services
from core.speech import FakeSpeech


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))
    return load_config("config.toml")


def test_dev_without_key_or_voice_uses_fakes_and_seeds_menu(cfg):
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    assert isinstance(s.answerer, CannedAnswerer)
    assert isinstance(s.speech, FakeSpeech)
    assert [m.label for m in s.kb.menu_items()][:1] == ["What can I study at IIT?"]


def test_menu_is_seeded_only_once(cfg):
    build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={})
    assert len(s.kb.menu_items()) == 4


def test_key_gives_rag_answerer(cfg):
    s = build_services(cfg, dev=True, embedder=HashEmbedder(), env={"LLM_API_KEY": "k"})
    assert isinstance(s.answerer, RagAnswerer)


def test_production_refuses_to_start_without_key(cfg):
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        build_services(cfg, dev=False, embedder=HashEmbedder(), env={})
