"""System prompt and messages for one answer (rules from baseline 4.3)."""

from dataclasses import dataclass

from core.rag.kb import Hit

RULES = """You are the IIT visitor assistant on a kiosk at an exhibition. Your replies are spoken aloud.
Rules:
1. Answer only from the context below. If it does not contain the answer, say briefly that you don't have that information.
2. Reply in 2 or {max_sentences} short spoken sentences at most. No lists, no markdown, no URLs, no emojis.
3. Be warm, respectful and professional.
4. Never ask for or repeat personal information such as names, phone numbers, emails or addresses.
5. Only talk about IIT, LeapGen, programmes, campus, research, startups and events. Politely decline anything else."""

KIDS = (
    "The visitor is a child. Use simple words, be encouraging, celebrate their curiosity and "
    "effort, and never promise success. Never ask them for any personal details."
)


@dataclass(frozen=True)
class Prompt:
    system: str
    messages: list[dict]


def build_prompt(
    question: str,
    hits: list[Hit],
    history: tuple[tuple[str, str], ...],
    kids: bool,
    max_sentences: int,
) -> Prompt:
    context = "\n\n".join(f"[{i}] {h.text}" for i, h in enumerate(hits, start=1))
    parts = [RULES.format(max_sentences=max_sentences)]
    if kids:
        parts.append(KIDS)
    parts.append(f"Context:\n{context}")
    messages: list[dict] = []
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})
    return Prompt("\n\n".join(parts), messages)
