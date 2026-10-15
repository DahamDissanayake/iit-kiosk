import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.config import load_config
from core.rag.embed import HashEmbedder
from core.services import build_services

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))


def app(dev=True):
    cfg = load_config(ROOT / "config.toml")
    services = build_services(cfg, dev=dev, embedder=HashEmbedder(), env={}, with_voice=False)
    return create_app(cfg, dev=dev, services=services, links=False)


def read_until(ws, pred, limit=500):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if pred(msg):
            return seen
    raise AssertionError(f"condition not met; last messages: {seen[-5:]}")


def test_health():
    with TestClient(app()) as client:
        assert client.get("/health").json() == {"ok": True}


def test_ui_page_is_served():
    with TestClient(app()) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "IIT Visitor Assistant" in res.text


def test_new_connection_gets_snapshot():
    with TestClient(app()) as client, client.websocket_connect("/ws") as ws:
        snap = read_until(ws, lambda m: m["type"] == "state")
        assert snap[-1] == {"type": "state", "state": "idle"}
        assert {"type": "dev", "enabled": True} in snap


def test_dev_visitor_is_greeted_and_listens_after_playback():
    with TestClient(app()) as client, client.websocket_connect("/ws") as ws:
        read_until(ws, lambda m: m["type"] == "state")
        ws.send_json({"type": "dev", "action": "approach"})
        seen = read_until(ws, lambda m: m["type"] == "audio")
        assert [m["state"] for m in seen if m["type"] == "state"] == ["attentive", "greeting"]
        ws.send_json({"type": "speech.ended", "id": seen[-1]["id"]})
        read_until(ws, lambda m: m == {"type": "state", "state": "listening"})


def test_malformed_message_is_ignored():
    with TestClient(app()) as client, client.websocket_connect("/ws") as ws:
        read_until(ws, lambda m: m["type"] == "state")
        ws.send_text("not json")
        ws.send_json(["not", "an", "object"])
        ws.send_json({"type": "dev", "action": "linger"})
        read_until(ws, lambda m: m == {"type": "state", "state": "attentive"})


def test_stored_settings_apply_at_startup():
    cfg = load_config(ROOT / "config.toml")
    services = build_services(cfg, dev=True, embedder=HashEmbedder(), env={}, with_voice=False)
    services.settings.update({"greet_cooldown_s": 45, "min_score": 0.6, "quiet_mode": True})
    application = create_app(cfg, dev=True, services=services, links=False)
    with TestClient(application) as client, client.websocket_connect("/ws") as ws:
        snapshot = read_until(ws, lambda m: m["type"] == "state")
        runtime = application.state.runtime
        assert runtime.c.cfg.greet_cooldown_s == 45
        assert runtime.music == {"url": "", "volume": cfg["audio"]["music_volume"]}
        assert {"type": "music", "url": "", "volume": cfg["audio"]["music_volume"]} in snapshot
        assert client.get("/health").json() == {"ok": True}


def test_startup_signals_ready_to_systemd_after_the_runtime_is_up(monkeypatch):
    sent = []
    monkeypatch.setattr("core.app.notify", sent.append)
    with TestClient(app()):
        assert sent == ["READY=1"]


@pytest.mark.skipif(sys.platform == "win32", reason="unix datagram sockets")
def test_ready_and_watchdog_reach_a_real_notify_socket(tmp_path, monkeypatch):
    """What a Type=notify unit receives: READY=1 exactly once and WATCHDOG=1 pings."""
    sock_path = str(tmp_path / "notify.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)
    server.settimeout(0.2)
    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    received = []
    with TestClient(app()):
        deadline = time.time() + 3
        while time.time() < deadline and not ("READY=1" in received and "WATCHDOG=1" in received):
            try:
                received.append(server.recv(100).decode())
            except TimeoutError:
                pass
    server.close()
    assert received.count("READY=1") == 1  # a WATCHDOG ping may arrive first; systemd allows it
    assert "WATCHDOG=1" in received
