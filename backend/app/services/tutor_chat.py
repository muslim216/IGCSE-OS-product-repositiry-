"""The Academic Tutor: a streaming AI mentor grounded in the student's context.

Guardrails (system prompt + design): teaches and guides, never hands over
complete homework answers. Grounded in the student's readiness and workload so
advice targets real weak topics.
"""

from collections.abc import AsyncIterator

from app.config import get_settings
from app.services.ai import get_client

SYSTEM_PROMPT = """You are an encouraging IGCSE/O Level academic mentor inside a \
tutoring platform. You help the student understand concepts, plan revision, and \
build confidence.

Hard rules — never break these:
- NEVER give complete answers to the student's homework or assignment questions. \
If asked to "do" or "answer" a homework question, refuse warmly and instead teach \
the method, give a worked example on a DIFFERENT problem, ask guiding questions, or \
check their attempt.
- Teach, don't replace learning. Prefer hints, Socratic questions, and worked \
analogies over final answers.
- Be accurate. If unsure, say so; don't invent facts or exam-board specifics.
- Keep answers focused and age-appropriate; use plain language and short steps.

Use the student's context below to personalise: point them at their weak topics, \
reference their upcoming homework, and encourage progress. Do not reveal internal \
readiness percentages as if they were official grades — talk about strengths and \
areas to work on."""


async def stream_reply(context: str, history: list[dict]) -> AsyncIterator[str]:
    """Yield text chunks of the assistant's reply. `history` is a list of
    {"role": "user"|"assistant", "content": str} ending with the new user turn."""
    settings = get_settings()
    client = get_client()
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": f"Student context:\n{context}"},
    ]
    async with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=system,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            yield text
