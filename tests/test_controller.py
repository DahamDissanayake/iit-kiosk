import pytest

from core.controller.machine import Controller, ControllerConfig
from core.controller.phrases import PHRASES, MenuItem, is_decline
from core.controller.types import (
    AnswerDone,
    AnswerFailed,
    AnswerSentence,
    Ask,
    CameraStatus,
    CancelAnswer,
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

APPROACH = Presence(1, approaching=True)


class Sim:
    """Drives a Controller with explicit timestamps and keeps every command it returned."""

    def __init__(self, **overrides):
        self.c = Controller(ControllerConfig(**overrides))
        self.out = []
        self.log = []

    def at(self, t, event=None):
        self.out = self.c.handle(event or Tick(), t)
        self.log += self.out
        return self.out

    def end_speech(self, t):
        return self.at(t, SpeechEnded(self.c.pending[-1]))

    def all(self, kind):
        return [c for c in self.log if isinstance(c, kind)]

    def spoken(self):
        return [c.text for c in self.all(Speak)]

    def ui(self, type_, out=None):
        cmds = self.log if out is None else out
        return [c.msg for c in cmds if isinstance(c, UiSend) and c.msg["type"] == type_]

    def to_listening(self):
        self.at(1.0, APPROACH)
        self.end_speech(4.0)
        assert self.c.state == "listening"

    def ask(self, t, question):
        self.at(t, SpeechFinal(question))
        assert self.c.state == "thinking"


# ---- presence and greeting ----


def test_person_entering_zone_makes_bot_attentive_without_speaking():
    s = Sim()
    s.at(1.0, Presence(1))
    assert s.c.state == "attentive"
    assert s.spoken() == []
    assert Record("encounter") in s.out


def test_passer_by_is_not_greeted():
    s = Sim()
    s.at(1.0, Presence(1, cx=-0.8))
    s.at(1.5, Presence(0))
    s.at(2.6)
    assert s.c.state == "idle"
    assert s.spoken() == []


def test_brief_detection_gap_does_not_drop_attention():
    s = Sim()
    s.at(1.0, Presence(1))
    s.at(1.2, Presence(0))
    s.at(1.6, Presence(1))
    assert s.c.state == "attentive"
    assert {"type": "state", "state": "idle"} not in s.ui("state")


def test_approach_greets_once_per_encounter():
    s = Sim()
    s.at(1.0, APPROACH)
    assert s.c.state == "greeting"
    s.at(1.5, APPROACH)
    s.end_speech(4.0)
    s.at(5.0, APPROACH)
    assert s.spoken() == [PHRASES.greet]


def test_lingering_for_dwell_time_greets():
    s = Sim()
    s.at(1.0, Presence(1))
    s.at(2.4, Presence(1))
    assert s.c.state == "attentive"
    s.at(2.5, Presence(1))
    assert s.c.state == "greeting"


def test_group_gets_group_greeting():
    s = Sim()
    s.at(1.0, Presence(2, approaching=True))
    assert s.spoken() == [PHRASES.group_greet]


def test_kids_mode_uses_kids_greeting_and_kids_answers():
    s = Sim()
    s.at(0.5, Touch("kids", True))
    s.at(1.0, APPROACH)
    assert s.spoken() == [PHRASES.kids_greet]
    s.end_speech(4.0)
    s.ask(5.0, "What is a startup?")
    assert s.all(Ask)[0].kids is True


def test_greeting_mutes_mic_then_listening_opens_it():
    s = Sim()
    s.at(1.0, APPROACH)
    assert MicMute(True) in s.out
    s.end_speech(4.0)
    assert s.c.state == "listening"
    assert MicMute(False) in s.out


def test_vision_slows_while_engaged_and_restores_after():
    s = Sim()
    s.at(1.0, APPROACH)
    assert VisionRate(2) in s.out
    s.end_speech(4.0)
    s.at(5.0, Presence(0))
    s.at(8.0)
    s.at(10.0)
    assert s.c.state == "idle"
    assert VisionRate(8) in s.out


# ---- listening and follow-up ----


def test_silence_triggers_one_follow_up_then_waits():
    s = Sim()
    s.to_listening()
    s.at(11.9)
    assert s.spoken() == [PHRASES.greet]
    s.at(12.0)
    assert s.spoken() == [PHRASES.greet, PHRASES.followup]
    s.end_speech(14.0)
    s.at(30.0)
    s.at(60.0)
    assert s.spoken() == [PHRASES.greet, PHRASES.followup]
    assert s.c.state == "listening"


def test_speech_heard_while_bot_talks_is_ignored():
    s = Sim()
    s.at(1.0, APPROACH)
    s.at(2.0, SpeechFinal("hello"))
    assert s.c.state == "greeting"
    assert s.all(Ask) == []


def test_duplicate_or_unknown_speech_ended_is_ignored():
    s = Sim()
    s.at(1.0, APPROACH)
    sid = s.c.pending[-1]
    s.at(4.0, SpeechEnded(sid))
    s.at(4.1, SpeechEnded(sid))
    s.at(4.2, SpeechEnded("nope"))
    assert s.c.state == "listening"
    assert s.ui("state").count({"type": "state", "state": "listening"}) == 1


# ---- question and answer ----


def test_question_turn_streams_sentences_and_returns_to_listening():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "What courses do you offer?")
    ask = s.all(Ask)[0]
    assert ask.question == "What courses do you offer?"
    assert ask.history == ()
    assert MicMute(True) in s.out
    s.at(6.0, AnswerSentence("We offer computing degrees."))
    assert s.c.state == "speaking"
    assert Record("reply_latency_ms", 1000) in s.out
    s.at(6.5, AnswerSentence("Ask me about any of them."))
    assert s.ui("say", s.out)[-1]["text"] == "We offer computing degrees. Ask me about any of them."
    s.at(7.0, AnswerDone())
    s.end_speech(9.0)
    assert s.c.state == "listening"
    assert s.c.history == [
        ("What courses do you offer?", "We offer computing degrees. Ask me about any of them.")
    ]


