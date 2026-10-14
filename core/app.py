"""FastAPI app for the kiosk screen: character UI, its WebSocket, and /health.

The staff dashboard API on port 8080 is added in M5.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from core.controller.machine import Controller, ControllerConfig
from core.runtime import Runtime
from core.services import Services, build_services
from core.store.events import SessionRecorder

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


class Hub:
    """Every connected UI page; messages go to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                self._clients.discard(ws)


def create_app(cfg: dict, dev: bool = False, services: Services | None = None) -> FastAPI:
    services = services or build_services(cfg, dev=dev)
    hub = Hub()
    music_url = cfg["ui"].get("music_url")
    music = {"url": music_url, "volume": cfg["audio"]["music_volume"]} if music_url else None
    runtime = Runtime(
        Controller(ControllerConfig.from_config(cfg)),
        services.speech,
        services.answerer,
        hub.broadcast,
        dev=dev,
        music=music,
        record=SessionRecorder(services.events),
        menu_source=services.kb.menu_items,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        yield
        await runtime.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(sock: WebSocket) -> None:
        await sock.accept()
        try:
            for msg in runtime.snapshot():
                await sock.send_json(msg)
            hub.add(sock)
            while True:
                raw = await sock.receive_text()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await runtime.on_ui(msg)
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(sock)

    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app
