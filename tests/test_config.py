from pathlib import Path

from core.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_has_controller_and_ui_settings():
    cfg = load_config(ROOT / "config.toml")
    assert cfg["vision"]["dwell_s"] == 1.5
    assert cfg["engagement"]["greet_cooldown_s"] == 20
    assert cfg["llm"]["timeout_s"] == 6
    assert cfg["ui"]["port"] == 8765
