from pathlib import Path

from fastapi.testclient import TestClient

from core.app import create_app
from core.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def app(dev=True):
    return create_app(load_config(ROOT / "config.toml"), dev=dev)


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
