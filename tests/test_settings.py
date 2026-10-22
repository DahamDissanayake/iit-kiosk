import asyncio

import pytest

from core.admin.apply import SettingsApplier
from core.admin.settings import Settings
from core.answer import CannedAnswerer
from core.config import load_config
from core.controller.machine import Controller, ControllerConfig
from core.runtime import Runtime
from core.speech import FakeSpeech
from core.store.db import Database

CFG = load_config("config.toml")


def test_defaults_come_from_config():
    s = Settings(Database(":memory:"), CFG)
    values = s.all()
    assert values["greet_cooldown_s"] == CFG["engagement"]["greet_cooldown_s"]
    assert values["min_score"] == CFG["rag"]["min_score"]
    assert values["log_unmatched_questions"] is False


def test_update_persists_and_overrides():
    db = Database(":memory:")
    Settings(db, CFG).update({"greet_cooldown_s": 45, "quiet_mode": True})
    values = Settings(db, CFG).all()
    assert values["greet_cooldown_s"] == 45
    assert values["quiet_mode"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"volume": 5},
        {"greet_cooldown_s": -1},
        {"greet_cooldown_s": "ten"},
        {"quiet_mode": "yes"},
        {"unknown": 1},
    ],
)
def test_invalid_values_are_rejected(changes):
    with pytest.raises(ValueError):
        Settings(Database(":memory:"), CFG).update(changes)


def test_invalid_update_saves_nothing():
    db = Database(":memory:")
    s = Settings(db, CFG)
    with pytest.raises(ValueError):
        s.update({"greet_cooldown_s": 30, "volume": 9})
    assert s.all()["greet_cooldown_s"] == CFG["engagement"]["greet_cooldown_s"]


class FakeServices:
    def __init__(self):
        self.answerer = CannedAnswerer()
        self.answerer.min_score = 0.5

        class U:
            enabled = False

        self.unmatched = U()


def test_applier_updates_controller_answers_privacy_music_and_volume():
    sent, volumes = [], []

    async def send(msg):
        sent.append(msg)

    rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(), send)
    services = FakeServices()
    applier = SettingsApplier(rt, services, "music.mp3", set_volume=volumes.append)
    values = {
        **Settings(Database(":memory:"), CFG).all(),
        "greet_cooldown_s": 40,
        "dwell_s": 2.0,
        "kids_default": True,
        "min_score": 0.6,
        "log_unmatched_questions": True,
        "quiet_mode": True,
        "volume": 0.8,
    }
    asyncio.run(applier.apply(values))
    assert rt.c.cfg.greet_cooldown_s == 40
    assert rt.c.cfg.dwell_s == 2.0
    assert rt.c.cfg.kids_default is True
    assert services.answerer.min_score == 0.6
    assert services.unmatched.enabled is True
    assert {"type": "music", "url": "", "volume": values["music_volume"]} in sent
    assert volumes == [0.4]


def test_applier_announces_privacy_notice():
    sent = []

    async def send(msg):
        sent.append(msg)

    rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(), send)
    applier = SettingsApplier(rt, FakeServices(), "", set_volume=lambda v: None)
    values = {**Settings(Database(":memory:"), CFG).all(), "log_unmatched_questions": True}
    asyncio.run(applier.apply(values))
    assert {"type": "privacy", "logQuestions": True} in sent
    assert {"type": "privacy", "logQuestions": True} in rt.snapshot()
