"""The real Anthropic SDK client, driven against a canned in-process server.

Every other AI test swaps out `structured_complete` with `fake_ai`, so none of
them ever builds the SDK client. That is how a marking call that the SDK refuses
before sending (`max_tokens=32000` on a non-streaming request) went unnoticed.
Here the real `AsyncAnthropic` is built, wired to an `httpx` transport that
answers with server-sent events, so the request-building, the SDK's own
guards and its stream parsing are exercised for real. Nothing leaves the
process and no real key is used (`QA-8`).
"""

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import get_settings
from app.services import ai as ai_service
from app.services.ai import (
    AIKeyMissingError,
    AIOutputTruncatedError,
    AIUnavailableError,
    get_client,
    structured_complete,
    text_complete,
)
from app.services.marking import MARKING_MAX_TOKENS

CONTENT = [{"type": "text", "text": "mark this"}]


class Verdict(BaseModel):
    mark: int
    comment: str


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def sse_message(
    text: str,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 123,
    output_tokens: int = 45,
    model: str = "claude-canned",
) -> bytes:
    """A complete Messages API server-sent-events body carrying `text`."""
    chunks = [text[i : i + 8] for i in range(0, len(text), 8)]
    parts = [
        _event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 1},
                },
            },
        )
    ]
    if text:
        parts.append(
            _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        )
        for chunk in chunks:
            parts.append(
                _event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": chunk},
                    },
                )
            )
        parts.append(_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
    parts.append(
        _event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            },
        )
    )
    parts.append(_event("message_stop", {"type": "message_stop"}))
    return "".join(parts).encode()


class CannedServer:
    """Records every request and answers each with the same SSE body."""

    def __init__(self, body: bytes):
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=self.body)

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


@pytest.fixture
def anthropic_key(monkeypatch):
    # Not a working key: the transport below never reaches the network.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-canned", raising=False)


@pytest.fixture
def serve(monkeypatch, anthropic_key):
    """Point the real client at a CannedServer answering with `body`."""

    def _serve(body: bytes) -> CannedServer:
        server = CannedServer(body)
        monkeypatch.setattr(ai_service, "_transport", httpx.MockTransport(server))
        return server

    return _serve


VERDICT_JSON = json.dumps({"mark": 3, "comment": "Correct method, arithmetic slip."})


async def test_marking_call_with_the_real_limit_reaches_the_transport(serve):
    server = serve(sse_message(VERDICT_JSON))

    response = await structured_complete(
        surface="marking",
        content=CONTENT,
        output_format=Verdict,
        max_tokens=MARKING_MAX_TOKENS,
    )

    assert len(server.requests) == 1
    assert server.sent["stream"] is True
    assert server.sent["max_tokens"] == MARKING_MAX_TOKENS == 32000
    assert response.parsed == Verdict(mark=3, comment="Correct method, arithmetic slip.")
    assert response.input_tokens == 123
    assert response.output_tokens == 45
    assert response.model == "claude-canned"
    assert response.truncated is False


@pytest.mark.parametrize("max_tokens", [400, 2000, 16000, 32000, 64000])
async def test_no_max_tokens_is_refused_client_side_structured(serve, max_tokens):
    server = serve(sse_message(VERDICT_JSON))

    response = await structured_complete(
        surface="marking", content=CONTENT, output_format=Verdict, max_tokens=max_tokens
    )

    assert server.sent["max_tokens"] == max_tokens
    assert response.parsed is not None


@pytest.mark.parametrize("max_tokens", [400, 2000, 16000, 32000, 64000])
async def test_no_max_tokens_is_refused_client_side_text(serve, max_tokens):
    server = serve(sse_message("A short paragraph."))

    response = await text_complete(surface="narrative", prompt="write", max_tokens=max_tokens)

    assert server.sent["max_tokens"] == max_tokens
    assert server.sent["stream"] is True
    assert response.text == "A short paragraph."
    assert response.input_tokens == 123
    assert response.output_tokens == 45
    assert response.truncated is False