def test_follow_up_question_gets_last_three_turns():
    s = Sim()
    s.to_listening()
    t = 5.0
    for i in range(4):
        s.ask(t, f"q{i}")
        s.at(t + 0.5, AnswerSentence(f"a{i}."))
        s.at(t + 0.6, AnswerDone())
        s.end_speech(t + 1.0)
        t += 2.0
    s.ask(t, "q4")
    assert s.all(Ask)[-1].history == (("q1", "a1."), ("q2", "a2."), ("q3", "a3."))


def test_queue_drain_between_sentences_does_not_end_turn():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "Tell me about LeapGen")
    s.at(6.0, AnswerSentence("LeapGen is a startup programme."))
    s.end_speech(7.0)
    assert s.c.state == "speaking"
    s.at(7.2, AnswerSentence("It helps students launch ideas."))
    s.at(7.3, AnswerDone())
    s.end_speech(9.0)
    assert s.c.state == "listening"


def test_no_first_sentence_within_timeout_falls_back_to_menu():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "What is IIT?")
    s.at(10.9)
    assert s.c.state == "thinking"
    s.at(11.0)
    assert CancelAnswer() in s.out
    assert s.spoken()[-1] == PHRASES.offline
    assert Record("fallback") in s.out
    menu = s.ui("menu", s.out)[0]
    assert menu["show"] is True
    assert [i["id"] for i in menu["items"]] == [m.id for m in PHRASES.menu]


def test_unmatched_question_says_so_and_offers_menu():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "What's the weather on Mars?")
    s.at(6.0, AnswerFailed("unmatched"))
    assert s.spoken()[-1] == PHRASES.unmatched
    assert Record("unmatched") in s.out
    assert s.ui("menu", s.out)[0]["show"] is True
    s.end_speech(8.0)
    assert s.c.state == "listening"
    assert s.c.history == []


def test_stop_cuts_speech_and_listens():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "What courses do you offer?")
    s.at(6.0, AnswerSentence("We offer many courses."))
    s.at(6.5, Touch("stop"))
    assert StopSpeech() in s.out
    assert CancelAnswer() in s.out
    assert s.c.state == "listening"


def test_menu_item_reads_prewritten_answer_even_from_idle():
    s = Sim()
    item = PHRASES.menu[0]
    s.at(1.0, Touch("menu_item", item.id))
    assert s.c.state == "speaking"
    assert s.spoken() == [item.answer]
    assert Record("fallback") in s.out
    s.end_speech(3.0)
    assert s.c.state == "listening"


# ---- leaving ----


def test_no_thanks_releases_visitor_with_goodbye_and_cooldown():
    s = Sim()
    s.to_listening()
    s.at(5.0, SpeechFinal("No thanks, bye"))
    assert s.c.state == "farewell"
    assert s.spoken()[-1] == PHRASES.bye
    assert Record("decline") in s.out
    s.end_speech(7.0)
    assert s.c.state == "idle"
    s.at(8.0, APPROACH)
    assert s.c.state == "idle"
    s.at(27.0, APPROACH)
    assert s.c.state == "greeting"


