"""Engagement state machine (baseline spec 4.1).

Pure: events in, commands out, time injected. No I/O, so every timing rule is testable.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from core.controller.phrases import PHRASES, MenuItem, Phrases, is_decline
from core.controller.types import (
    AnswerDone,
    AnswerFailed,
    AnswerSentence,
    Ask,
    CameraStatus,
    CancelAnswer,
    Command,
    Event,
    MicMute,
    Presence,
    Record,
    Speak,
    SpeechEnded,
    SpeechFinal,
    StopSpeech,
    Tick,
    Touch,
    UiSend,
    VisionRate,
)

ENGAGED = frozenset({"greeting", "listening", "thinking", "speaking"})
# Detector misses shorter than this do not count as the person leaving Attentive.
ATTENTIVE_LOST_S = 1.0


@dataclass(frozen=True)
class ControllerConfig:
    dwell_s: float = 1.5
    depart_empty_s: float = 3.0
    greet_cooldown_s: float = 20.0
    silence_followup_s: float = 8.0
    max_followups: int = 1
    answer_timeout_s: float = 6.0
    farewell_silent_s: float = 2.0
    fps_idle: float = 8.0
    fps_engaged: float = 2.0
    kids_default: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> ControllerConfig:
        v, e = cfg["vision"], cfg["engagement"]
        return cls(
            dwell_s=v["dwell_s"],
            depart_empty_s=v["depart_empty_s"],
            greet_cooldown_s=e["greet_cooldown_s"],
            silence_followup_s=e["silence_followup_s"],
            max_followups=e["max_followups"],
            answer_timeout_s=cfg["llm"]["timeout_s"],
            farewell_silent_s=e["farewell_silent_s"],
            fps_idle=v["fps_idle"],
            fps_engaged=v["fps_engaged"],
            kids_default=e["kids_default"],
        )


class Controller:
    def __init__(self, cfg: ControllerConfig, phrases: Phrases = PHRASES) -> None:
        self.cfg = cfg
        self.p = phrases
        self.menu: tuple[MenuItem, ...] = phrases.menu
        self.state = "idle"
        self.camera_ok = True
        self.count = 0
        self.approaching = False
        self.empty_since: float | None = 0.0
        self.cooldown_until = 0.0
        self._ids = itertools.count(1)
        self._reset_session()

    def _reset_session(self) -> None:
        self.kids = self.cfg.kids_default
        self.history: list[tuple[str, str]] = []
        self.pending: list[str] = []
        self.followups = 0
        self.listen_since: float | None = None
        self.attentive_since: float | None = None
        self.greeted_at: float | None = None
        self.conversation_started = False
        self.question: str | None = None
        self.reply: list[str] = []
        self.answer_done = False
        self.got_sentence = False
        self.ask_since: float | None = None
        self.farewell_until: float | None = None

    def set_menu(self, items: list[MenuItem]) -> None:
        self.menu = tuple(items)

    # ---- entry point ----

    def handle(self, event: Event, now: float) -> list[Command]:
        out: list[Command] = []
        match event:
            case Presence():
                self._on_presence(event, now, out)
            case SpeechFinal(text=text):
                self._on_speech_final(text, now, out)
            case SpeechEnded(id=sid):
                self._on_speech_ended(sid, now, out)
            case AnswerSentence(text=text):
                self._on_sentence(text, now, out)
            case AnswerDone():
                self._on_answer_done(now, out)
            case AnswerFailed(kind=kind):
                if self.state == "thinking":
                    self._fail(kind, now, out)
                elif self.state == "speaking":
                    self._on_answer_done(now, out)
            case Touch():
                self._on_touch(event, now, out)
            case CameraStatus(ok=ok):
                self.camera_ok = ok
                out.append(UiSend({"type": "camera", "ok": ok}))
            case Tick():
                pass
        self._on_timers(now, out)
        return out

    # ---- events ----

    def _on_presence(self, ev: Presence, now: float, out: list[Command]) -> None:
        self.count = ev.count
        self.approaching = ev.approaching
        if ev.count > 0:
            self.empty_since = None
            if self.state != "idle":
                out.append(UiSend({"type": "lookAt", "x": ev.cx, "y": ev.cy}))
        elif self.empty_since is None:
            self.empty_since = now

    def _on_speech_final(self, text: str, now: float, out: list[Command]) -> None:
        text = text.strip()
        if self.state != "listening" or self.pending or not text:
            return
        if is_decline(text):
            out.append(Record("decline"))
            self._farewell(now, out, spoken=True)
            return
        if not self.conversation_started:
            self.conversation_started = True
            out.append(Record("conversation_start"))
        out.append(Record("question"))
        self.question = text
        self.reply = []
        self.answer_done = False
        self.got_sentence = False
        self.ask_since = now
        self._enter("thinking", now, out)
        out.append(MicMute(True))
        out.append(Ask(text, tuple(self.history[-3:]), self.kids))

    def _on_speech_ended(self, sid: str, now: float, out: list[Command]) -> None:
        if sid not in self.pending:
            return
        del self.pending[: self.pending.index(sid) + 1]
        if self.pending:
            return
        if self.state == "greeting":
            self._enter("listening", now, out)
        elif self.state == "listening":
            out.append(MicMute(False))
            self.listen_since = now
        elif self.state == "speaking" and self.answer_done:
            self._end_turn(now, out)
        elif self.state == "farewell":
            self._finish(now, out)

    def _on_sentence(self, text: str, now: float, out: list[Command]) -> None:
        if self.state not in ("thinking", "speaking") or self.question is None:
            return
        if not self.got_sentence:
            self.got_sentence = True
            out.append(Record("reply_latency_ms", round((now - self.ask_since) * 1000)))
            self._enter("speaking", now, out)
        self.reply.append(text)
        self._speak(text, out, display=" ".join(self.reply))

    def _on_answer_done(self, now: float, out: list[Command]) -> None:
        if self.question is None:
            return
        if self.state == "thinking":
            self._fail("unmatched", now, out)
            return
        if self.state != "speaking":
            return
        self.answer_done = True
        out.append(Record("answered"))
        if not self.pending:
            self._end_turn(now, out)

    def _on_touch(self, t: Touch, now: float, out: list[Command]) -> None:
        s = self.state
        # A touch proves someone is at the screen, even if the camera has not seen them yet.
        if self.empty_since is not None:
            self.empty_since = now
        if t.event == "kids":
            self.kids = bool(t.value)
        elif t.event == "talk":
            if s == "idle":
                out.append(Record("encounter"))
                self._greet(now, out)
            elif s == "attentive":
                self._greet(now, out)
        elif t.event == "stop":
            if s in ("greeting", "thinking", "speaking"):
                self.pending.clear()
                self.question = None
                out += [StopSpeech(), CancelAnswer()]
                self._enter("listening", now, out)
        elif t.event == "menu_item":
            item = next((m for m in self.menu if m.id == t.value), None)
            if item is None or s == "farewell":
                return
            if s in ("idle", "attentive") and self.greeted_at is None:
                if s == "idle":
                    out.append(Record("encounter"))
                self.greeted_at = now
            out.append(Record("fallback"))
            if self.pending or s in ("thinking", "speaking"):
                self.pending.clear()
                out += [StopSpeech(), CancelAnswer()]
            self._answer_fixed(item.answer, now, out)

    # ---- timers ----

    def _on_timers(self, now: float, out: list[Command]) -> None:
        s, c = self.state, self.cfg
        present = self.count > 0
        empty_for = now - self.empty_since if self.empty_since is not None else 0.0
        if s == "idle":
            if present and self.camera_ok and now >= self.cooldown_until:
                self.attentive_since = now
                out.append(Record("encounter"))
                self._enter("attentive", now, out)
                if self.approaching:
                    self._greet(now, out)
        elif s == "attentive":
            if not present and empty_for >= ATTENTIVE_LOST_S:
                self._enter("idle", now, out)
            elif present and (self.approaching or now - self.attentive_since >= c.dwell_s):
                self._greet(now, out)
        elif s in ENGAGED:
            if self.camera_ok and not present and empty_for >= c.depart_empty_s:
                out.append(Record("walkaway"))
                self._farewell(now, out, spoken=False)
            elif s == "listening":
                self._listening_timer(now, out)
            elif (
                s == "thinking"
                and not self.got_sentence
                and now - self.ask_since >= c.answer_timeout_s
            ):
                out.append(CancelAnswer())
                self._fail("offline", now, out)
        elif s == "farewell":
            if self.farewell_until is not None and now >= self.farewell_until:
                self._finish(now, out)

    def _listening_timer(self, now: float, out: list[Command]) -> None:
        if self.pending or self.listen_since is None:
            return
        if now - self.listen_since < self.cfg.silence_followup_s:
            return
        if self.followups < self.cfg.max_followups:
            self.followups += 1
            self.listen_since = None
            self._speak(self.p.followup, out)
        elif not self.camera_ok:
            # Without a camera we cannot see them leave, so silence ends the encounter.
            self._farewell(now, out, spoken=True)
        else:
            self.listen_since = None

    # ---- actions ----

    def _enter(self, state: str, now: float, out: list[Command], text: str | None = None) -> None:
        prev, self.state = self.state, state
        msg = {"type": "state", "state": state}
        if text is not None:
            msg["text"] = text
        out.append(UiSend(msg))
        if state in ENGAGED and prev not in ENGAGED:
            out.append(VisionRate(self.cfg.fps_engaged))
        elif state == "idle" and (prev in ENGAGED or prev == "farewell"):
            out.append(VisionRate(self.cfg.fps_idle))
        if state == "listening":
            out.append(MicMute(False))
            self.listen_since = now

    def _speak(self, text: str, out: list[Command], display: str | None = None) -> None:
        sid = f"s{next(self._ids)}"
        self.pending.append(sid)
        out.append(MicMute(True))
        out.append(UiSend({"type": "say", "text": display if display is not None else text}))
        out.append(Speak(sid, text))

    def _greet(self, now: float, out: list[Command]) -> None:
        self.greeted_at = now
        out.append(Record("greeting"))
        self._enter("greeting", now, out)
        if self.count >= 2:
            text = self.p.group_greet
        elif self.kids:
            text = self.p.kids_greet
        else:
            text = self.p.greet
        self._speak(text, out)

    def _answer_fixed(self, text: str, now: float, out: list[Command]) -> None:
        """Speak a reply that does not come from the LLM, then return to listening."""
        self.question = None
        self.reply = []
        self.got_sentence = True
        self.answer_done = True
        self._enter("speaking", now, out)
        self._speak(text, out)

    def _fail(self, kind: str, now: float, out: list[Command]) -> None:
        out.append(Record("unmatched" if kind == "unmatched" else "fallback"))
        self._answer_fixed(self.p.unmatched if kind == "unmatched" else self.p.offline, now, out)
        items = [{"id": m.id, "label": m.label} for m in self.menu]
        out.append(UiSend({"type": "menu", "show": True, "items": items}))

    def _end_turn(self, now: float, out: list[Command]) -> None:
        if self.question is not None and self.reply:
            self.history.append((self.question, " ".join(self.reply)))
        self.question = None
        self._enter("listening", now, out)

    def _farewell(self, now: float, out: list[Command], spoken: bool) -> None:
        if self.pending or self.state in ("thinking", "speaking"):
            out += [StopSpeech(), CancelAnswer()]
        self.pending.clear()
        self.question = None
        self._enter("farewell", now, out)
        out.append(UiSend({"type": "menu", "show": False}))
        if spoken:
            self.farewell_until = None
            self._speak(self.p.bye, out)
        else:
            self.farewell_until = now + self.cfg.farewell_silent_s

    def _finish(self, now: float, out: list[Command]) -> None:
        if self.greeted_at is not None:
            out.append(Record("conversation_end", round(now - self.greeted_at, 1)))
        self._reset_session()
        self.cooldown_until = now + self.cfg.greet_cooldown_s
        self._enter("idle", now, out)
        out.append(UiSend({"type": "kids", "value": self.kids}))