async def test_structured_answer_cut_off_mid_json_raises_truncated(serve):
    serve(sse_message(VERDICT_JSON[:20], stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError, match="cut off at the output limit"):
        await structured_complete(
            surface="marking",
            content=CONTENT,
            output_format=Verdict,
            max_tokens=MARKING_MAX_TOKENS,
        )


async def test_structured_answer_with_max_tokens_stop_raises_even_if_json_is_whole(serve):
    # The model hit the limit at the last token: the JSON happens to parse, but
    # "stopped because it ran out of room" is not an answer to trust.
    serve(sse_message(VERDICT_JSON, stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError):
        await structured_complete(
            surface="marking", content=CONTENT, output_format=Verdict, max_tokens=500
        )


async def test_structured_answer_wrong_shape_is_not_called_truncation(serve):
    # A genuine schema fault keeps its own error; only unterminated JSON is
    # read as running out of tokens.
    serve(sse_message(json.dumps({"mark": "three"})))

    with pytest.raises(Exception) as caught:
        await structured_complete(
            surface="marking", content=CONTENT, output_format=Verdict, max_tokens=500
        )
    assert not isinstance(caught.value, AIUnavailableError)


async def test_structured_answer_with_no_text_raises_instead_of_returning_none(serve):
    serve(sse_message(""))

    with pytest.raises(AIUnavailableError, match="no structured result"):
        await structured_complete(
            surface="marking", content=CONTENT, output_format=Verdict, max_tokens=500
        )


async def test_text_cut_off_with_partial_text_is_returned_flagged(serve, caplog):
    serve(sse_message("The class did well on algebra but", stop_reason="max_tokens"))

    with caplog.at_level("WARNING", logger="app.services.ai"):
        response = await text_complete(surface="narrative", prompt="write", max_tokens=400)

    assert response.truncated is True
    assert response.text == "The class did well on algebra but"
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "narrative" in warnings[0].getMessage()
    assert "400" in warnings[0].getMessage()


async def test_text_cut_off_with_no_text_raises(serve):
    serve(sse_message("", stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError):
        await text_complete(surface="narrative", prompt="write", max_tokens=400)


class _NeverAnswers(httpx.AsyncBaseTransport):
    """Accepts the request and then goes silent, like a hung upstream."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


async def test_a_call_that_never_finishes_hits_the_total_time_limit(monkeypatch, anthropic_key):
    monkeypatch.setattr(ai_service, "_transport", _NeverAnswers())
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 0.05, raising=False)

    with pytest.raises(AIUnavailableError, match="did not answer in time") as caught:
        await structured_complete(
            surface="marking", content=CONTENT, output_format=Verdict, max_tokens=500
        )
    assert isinstance(caught.value.__cause__, TimeoutError)

    with pytest.raises(AIUnavailableError, match="did not answer in time"):
        await text_complete(surface="narrative", prompt="write", max_tokens=400)


async def test_gemini_calls_have_the_same_total_time_limit(monkeypatch):
    class _Models:
        async def generate_content(self, **kwargs):
            await asyncio.sleep(3600)

    class _Aio:
        models = _Models()

    class _Gemini:
        aio = _Aio()

    monkeypatch.setattr(get_settings(), "ai_narrative_provider", "gemini", raising=False)
    monkeypatch.setattr(ai_service, "get_gemini_client", lambda: _Gemini())
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 0.05, raising=False)

    with pytest.raises(AIUnavailableError, match="did not answer in time"):
        await text_complete(surface="narrative", prompt="write", max_tokens=400)


async def test_empty_key_still_raises_key_missing(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)

    with pytest.raises(AIKeyMissingError):
        get_client()


async def test_key_is_checked_on_every_call_not_cached(monkeypatch, anthropic_key):
    assert get_client() is not None
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)

    with pytest.raises(AIKeyMissingError):
        get_client()


async def test_client_is_reused_within_a_loop_and_carries_the_configured_limits(
    monkeypatch, anthropic_key
):
    monkeypatch.setattr(get_settings(), "ai_request_timeout_seconds", 42.0, raising=False)
    monkeypatch.setattr(get_settings(), "ai_max_retries", 3, raising=False)

    first = get_client()

    assert get_client() is first
    assert first.max_retries == 3
    assert first.timeout == httpx.Timeout(42.0, connect=5.0)


async def test_changed_settings_build_a_fresh_client(monkeypatch, anthropic_key):
    first = get_client()
    monkeypatch.setattr(get_settings(), "ai_max_retries", 0, raising=False)

    assert get_client() is not first


def test_a_client_is_never_handed_to_a_different_event_loop(monkeypatch, anthropic_key):
    async def grab():
        return get_client()

    first_loop = asyncio.new_event_loop()
    second_loop = asyncio.new_event_loop()
    try:
        a = first_loop.run_until_complete(grab())
        a_again = first_loop.run_until_complete(grab())
        b = second_loop.run_until_complete(grab())
    finally:
        first_loop.close()
        second_loop.close()

    assert a is a_again
    assert b is not a
