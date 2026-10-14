"""Events the controller receives and commands it returns."""

from dataclasses import dataclass, field

# ---- events ----


@dataclass(frozen=True)
class Presence:
    """Snapshot from vision. cx, cy are the target's box centre in -1..1."""

    count: int
    approaching: bool = False
    cx: float = 0.0
    cy: float = 0.0


@dataclass(frozen=True)
class SpeechFinal:
    text: str


@dataclass(frozen=True)
class SpeechEnded:
    """The UI finished playing every queued audio chunk up to and including `id`."""

    id: str


@dataclass(frozen=True)
class AnswerSentence:
    text: str


@dataclass(frozen=True)
class AnswerDone:
    pass


@dataclass(frozen=True)
class AnswerFailed:
    kind: str  # "unmatched" or "offline"


@dataclass(frozen=True)
class Touch:
    event: str  # "talk", "stop", "kids", "menu_item"
    value: object = None


@dataclass(frozen=True)
class CameraStatus:
    ok: bool


@dataclass(frozen=True)
class Tick:
    pass


Event = (
    Presence
    | SpeechFinal
    | SpeechEnded
    | AnswerSentence
    | AnswerDone
    | AnswerFailed
    | Touch
    | CameraStatus
    | Tick
)

# ---- commands ----


@dataclass(frozen=True)
class UiSend:
    msg: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Speak:
    id: str
    text: str


@dataclass(frozen=True)
class StopSpeech:
    pass


@dataclass(frozen=True)
class MicMute:
    muted: bool


@dataclass(frozen=True)
class VisionRate:
    fps: float


@dataclass(frozen=True)
class Ask:
    question: str
    history: tuple[tuple[str, str], ...]
    kids: bool


@dataclass(frozen=True)
class CancelAnswer:
    pass


@dataclass(frozen=True)
class Record:
    type: str
    value: float | None = None


Command = UiSend | Speak | StopSpeech | MicMute | VisionRate | Ask | CancelAnswer | Record
