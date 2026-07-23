"""Shared helpers for calling the Anthropic API — the single choke point
every AI-calling service routes through, so usage metering lives in one
place (record_usage) instead of being reimplemented per feature."""

import base64

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AiFeature, AiUsageEvent


class AIUnavailableError(RuntimeError):
    """Raised when AI features are used without an API key configured."""


def get_client() -> AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AIUnavailableError(
            "AI is not configured: set ANTHROPIC_API_KEY in the backend environment"
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


async def record_usage(
    session: AsyncSession,
    response: object,
    *,
    organization_id: int,
    tutor_id: int,
    student_id: int | None,
    feature: AiFeature,
) -> None:
    """Record one AI call's token usage. Best-effort: a response missing the
    expected `.model`/`.usage` shape (e.g. a test double) is silently skipped
    rather than breaking the feature that made the call."""
    model = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    if model is None or usage is None:
        return
    session.add(
        AiUsageEvent(
            organization_id=organization_id,
            tutor_id=tutor_id,
            student_id=student_id,
            feature=feature,
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
    )


def file_block(data: bytes, mime: str, cache: bool = False) -> dict:
    """Build a document (PDF) or image content block from stored file bytes."""
    b64 = base64.standard_b64encode(data).decode()
    if mime == "application/pdf":
        block: dict = {
            "type": "document",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        }
    else:
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        }
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block
