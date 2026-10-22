"""Mic -> VAD -> STT on a worker thread; results go to a VoiceSink on the asyncio loop."""

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

log = logging.getLogger("kiosk.voice")


class VoiceSink(Protocol):
    async def speech_started(self) -> None: ...
    async def partial(self, text: str) -> None: ...
    async def final(self, text: str) -> None: ...
    async def mic_status(self, ok: bool) -> None: ...


class VoicePipeline:
    def __init__(
        self,
        mic,
        vad,
        segmenter,
        transcriber,
        sink: VoiceSink,
        loop: asyncio.AbstractEventLoop,
        partial_every_s: float = 1.5,
        stall_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        check_every_s: float = 1.0,
        reopen_every_s: float = 5.0,
    ) -> None:
        self.mic = mic
        self.vad = vad
        self.seg = segmenter
        self.stt = transcriber
        self.sink = sink
        self.loop = loop
        self.partial_every_s = partial_every_s
        self.stall_s = stall_s
        self.clock = clock
        self.check_every_s = check_every_s
        self.reopen_every_s = reopen_every_s
        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._generation = 0  # bumped on every mute; stale frames are dropped
        self._running = threading.Event()
        self._threads: list[threading.Thread] = []
        self.mic.on_frame = self._on_frame

    # ---- control ----

    def start(self) -> None:
        self._running.set()
        for target, name in ((self._work, "voice-worker"), (self._watch, "voice-watch")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._running.clear()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        self.mic.close()

    def set_muted(self, muted: bool) -> None:
        self.mic.muted = muted
        if muted:
            self._generation += 1
            while True:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    break

    # ---- threads ----

    def _on_frame(self, frame: np.ndarray) -> None:
        if self.mic.muted:
            return
        try:
            self._frames.put_nowait((self._generation, frame))
        except queue.Full:
            log.warning("voice worker is behind; dropping audio")

    def _post(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _work(self) -> None:
        generation = self._generation
        last_partial = 0.0
        while self._running.is_set():
            try:
                gen, frame = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if gen != self._generation or self.mic.muted:
                continue
            if gen != generation:
                generation = gen
                self.seg.reset()
                self.vad.reset()
            event = self.seg.push(frame, self.vad.prob(frame))
            now = self.clock()
            if event == "start":
                last_partial = now
                self._post(self.sink.speech_started())
            elif isinstance(event, tuple):
                text = self.stt.transcribe(event[1])
                if gen == self._generation:
                    self._post(self.sink.final(text))
            elif (
                self.seg.active
                and self.partial_every_s
                and now - last_partial >= self.partial_every_s
            ):
                last_partial = now
                text = self.stt.transcribe(self.seg.current_audio())
                if text and gen == self._generation:
                    self._post(self.sink.partial(text))

    def _watch(self) -> None:
        ok: bool | None = None
        last_open = -1e9
        while self._running.is_set():
            now = self.clock()
            healthy = now - self.mic.last_frame_at < self.stall_s
            if not healthy and now - last_open >= self.reopen_every_s:
                last_open = now
                try:
                    self.mic.open()
                    healthy = True
                except Exception as e:  # device unplugged or busy
                    log.warning("microphone unavailable: %s", e)
            if healthy != ok:
                ok = healthy
                self._post(self.sink.mic_status(ok))
            time.sleep(self.check_every_s)
