import asyncio
import json

import httpx
import pytest

from core.llm.prompt import Prompt
from core.llm.providers import LLMError, make_provider

PROMPT = Prompt("SYSTEM", [{"role": "user", "content": "Hi"}])


def sse(events, done=False):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def run(provider_name, response_body, status=200):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            status, content=response_body, headers={"content-type": "text/event-stream"}
        )

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            p = make_provider(
                {
                    "provider": provider_name,
                    "model": "m1",
                    "timeout_s": 6,
                    "max_output_tokens": 200,
                },
                "KEY",
                client,
            )
            return "".join([t async for t in p.stream(PROMPT)])

    return asyncio.run(go()), seen


def test_gemini_streams_text():
    body = sse(
        [
            {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "there."}]}}]},
        ]
    )
    text, seen = run("gemini", body)
    assert text == "Hello there."
    assert seen["url"].endswith("/models/m1:streamGenerateContent?alt=sse")
    assert seen["headers"]["x-goog-api-key"] == "KEY"
    assert seen["json"]["systemInstruction"] == {"parts": [{"text": "SYSTEM"}]}
    assert seen["json"]["contents"] == [{"role": "user", "parts": [{"text": "Hi"}]}]


def test_anthropic_streams_text():
    body = sse(
        [
            {"type": "message_start"},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi "}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "you."}},
            {"type": "message_stop"},
        ]
    )
    text, seen = run("anthropic", body)
    assert text == "Hi you."
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "KEY"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["json"]["system"] == "SYSTEM"
    assert seen["json"]["stream"] is True
    assert seen["json"]["max_tokens"] == 200


def test_openai_streams_text():
    body = sse(
        [{"choices": [{"delta": {"content": "Yes"}}]}, {"choices": [{"delta": {"content": "."}}]}],
        done=True,
    )
    text, seen = run("openai", body)
    assert text == "Yes."
    assert seen["headers"]["authorization"] == "Bearer KEY"
    assert seen["json"]["messages"][0] == {"role": "system", "content": "SYSTEM"}


def test_http_error_raises_llm_error():
    with pytest.raises(LLMError):
        run("anthropic", b'{"error": "bad key"}', status=401)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        make_provider(
            {"provider": "other", "model": "", "timeout_s": 6, "max_output_tokens": 200},
            "KEY",
            httpx.AsyncClient(),
        )


def test_timeout_raises_llm_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            p = make_provider(
                {"provider": "gemini", "model": "m", "timeout_s": 6, "max_output_tokens": 200},
                "KEY",
                client,
            )
            return [t async for t in p.stream(PROMPT)]

    with pytest.raises(LLMError):
        asyncio.run(go())


def test_garbled_stream_data_raises_llm_error():
    with pytest.raises(LLMError, match="unreadable"):
        run("openai", b"data: {not json}\n\n")
