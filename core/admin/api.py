"""Staff dashboard API on port 8080 (baseline 5 and 7.3)."""

import asyncio
import copy
import json
import subprocess
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from core import __version__
from core.admin.apply import SettingsApplier
from core.admin.auth import PinAuth
from core.admin.health import LLM_HOSTS, ErrorBuffer, NetProbe, systemd_restarts
from core.admin.stats import hourly, overview, start_of_today
from core.answer import AnswerError
from core.rag.kb import ModelMismatch
from core.runtime import Runtime
from core.sysinfo import load1, read_mem_mb, read_temp

DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
MAX_UPLOAD = 20 * 1024 * 1024
STARTED = time.time()


class PinIn(BaseModel):
    pin: str


class PinChange(BaseModel):
    current: str
    new: str


class SourcePatch(BaseModel):
    title: str | None = None
    enabled: bool | None = None
    text: str | None = None
    pairs: list[tuple[str, str]] | None = None


class Question(BaseModel):
    question: str


def create_admin_app(
    cfg: dict,
    services,
    runtime: Runtime,
    applier: SettingsApplier,
    *,
    dev: bool,
    session_secret: str,
    get_vision_link: Callable[[], object] = lambda: None,
    clock: Callable[[], float] = time.time,
    probe=None,
) -> "FastAPI":
    admin = cfg["admin"]
    auth = PinAuth(services.db, admin["pin_max_tries"], admin["lockout_s"], clock)
    kb, settings = services.kb, services.settings
    errors = ErrorBuffer.install()
    probe = probe or NetProbe(LLM_HOSTS.get(cfg["llm"]["provider"], "1.1.1.1"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        probe.start()
        yield
        await probe.stop()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="kiosk_admin",
        same_site="strict",
        https_only=False,
    )

    def session(request: Request) -> None:
        s, now = request.session, clock()
        if not s.get("auth") or now - s.get("seen", 0) > admin["session_idle_s"]:
            s.clear()
            raise HTTPException(401, "Please log in.")
        s["seen"] = now

    need = [Depends(session)]

    def since(range_: str) -> float:
        return start_of_today() if range_ == "today" else 0.0

    async def kb_call(fn, *args, **kwargs):
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except KeyError:
            raise HTTPException(404, "No such source.") from None
        except ModelMismatch as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        runtime.refresh_menu()
        return result

    # ---- public ----

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/version")
    async def version() -> dict:
        return {"version": __version__}

    # ---- auth ----

    @app.get("/api/auth/me")
    async def me(request: Request) -> dict:
        s = request.session
        return {
            "auth": bool(s.get("auth")) and clock() - s.get("seen", 0) <= admin["session_idle_s"]
        }

    @app.post("/api/auth/login")
    async def login(body: PinIn, request: Request) -> dict:
        result = await asyncio.to_thread(auth.check, body.pin)
        if result.ok:
            request.session.update({"auth": True, "seen": clock()})
            return {"ok": True}
        if result.reason == "unset":
            raise HTTPException(409, {"reason": "unset"})
        if result.reason == "locked":
            raise HTTPException(423, {"reason": "locked", "retry_after_s": result.retry_after_s})
        raise HTTPException(401, {"reason": "wrong", "tries_left": result.tries_left})

    @app.post("/api/auth/logout", dependencies=need)
    async def logout(request: Request) -> dict:
        request.session.clear()
        return {"ok": True}

    @app.post("/api/auth/pin", dependencies=need)
    async def change_pin(body: PinChange) -> dict:
        if not (await asyncio.to_thread(auth.check, body.current)).ok:
            raise HTTPException(400, "The current PIN is wrong.")
        try:
            await asyncio.to_thread(auth.set_pin, body.new)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    # ---- stats ----

    @app.get("/api/stats", dependencies=need)
    async def stats(range: str = "today") -> dict:
        return {**overview(services.db, since(range)), "uptime_s": round(time.time() - STARTED)}

    @app.get("/api/stats/hourly", dependencies=need)
    async def stats_hourly(range: str = "today") -> list[dict]:
        return hourly(services.db, since(range))

    # ---- knowledge base ----

    @app.get("/api/kb/sources", dependencies=need)
    async def sources() -> dict:
        return {
            "sources": [s.__dict__ for s in kb.list_sources()],
            "needs_reindex": kb.needs_reindex(),
        }

    @app.get("/api/kb/sources/{source_id}", dependencies=need)
    async def source(source_id: int) -> dict:
        info = next((s for s in kb.list_sources() if s.id == source_id), None)
        if info is None:
            raise HTTPException(404, "No such source.")
        body = kb.get_body(source_id)
        out = dict(info.__dict__)
        if info.kind == "qa":
            out["pairs"] = json.loads(body)
        elif info.kind == "file":
            out["text"] = "\n\n".join(f"{h}\n{t}".strip() for h, t in json.loads(body))
        else:
            out["text"] = body
        return out

    @app.post("/api/kb/sources", dependencies=need)
    async def add_source(
        kind: str = Form(...),
        title: str = Form(""),
        text: str = Form(""),
        pairs: str = Form(""),
        file: Annotated[UploadFile | None, File()] = None,
    ) -> dict:
        title = title.strip()
        if kind == "text":
            sid = await kb_call(kb.add_text, title or "Untitled", text)
        elif kind == "menu":
            if not title or not text.strip():
                raise HTTPException(400, "A menu item needs a label and an answer.")
            sid = await kb_call(kb.add_menu, title, text.strip())
        elif kind == "qa":
            try:
                parsed = [(q, a) for q, a in json.loads(pairs or "[]")]
            except (ValueError, TypeError):
                raise HTTPException(400, "Questions and answers could not be read.") from None
            if not parsed:
                raise HTTPException(400, "Add at least one question and answer.")
            sid = await kb_call(kb.add_qa, title or "Questions and answers", parsed)
        elif kind == "file":
            if file is None:
                raise HTTPException(400, "Choose a file to upload.")
            data = await file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "Files must be 20 MB or smaller.")
            sid = await kb_call(kb.add_file, title, file.filename or "upload", data)
        else:
            raise HTTPException(400, f"Unknown source type: {kind}")
        return {"id": sid}

    @app.patch("/api/kb/sources/{source_id}", dependencies=need)
    async def patch_source(source_id: int, body: SourcePatch) -> dict:
        await kb_call(
            kb.update,
            source_id,
            title=body.title,
            enabled=body.enabled,
            text=body.text,
            pairs=body.pairs,
        )
        return {"ok": True}

    @app.delete("/api/kb/sources/{source_id}", dependencies=need)
    async def delete_source(source_id: int) -> dict:
        await kb_call(kb.delete, source_id)
        return {"ok": True}

    @app.post("/api/kb/reindex", dependencies=need)
    async def reindex() -> dict:
        return {"sources": await kb_call(kb.reindex)}

    @app.post("/api/kb/test", dependencies=need)
    async def test_question(body: Question) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(400, "Type a question.")
        top_k = cfg["rag"]["top_k"]
        hits = await kb_call(kb.search, question, top_k)
        answerer = copy.copy(services.answerer)
        if hasattr(answerer, "on_unmatched"):
            answerer.on_unmatched = None  # testing must not log visitor questions
        sentences, status = [], "answered"
        try:
            async for s in answerer.answer(question, (), False):
                sentences.append(s)
        except AnswerError as e:
            status = e.kind
        return {
            "status": status,
            "answer": " ".join(sentences) or None,
            "hits": [
                {"title": h.title, "heading": h.heading, "text": h.text, "score": round(h.score, 3)}
                for h in hits
            ],
            "threshold": settings.all()["min_score"],
        }

    @app.get("/api/kb/unmatched", dependencies=need)
    async def unmatched() -> dict:
        enabled = services.unmatched.enabled
        return {"enabled": enabled, "items": services.unmatched.list() if enabled else []}

    # ---- settings ----

    @app.get("/api/settings", dependencies=need)
    async def get_settings() -> dict:
        return settings.all()

    @app.put("/api/settings", dependencies=need)
    async def put_settings(changes: dict) -> dict:
        try:
            values = settings.update(changes)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        await applier.apply(values)
        return values

    @app.get("/api/vision/preview", dependencies=need)
    async def vision_preview() -> dict:
        link = get_vision_link()
        preview = getattr(link, "preview", None)
        if not preview:
            raise HTTPException(404, "No camera preview: kiosk-vision is not running.")
        return preview

    # ---- health and system ----

    @app.get("/api/health/detail", dependencies=need)
    async def health_detail() -> dict:
        mem = read_mem_mb()
        last = services.db.execute(
            "SELECT value FROM events WHERE type = 'reply_latency_ms' ORDER BY ts DESC LIMIT 1"
        )
        return {
            "cpu_temp_c": read_temp(),
            "load1": load1(),
            "mem_used_mb": (mem[0] - mem[1]) if mem else None,
            "mem_total_mb": mem[0] if mem else None,
            "internet_ok": probe.ok,
            "llm_last_reply_ms": round(last[0]["value"]) if last else None,
            "camera_ok": runtime.c.camera_ok,
            "mic_ok": getattr(runtime.c, "mic_ok", True),
            "uptime_s": round(time.time() - STARTED),
            "restarts": await asyncio.to_thread(systemd_restarts, "kiosk-core"),
            "errors": errors.items()[:20],
            "dev": dev,
        }

    def system_action(cmd: list[str]) -> dict:
        if dev:
            raise HTTPException(409, "Restart and shut down are disabled in dev mode.")
        asyncio.get_running_loop().call_later(1.0, lambda: subprocess.Popen(cmd))
        return {"ok": True}

    @app.post("/api/system/restart", dependencies=need)
    async def restart() -> dict:
        return system_action(admin["restart_cmd"])

    @app.post("/api/system/shutdown", dependencies=need)
    async def shutdown() -> dict:
        return system_action(admin["shutdown_cmd"])

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
    return app
