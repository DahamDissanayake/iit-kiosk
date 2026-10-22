"""Splits streamed LLM text into speakable sentences as soon as each one is complete."""

import re

ABBREVIATIONS = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "st",
    "e.g",
    "i.e",
    "etc",
    "vs",
    "no",
    "dept",
    "rs",
    "approx",
    "est",  # "Rs." is the rupee sign in Sri Lankan prices
}
END = re.compile(r"[.!?]+[\"')\]]*\s")


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"^\s*([-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceSplitter:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        start = 0
        for m in END.finditer(self._buf):
            candidate = self._buf[start : m.end()]
            last_word = re.findall(r"[\w.]+(?=[.!?]+[\"')\]]*\s$)", candidate)
            if last_word and last_word[-1].lower().rstrip(".") in ABBREVIATIONS:
                continue
            sentence = clean_for_speech(candidate)
            if sentence:
                out.append(sentence)
            start = m.end()
        self._buf = self._buf[start:]
        return out

    def flush(self) -> list[str]:
        rest = clean_for_speech(self._buf)
        self._buf = ""
        return [rest] if rest else []
