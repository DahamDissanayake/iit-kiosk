"""FastAPI app for the kiosk screen: character UI, its WebSocket, and /health.

The staff dashboard API on port 8080 is added in M5.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from core.admin.apply import SettingsApplier
from core.admin.settings import ZONE_KEYS
from core.controller.machine import Controller, ControllerConfig
from core.runtime import Runtime
from core.sdnotify import notify
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


def create_app(
    cfg: dict,
    dev: bool = False,
    services: Services | None = None,
    links: bool = True,
) -> FastAPI:
    services = services or build_services(cfg, dev=dev)
    hub = Hub()
    runtime = Runtime(
        Controller(ControllerConfig.from_config(cfg)),
        services.speech,
        services.answerer,
        hub.broadcast,
        dev=dev,
        record=SessionRecorder(services.events),
        menu_source=services.kb.menu_items,
    )

    applier = SettingsApplier(runtime, services, cfg["ui"].get("music_url", ""))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        await applier.apply(services.settings.all())
        voice = services.voice(runtime) if (links and services.voice) else None
        if voice:
            voice.start()
        ctx = core_pub = vision = voice_link = None
        if links:
            import zmq.asyncio

            from core.bus import Publisher, Subscriber
            from core.vision_link import VisionLink
            from core.voice_link import VoiceLink

            ctx = zmq.asyncio.Context()
            core_pub = Publisher(ctx, cfg["bus"]["core_pub"])
            vision = VisionLink(
                runtime,
                Subscriber(
                    ctx, [cfg["bus"]["vision_pub"]], ["presence", "camera", "vision.preview"]
                ),
                core_pub,
                zone_source=lambda: {k: services.settings.all()[k] for k in ZONE_KEYS},
            )
            vision.start()
            app.state.vision_link = vision
            if cfg["voice"]["mode"] == "service":
                voice_link = VoiceLink(runtime, ctx, cfg["bus"]["voice_pub"], core_pub)
                voice_link.start()
        notify("READY=1")  # tells systemd (Type=notify) that startup is complete
        yield
        for link in (vision, voice_link):
            if link:
                await link.stop()
        if voice:
            voice.stop()
        await runtime.stop()
        if core_pub:
            core_pub.close()
        if ctx:
            ctx.term()

    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.state.applier = applier
    app.state.vision_link = None  # set while the vision link is running

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
