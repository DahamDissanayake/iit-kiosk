import pytest
from fastapi.testclient import TestClient

from core.admin.api import create_admin_app
from core.admin.apply import SettingsApplier
from core.answer import CannedAnswerer
from core.config import load_config
from core.controller.machine import Controller, ControllerConfig
from core.rag.embed import HashEmbedder
from core.runtime import Runtime
from core.services import build_services
from core.speech import FakeSpeech


class FakeProbe:
    ok = True

    def start(self):
        pass

    async def stop(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))
    cfg = load_config("config.toml")
    services = build_services(cfg, dev=True, embedder=HashEmbedder(), env={}, with_voice=False)

    async def send(msg):
        pass

    runtime = Runtime(
        Controller(ControllerConfig()),
        FakeSpeech(),
        CannedAnswerer(delay_s=0),
        send,
        menu_source=services.kb.menu_items,
    )
    applier = SettingsApplier(runtime, services, "", set_volume=lambda v: None)
    now = [1_000_000.0]

    def make(dev=True):
        app = create_admin_app(
            cfg,
            services,
            runtime,
            applier,
            dev=dev,
            session_secret="test",
            clock=lambda: now[0],
            probe=FakeProbe(),
        )
        return TestClient(app)

    return make, services, runtime, now


def login(client, pin="482913"):
    return client.post("/api/auth/login", json={"pin": pin})


def authed(env, dev=True):
    make, services, runtime, now = env
    from core.admin.auth import PinAuth

    PinAuth(services.db).set_pin("482913")
    client = make(dev)
    assert login(client).status_code == 200
    return client


def test_public_routes(env):
    with env[0]() as c:
        assert c.get("/health").json() == {"ok": True}
        assert "version" in c.get("/version").json()
        assert c.get("/api/auth/me").json() == {"auth": False}


def test_api_requires_login(env):
    with env[0]() as c:
        assert c.get("/api/stats?range=today").status_code == 401


def test_unset_pin(env):
    with env[0]() as c:
        r = login(c)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "unset"


def test_wrong_pin_then_lockout(env):
    make, services, _, _ = env
    from core.admin.auth import PinAuth

    PinAuth(services.db).set_pin("482913")
    with make() as c:
        r = login(c, "000000")
        assert r.status_code == 401 and r.json()["detail"]["tries_left"] == 4
        for _ in range(4):
            r = login(c, "000000")
        assert r.status_code == 423
        assert login(c).status_code == 423


def test_session_expires_after_idle_time(env):
    with authed(env) as c:
        now = env[3]
        assert c.get("/api/stats?range=today").status_code == 200
        now[0] += 301
        assert c.get("/api/stats?range=today").status_code == 401


def test_logout(env):
    with authed(env) as c:
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").json() == {"auth": False}


def test_change_pin_needs_current_pin(env):
    with authed(env) as c:
        assert (
            c.post("/api/auth/pin", json={"current": "111111", "new": "222222"}).status_code == 400
        )
        assert (
            c.post("/api/auth/pin", json={"current": "482913", "new": "222222"}).status_code == 200
        )
        c.post("/api/auth/logout")
        assert login(c, "222222").status_code == 200


def test_stats_shape(env):
    with authed(env) as c:
        body = c.get("/api/stats?range=all").json()
        assert set(body) == {"counts", "avg_conversation_s", "avg_reply_ms", "uptime_s"}
        assert len(c.get("/api/stats/hourly?range=today").json()) == 24


def test_knowledge_base_lifecycle_reaches_search_and_menu(env):
    _, services, runtime, _ = env
    with authed(env) as c:
        r = c.post(
            "/api/kb/sources",
            data={"kind": "text", "title": "Library", "text": "The library opens at eight."},
        )
        assert r.status_code == 200
        sid = r.json()["id"]
        assert services.kb.search("library opens")[0].source_id == sid
        detail = c.get(f"/api/kb/sources/{sid}").json()
        assert detail["text"] == "The library opens at eight."
        c.patch(f"/api/kb/sources/{sid}", json={"text": "The library opens at nine."})
        assert "nine" in services.kb.search("library opens")[0].text
        c.patch(f"/api/kb/sources/{sid}", json={"enabled": False})
        assert all(h.source_id != sid for h in services.kb.search("library opens"))
        assert c.delete(f"/api/kb/sources/{sid}").status_code == 200
        r = c.post(
            "/api/kb/sources",
            data={"kind": "menu", "title": "Where is IIT?", "text": "In Colombo."},
        )
        assert any(m.label == "Where is IIT?" for m in runtime.c.menu)
        r = c.post(
            "/api/kb/sources",
            data={"kind": "qa", "title": "FAQ", "pairs": '[["Parking?", "Yes."]]'},
        )
        assert r.status_code == 200
        listing = c.get("/api/kb/sources").json()
        assert listing["needs_reindex"] is False
        assert c.post("/api/kb/reindex").json()["sources"] == len(listing["sources"])


def test_upload_file(env):
    with authed(env) as c:
        r = c.post(
            "/api/kb/sources",
            data={"kind": "file", "title": ""},
            files={"file": ("guide.md", b"# Fees\nPaid each semester.", "text/markdown")},
        )
        assert r.status_code == 200


def test_unsupported_upload_is_rejected(env):
    with authed(env) as c:
        r = c.post(
            "/api/kb/sources",
            data={"kind": "file", "title": "x"},
            files={"file": ("run.exe", b"MZ", "application/octet-stream")},
        )
        assert r.status_code == 400
        assert c.get("/api/kb/sources").json()["sources"][-1]["title"] != "x"


def test_upload_too_large_is_rejected(env):
    with authed(env) as c:
        big = b"a" * (20 * 1024 * 1024 + 1)
        r = c.post(
            "/api/kb/sources",
            data={"kind": "file", "title": "big"},
            files={"file": ("big.txt", big, "text/plain")},
        )
        assert r.status_code == 413


def test_test_a_question(env):
    with authed(env) as c:
        c.post(
            "/api/kb/sources",
            data={"kind": "text", "title": "Library", "text": "The library opens at eight."},
        )
        body = c.post("/api/kb/test", json={"question": "When does the library open?"}).json()
        assert body["status"] == "answered"
        assert body["hits"][0]["title"] == "Library"
        assert "threshold" in body


def test_unmatched_off_by_default(env):
    with authed(env) as c:
        assert c.get("/api/kb/unmatched").json() == {"enabled": False, "items": []}


def test_settings_read_write_and_apply(env):
    runtime = env[2]
    with authed(env) as c:
        assert c.get("/api/settings").json()["greet_cooldown_s"] == 20
        r = c.put("/api/settings", json={"greet_cooldown_s": 45})
        assert r.json()["greet_cooldown_s"] == 45
        assert runtime.c.cfg.greet_cooldown_s == 45
        bad = c.put("/api/settings", json={"volume": 7})
        assert bad.status_code == 400 and "volume" in bad.json()["detail"]


def test_vision_preview_404_without_vision(env):
    with authed(env) as c:
        assert c.get("/api/vision/preview").status_code == 404


def test_health_detail_shape(env):
    with authed(env) as c:
        body = c.get("/api/health/detail").json()
        assert {
            "cpu_temp_c",
            "internet_ok",
            "camera_ok",
            "mic_ok",
            "uptime_s",
            "errors",
            "dev",
        } <= set(body)


def test_system_actions_refused_in_dev(env):
    with authed(env) as c:
        assert c.post("/api/system/restart").status_code == 409
        assert c.post("/api/system/shutdown").status_code == 409
