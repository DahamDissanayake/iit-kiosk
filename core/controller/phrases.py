"""Fixed spoken lines and the touch-menu answers.

The menu answers are placeholders until IIT supplies approved content; M2 moves them
into the knowledge base as `menu` sources.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    id: str
    label: str
    answer: str


@dataclass(frozen=True)
class Phrases:
    greet: str
    group_greet: str
    kids_greet: str
    followup: str
    bye: str
    unmatched: str
    offline: str
    menu: tuple[MenuItem, ...]


PHRASES = Phrases(
    greet=(
        "Hi! Welcome to IIT. I'm your digital assistant. Ask me about our courses, "
        "the campus, or how LeapGen helps turn ideas into startups."
    ),
    group_greet=(
        "Hello everyone! Welcome to IIT. Ask me anything about our courses, campus or LeapGen."
    ),
    kids_greet=(
        "Hi there, young innovator! Have you ever had an idea to make something better? "
        "Ask me anything about IIT!"
    ),
    followup="Feel free to ask me anything whenever you're ready.",
    bye="Thank you for stopping by. Have a wonderful day!",
    unmatched="Sorry, I don't have that information. You can pick a question on the screen.",
    offline="I can't reach my answers right now. Please pick a question on the screen.",
    menu=(
        MenuItem("programmes", "What can I study at IIT?", "Placeholder answer about programmes."),
        MenuItem("campus", "Where is the campus?", "Placeholder answer about the campus."),
        MenuItem("leapgen", "What is LeapGen?", "Placeholder answer about LeapGen."),
        MenuItem("events", "What's on today?", "Placeholder answer about today's events."),
    ),
)

DECLINES = (
    "bye",
    "goodbye",
    "good bye",
    "no thanks",
    "no thank you",
    "that's all",
    "that is all",
    "nothing else",
    "i'm done",
    "i am done",
    "see you",
)


def is_decline(text: str) -> bool:
    """True for short goodbyes like "No thanks, bye!"; long questions never count."""
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    if not words or len(words) > 6:
        return False
    joined = f" {' '.join(words)} "
    return any(f" {d} " in joined for d in DECLINES)
