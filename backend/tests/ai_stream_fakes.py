"""A canned Anthropic server for tests that need the REAL SDK client.

Shared by `test_ai_real_client.py` and the tests of callers that must show how a
real failure surfaces (`QA-8`: nothing here reaches a network or needs a working
key). Point `app.services.ai._transport` at `http.MockTransport(CannedServer(...))`.
"""

import asyncio
import importlib
import json

import anthropic

# The SDK sits on whichever HTTP library it vendors (`httpx` up to 0.x, `httpx2`
# from 1.x), and a transport from the wrong one is ignored or rejected. Read it
# off the SDK's own public client class; this is the only place that is decided.
_client_base = next(
    c for c in anthropic.DefaultAsyncHttpxClient.__mro__ if c.__name__ == "AsyncClient"
)
http = importlib.import_module(_client_base.__module__.split(".")[0])

VERDICT_JSON = json.dumps({"mark": 3, "comment": "Correct method, arithmetic slip."})


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def sse_message(
    text: str | list[str],
    *,
    thinking: str | None = None,
    stop_reason: str | None = "end_turn",
    input_tokens: int = 123,
    output_tokens: int = 45,
    model: str = "claude-canned",
) -> bytes:
    """A complete Messages API server-sent-events body carrying `text` as one text
    block (empty if `text` is), or as one block per item if it is a list.
    `stop_reason=None` leaves out the closing `message_delta`, like a connection
    that dropped before the end."""
    blocks = [text] if isinstance(text, str) else text
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
    index = 0
    if thinking is not None:
        parts += [
            _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                },
            ),
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "thinking_delta", "thinking": thinking},
                },
            ),
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "signature_delta", "signature": "sig"},
                },
            ),
            _event("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
        index += 1
    for block_text in blocks:
        parts.append(
            _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        )
        for i in range(0, len(block_text), 8):
            parts.append(
                _event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": block_text[i : i + 8]},
                    },
                )
            )
        parts.append(_event("content_block_stop", {"type": "content_block_stop", "index": index}))
        index += 1
    if stop_reason is not None:
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


def json_message(text: str) -> dict:
    """The same answer as a non-streaming Messages API response body."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-canned",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class CannedServer:
    """Records every request. Answers a streaming request with `body` and a
    plain one (only `messages.parse` makes those) with a JSON message."""

    def __init__(self, body: bytes):
        self.body = body
        self.requests: list = []

    def __call__(self, request):
        self.requests.append(request)
        if json.loads(request.content).get("stream"):
            return http.Response(
                200, headers={"content-type": "text/event-stream"}, content=self.body
            )
        return http.Response(200, json=json_message(VERDICT_JSON))

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


class Trickle(http.AsyncByteStream):
    """A response that never ends: it sends one heartbeat after another, so the
    SDK's per-read silence timeout never fires. Only a total limit can stop it."""

    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        while True:
            yield b": heartbeat\n\n"
            await asyncio.sleep(0.01)

    async def aclose(self):
        self.closed = True


class Dropping(http.AsyncByteStream):
    """A 200 that delivers the first half of the events, then fails with `error`
    while the body is being read — the point the SDK no longer wraps errors."""

    def __init__(self, body: bytes, error: Exception):
        cut = body.index(b"event: content_block_stop")
        self.first_half = body[:cut]
        self.error = error

    async def __aiter__(self):
        yield self.first_half
        raise self.error

    async def aclose(self):
        pass


def dropping_transport(body: bytes, error: Exception):
    return http.MockTransport(
        lambda request: http.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Dropping(body, error)
        )
    )
