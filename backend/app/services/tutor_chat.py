"""The Academic Tutor: a streaming AI mentor grounded in the student's context.

Guardrails (system prompt + design): teaches and guides, never hands over
complete homework answers. Grounded in the student's readiness and workload so
advice targets real weak topics.
"""

from collections.abc import AsyncIterator

from app.services.ai import stream_complete


async def stream_reply(
    context: str,
    history: list[dict],
    *,
    kb_context: str = "",
    usage: dict | None = None,
) -> AsyncIterator[str]:
    """Yield text chunks of the assistant's reply. `history` is a list of
    {"role": "user"|"assistant", "content": str} ending with the new user turn.

    `kb_context` (the tutor's Knowledge Base, see services/knowledge.py) is
    injected as its own cached system block so the AI behaves like that
    specific tutor.

    When `usage` is passed, it is filled in with {"provider", "model",
    "prompt_version", "input_tokens", "output_tokens"} once the stream
    finishes, so the caller can meter the call with its own (possibly fresher)
    DB session — see api/chat.py."""
    extra_system = [f"Student context:\n{context}"]
    if kb_context:
        extra_system.append(kb_context)
    stream = stream_complete(
        surface="chat",
        messages=history,
        max_tokens=2000,
        extra_system=extra_system,
        cache_extra_system=True,
        usage=usage,
    )
    async for text in stream:
        yield text
