"""Shared helpers for calling the Anthropic API."""

import base64

from anthropic import AsyncAnthropic

from app.config import get_settings


class AIUnavailableError(RuntimeError):
    """Raised when AI features are used without an API key configured."""


def get_client() -> AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AIUnavailableError(
            "AI is not configured: set ANTHROPIC_API_KEY in the backend environment"
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


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
