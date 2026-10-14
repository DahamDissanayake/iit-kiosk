"""Streaming adapters for Gemini, Anthropic and OpenAI (provider chosen in config.toml)."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from core.llm.prompt import Prompt

# Used when [llm] model is empty. Confirm the final choice with IIT before handover.
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4.1-mini",
}


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    def stream(self, prompt: Prompt) -> AsyncIterator[str]: ...


class _Base:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_tokens: int,
        timeout_s: float,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = httpx.Timeout(timeout_s, connect=3.0)

    async def _events(self, url: str, headers: dict, body: dict) -> AsyncIterator[dict]:
        try:
            async with self.client.stream(
                "POST", url, headers=headers, json=body, timeout=self.timeout
            ) as res:
                if res.status_code != 200:
                    detail = (await res.aread())[:200]
                    raise LLMError(f"HTTP {res.status_code}: {detail!r}")
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    if payload:
                        try:
                            yield json.loads(payload)
                        except ValueError as e:
                            raise LLMError(f"unreadable stream data: {payload[:80]!r}") from e
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e


class GeminiProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:streamGenerateContent?alt=sse"
        )
        body = {
            "systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [
                {
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": m["content"]}],
                }
                for m in prompt.messages
            ],
            "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": 0.3},
        }
        async for event in self._events(url, {"x-goog-api-key": self.api_key}, body):
            for cand in event.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        yield part["text"]


class AnthropicProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": prompt.system,
            "messages": prompt.messages,
            "stream": True,
        }
        async for event in self._events("https://api.anthropic.com/v1/messages", headers, body):
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
            elif event.get("type") == "error":
                raise LLMError(str(event.get("error")))


class OpenAIProvider(_Base):
    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        headers = {"authorization": f"Bearer {self.api_key}"}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": prompt.system}, *prompt.messages],
            "max_completion_tokens": self.max_tokens,
            "stream": True,
        }
        url = "https://api.openai.com/v1/chat/completions"
        async for event in self._events(url, headers, body):
            for choice in event.get("choices", []):
                text = choice.get("delta", {}).get("content")
                if text:
                    yield text


PROVIDERS = {"gemini": GeminiProvider, "anthropic": AnthropicProvider, "openai": OpenAIProvider}


def make_provider(llm_cfg: dict, api_key: str, client: httpx.AsyncClient) -> LLMProvider:
    name = llm_cfg["provider"]
    if name not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {name!r}; use gemini, anthropic or openai.")
    return PROVIDERS[name](
        client,
        api_key,
        llm_cfg["model"] or DEFAULT_MODELS[name],
        llm_cfg["max_output_tokens"],
        llm_cfg["timeout_s"],
    )
