"""Runs the controller: feeds it events and carries out the commands it returns."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from core import __version__
from core.answer import Answerer, AnswerError
from core.controller.machine import Controller
from core.controller.phrases import MenuItem
from core.controller.types import (
    AnswerDone,
    AnswerFailed,
    AnswerSentence,
    Ask,
    CameraStatus,
    CancelAnswer,
    Event,
    MicMute,
    MicStatus,
    Presence,
    Record,
    Speak,
    SpeechEnded,
    SpeechFinal,
    SpeechStarted,
    StopSpeech,
    Tick,
    Touch,
    UiSend,
    VisionRate,
)
from core.speech import SpeechOutput, SpeechQueue

log = logging.getLogger("kiosk.core")

TICK_S = 0.1
TOUCH_EVENTS = ("talk", "stop", "kids", "menu_item")


class Runtime:
    def __init__(
        self,
        controller: Controller,
        speech: SpeechOutput,
        answerer: Answerer,
        send: Callable[[dict], Awaitable[None]],
        *,
        dev: bool = False,
        music: dict | None = None,
        clock: Callable[[], float] = time.monotonic,
        record: Callable[[str, float | None], None] | None = None,
        menu_source: Callable[[], list[MenuItem]] | None = None,
    ) -> None:
        self.c = controller
        self.answerer = answerer
        self.send = send
        self.dev = dev
        self.music = music
        self.clock = clock
        self.menu_source = menu_source
        self.record = record or (lambda kind, value: log.info("event %s %s", kind, value))
        self.mic_muted = True
        self.mic_listeners: list[Callable[[bool], None]] = []
        self.vision_listeners: list[Callable[[float], None]] = []
        self.vision_fps: float | None = None
        self.voice = SpeechQueue(speech, send, self._speech_failed)
        self._lock = asyncio.Lock()
        self._answer_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # ---- lifecycle ----

    def refresh_menu(self) -> None:
        if self.menu_source:
            self.c.set_menu(self.menu_source())

    def start(self) -> None:
        self.refresh_menu()
        self._spawn(self._tick_loop())
        self._spawn(self.voice.run())

    async def stop(self) -> None:
        self._cancel_answer()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def snapshot(self) -> list[dict]:
        """Messages a newly connected UI needs; the current state goes last."""
        msgs = [
            {"type": "version", "version": __version__},
            {"type": "dev", "enabled": self.dev},
            {"type": "camera", "ok": self.c.camera_ok},
        ]
        if self.music:
            msgs.append({"type": "music", **self.music})
        msgs.append({"type": "state", "state": self.c.state})
        return msgs

    # ---- events in ----

    async def handle(self, event: Event) -> None:
        async with self._lock:
            commands = self.c.handle(event, self.clock())
            await self._run(commands)

    async def on_ui(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "speech.ended":
            await self.handle(SpeechEnded(str(msg.get("id"))))
        elif kind == "ui" and msg.get("event") in TOUCH_EVENTS:
            await self.handle(Touch(msg["event"], msg.get("value")))
        elif kind == "dev" and self.dev:
            await self._dev(msg)

    async def _dev(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "approach":
            await self.handle(Presence(1, approaching=True))
        elif action == "group":
            await self.handle(Presence(2, approaching=True))
        elif action == "linger":
            await self.handle(Presence(1))
        elif action == "walkpast":
            await self.handle(Presence(1, cx=-0.8))
            self._spawn(self._later(1.0, Presence(0)))
        elif action == "leave":
            await self.handle(Presence(0))
        elif action == "ask":
            text = str(msg.get("text", "")).strip()
            if text:
                await self.handle(SpeechFinal(text))
        elif action == "camera":
            await self.handle(CameraStatus(bool(msg.get("ok"))))
        elif action == "internet" and hasattr(self.answerer, "offline"):
            self.answerer.offline = not bool(msg.get("ok"))

    # ---- voice input (VoiceSink) ----

    async def speech_started(self) -> None:
        await self.handle(SpeechStarted())

    async def partial(self, text: str) -> None:
        if self.c.state == "listening":
            await self.send({"type": "stt", "text": text, "final": False})

    async def final(self, text: str) -> None:
        if text.strip() and self.c.state == "listening":
            await self.send({"type": "stt", "text": text, "final": True})
        await self.handle(SpeechFinal(text))

    async def mic_status(self, ok: bool) -> None:
        await self.handle(MicStatus(ok))

    # ---- commands out ----

    async def _run(self, commands: list) -> None:
        for cmd in commands:
            match cmd:
                case UiSend(msg=msg):
                    await self.send(msg)
                case Speak(id=sid, text=text):
                    self.voice.put(sid, text)
                case StopSpeech():
                    self.voice.clear()
                    await self.send({"type": "stopAudio"})
                case MicMute(muted=muted):
                    self.mic_muted = muted
                    for listener in self.mic_listeners:
                        listener(muted)
                case VisionRate(fps=fps):
                    self.vision_fps = fps
                    for listener in self.vision_listeners:
                        listener(fps)
                case Ask():
                    self._cancel_answer()
                    self._answer_task = self._spawn(self._answer(cmd))
                case CancelAnswer():
                    self._cancel_answer()
                case Record(type=kind, value=value):
                    self.record(kind, value)

    async def _answer(self, ask: Ask) -> None:
        try:
            async for sentence in self.answerer.answer(ask.question, ask.history, ask.kids):
                await self.handle(AnswerSentence(sentence))
            await self.handle(AnswerDone())
        except AnswerError as e:
            await self.handle(AnswerFailed(e.kind))
        except Exception:
            log.exception("answer failed")
            await self.handle(AnswerFailed("offline"))

    async def _speech_failed(self, sid: str) -> None:
        # Treat a failed utterance as played so the conversation moves on.
        await self.handle(SpeechEnded(sid))

    # ---- helpers ----

    def _cancel_answer(self) -> None:
        task = self._answer_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._answer_task = None

    async def _tick_loop(self) -> None:
        while True:
            await self.handle(Tick())
            await asyncio.sleep(TICK_S)

    async def _later(self, delay: float, event: Event) -> None:
        await asyncio.sleep(delay)
        await self.handle(event)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