def test_walk_away_ends_silently_and_resets_session():
    s = Sim()
    s.at(0.5, Touch("kids", True))
    s.to_listening()
    s.ask(5.0, "q")
    s.at(5.5, AnswerSentence("a."))
    s.at(5.6, AnswerDone())
    s.end_speech(6.0)
    s.at(10.0, Presence(0))
    s.at(12.9)
    assert s.c.state == "listening"
    s.at(13.0)
    assert s.c.state == "farewell"
    assert PHRASES.bye not in s.spoken()
    assert Record("walkaway") in s.out
    s.at(15.0)
    assert s.c.state == "idle"
    assert s.c.history == []
    assert s.c.kids is False
    assert {"type": "kids", "value": False} in s.ui("kids", s.out)
    assert any(isinstance(c, Record) and c.type == "conversation_end" for c in s.out)


def test_second_visitor_does_not_interrupt():
    s = Sim()
    s.to_listening()
    s.at(5.0, Presence(2, approaching=True))
    assert s.c.state == "listening"
    assert s.spoken() == [PHRASES.greet]


def test_late_answer_after_visitor_left_is_ignored():
    s = Sim()
    s.to_listening()
    s.ask(5.0, "q")
    s.at(5.5, Presence(0))
    s.at(8.5)
    assert s.c.state == "farewell"
    s.at(9.0, AnswerSentence("late"))
    assert "late" not in s.spoken()
    s.at(11.0)
    s.at(11.5, AnswerDone())
    assert s.c.state == "idle"


def test_tap_to_talk_works_without_camera_and_ends_after_silence():
    s = Sim()
    s.at(0.5, CameraStatus(False))
    assert {"type": "camera", "ok": False} in s.ui("camera")
    s.at(1.0, Touch("talk"))
    assert s.c.state == "greeting"
    s.end_speech(4.0)
    s.at(11.0)
    assert s.c.state == "listening"
    s.at(12.0)
    s.end_speech(14.0)
    s.at(22.0)
    assert s.c.state == "farewell"
    assert s.spoken()[-1] == PHRASES.bye


# ---- decline phrases ----


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Bye!", True),
        ("No thanks", True),
        ("no thank you, that's all", True),
        ("Okay goodbye", True),
        ("What courses are good for someone who wants to say bye to exams", False),
        ("Tell me about IIT", False),
        ("", False),
    ],
)
def test_is_decline(text, expected):
    assert is_decline(text) is expected


def test_config_values_come_from_config_toml():
    cfg = ControllerConfig.from_config(
        {
            "vision": {"dwell_s": 2, "depart_empty_s": 4, "fps_idle": 6, "fps_engaged": 1},
            "engagement": {
                "greet_cooldown_s": 30,
                "silence_followup_s": 9,
                "max_followups": 2,
                "farewell_silent_s": 1,
                "kids_default": True,
            },
            "llm": {"timeout_s": 5},
        }
    )
    assert cfg == ControllerConfig(
        dwell_s=2,
        depart_empty_s=4,
        greet_cooldown_s=30,
        silence_followup_s=9,
        max_followups=2,
        answer_timeout_s=5,
        farewell_silent_s=1,
        fps_idle=6,
        fps_engaged=1,
        kids_default=True,
    )


def test_repo_config_toml_builds_a_controller_config():
    from core.config import load_config

    cfg = ControllerConfig.from_config(load_config("config.toml"))
    assert cfg == ControllerConfig()  # config.toml defaults match the baseline section 9 values


def test_menu_comes_from_set_menu():
    s = Sim()
    s.c.set_menu([MenuItem("7", "Where is IIT?", "In Colombo.")])
    s.to_listening()
    s.ask(5.0, "q")
    s.at(6.0, AnswerFailed("unmatched"))
    assert s.ui("menu", s.out)[0]["items"] == [{"id": "7", "label": "Where is IIT?"}]
    s.end_speech(8.0)
    s.at(9.0, Touch("menu_item", "7"))
    assert s.spoken()[-1] == "In Colombo."


def test_speaking_visitor_does_not_get_a_follow_up():
    s = Sim()
    s.to_listening()
    s.at(10.0, SpeechStarted())
    s.at(13.0)
    assert s.spoken() == [PHRASES.greet]


def test_empty_transcript_resumes_silence_timer():
    s = Sim()
    s.to_listening()
    s.at(10.0, SpeechStarted())
    s.at(13.5, SpeechFinal(""))
    s.at(21.4)
    assert s.spoken() == [PHRASES.greet]
    s.at(21.5)
    assert s.spoken() == [PHRASES.greet, PHRASES.followup]


def test_mic_failure_while_listening_shows_menu():
    s = Sim()
    s.to_listening()
    s.at(5.0, MicStatus(False))
    assert s.ui("menu", s.out)[0]["show"] is True
    assert s.c.mic_ok is False


def test_entering_listening_with_mic_down_shows_menu():
    s = Sim()
    s.at(0.5, MicStatus(False))
    s.at(1.0, APPROACH)
    s.end_speech(4.0)
    assert s.c.state == "listening"
    assert s.ui("menu", s.out)[0]["show"] is True
