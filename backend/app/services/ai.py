"""The single choke point every AI-calling service routes through.

Two things live here that nothing else may duplicate:

1. **Provider routing.** Each AI *surface* (marking, extraction, syllabus,
   reports, readiness, chat, class_brief) resolves independently to a provider
   (Anthropic or Gemini) and a model via settings, so the expensive surfaces
   and the bulk document-processing surfaces can sit on different vendors
   without touching call sites. Callers name a surface; they never name a
   model.
2. **Metering.** Every call comes back as a normalized AiResponse carrying the
   provider, model, prompt version and token counts, which record_usage()
   writes to ai_usage_events — including an estimated cost_usd when the model
   has a price configured.

Content blocks stay in Anthropic's wire shape (see file_block) because that's
what the call sites already build; the Gemini branch translates them.
"""

import base64
import enum
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AiFeature, AiUsageEvent
from app.services.prompts import get_prompt


class AIUnavailableError(RuntimeError):
    """Raised when AI features are used without an API key configured."""


class AiProvider(str, enum.Enum):
    anthropic = "anthropic"
    gemini = "gemini"


SURFACES = (
    "marking",
    "extraction",
    "syllabus",
    "reports",
    "readiness",
    "chat",
    "class_brief",
    "narrative",
)

# Which ai_usage_events.feature bucket each surface meters into. Several
# surfaces deliberately share a bucket (syllabus is extraction; the class
# brief is a report) — AiFeature is the billing-facing grouping, the surface
# is the routing key.
SURFACE_FEATURE: dict[str, AiFeature] = {
    "marking": AiFeature.marking,
    "extraction": AiFeature.extraction,
    "syllabus": AiFeature.extraction,
    "reports": AiFeature.report,
    "readiness": AiFeature.readiness,
    "chat": AiFeature.chat,
    "class_brief": AiFeature.report,
    # The stored narrative is a report-shaped paragraph, so it shares that bucket.
    "narrative": AiFeature.report,
}

# Streaming is Anthropic-only (see stream_complete). Naming the surfaces that
# need it here, rather than only checking inside stream_complete, means
# resolve_surface() itself rejects a misconfigured route — the check runs
# wherever a surface is resolved, not only at the moment a stream is opened.
SURFACES_REQUIRING_STREAMING = frozenset({"chat"})


def resolve_surface(surface: str, *, require_streaming: bool = False) -> tuple[AiProvider, str]:
    """(provider, model) for one AI surface, from settings. A blank per-surface
    model falls back to that provider's default model.

    `require_streaming=True` rejects a provider that cannot stream immediately,
    instead of resolving successfully and only failing once a caller actually
    tries to open a stream (AI-20: this is a configuration error, not a missing
    key, so it raises rather than degrading — the caller decides whether that
    surfaces at startup or at first request)."""
    if surface not in SURFACES:
        raise ValueError(f"Unknown AI surface '{surface}'")
    settings = get_settings()
    raw_provider = getattr(settings, f"ai_{surface}_provider", "anthropic")
    try:
        provider = AiProvider(raw_provider)
    except ValueError:
        raise ValueError(
            f"AI_{surface.upper()}_PROVIDER is '{raw_provider}'; expected one of "
            + ", ".join(p.value for p in AiProvider)
        ) from None
    if require_streaming and provider is not AiProvider.anthropic:
        raise AIUnavailableError(
            f"Streaming is only supported on Anthropic; set AI_{surface.upper()}_PROVIDER=anthropic"
        )
    model = getattr(settings, f"ai_{surface}_model", "") or (
        settings.gemini_model if provider is AiProvider.gemini else settings.anthropic_model
    )
    return provider, model


@dataclass
class AiResponse:
    """One AI call's result, normalized across providers so callers (and
    record_usage) never branch on which vendor answered."""

    provider: AiProvider
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    parsed: Any = None
    text: str = ""


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------


def get_client() -> AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AIUnavailableError(
            "AI is not configured: set ANTHROPIC_API_KEY in the backend environment"
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def get_gemini_client():
    """The google-genai client. Imported lazily so the SDK stays an optional
    dependency — an install without it runs fine as long as no surface is
    routed to Gemini."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AIUnavailableError(
            "AI is not configured: set GEMINI_API_KEY in the backend environment"
        )
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise AIUnavailableError(
            "The google-genai package is not installed; install it or route this "
            "surface to anthropic"
        ) from exc
    return genai.Client(api_key=settings.gemini_api_key)


# --------------------------------------------------------------------------
# Content blocks
# --------------------------------------------------------------------------


def file_block(data: bytes, mime: str, cache: bool = False) -> dict:
    """Build a document (PDF) or image content block from stored file bytes.

    Anthropic's block shape is the neutral wire format across the app; the
    Gemini branch translates it in _gemini_parts(). `cache` has no effect on
    Gemini (which does its own implicit caching)."""
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


def _gemini_parts(content: list[dict]) -> list[dict]:
    """Translate Anthropic content blocks into google-genai Part dicts."""
    parts: list[dict] = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            parts.append({"text": block["text"]})
        elif kind in ("document", "image"):
            source = block["source"]
            parts.append(
                {
                    "inline_data": {
                        "mime_type": source["media_type"],
                        "data": base64.standard_b64decode(source["data"]),
                    }
                }
            )
        else:
            raise ValueError(f"Cannot send content block of type '{kind}' to Gemini")
    return parts


def _anthropic_system(system_text: str, extra_system: list[str], cache_extra: bool) -> list[dict]:
    """Assemble Anthropic system blocks. `cache_extra` marks the *last* extra
    block for prompt caching — by convention that's the tutor Knowledge Base,
    which is identical across every call for that tutor and so is worth
    caching; per-student blocks before it are not."""
    blocks: list[dict] = []
    if system_text:
        blocks.append({"type": "text", "text": system_text})
    last = len(extra_system) - 1
    for i, extra in enumerate(extra_system):
        block: dict = {"type": "text", "text": extra}
        if cache_extra and i == last:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


def _joined_system(system_text: str, extra_system: list[str]) -> str | None:
    parts = [t for t in [system_text, *extra_system] if t]
    return "\n\n".join(parts) or None


# --------------------------------------------------------------------------
# Unified completion helpers
# --------------------------------------------------------------------------


async def structured_complete(
    *,
    surface: str,
    content: list[dict],
    output_format: type[BaseModel],
    max_tokens: int,
    extra_system: list[str] | None = None,
    cache_extra_system: bool = False,
) -> AiResponse:
    """A structured (schema-constrained) completion for one surface. `content`
    is a list of Anthropic-shaped blocks; `output_format` is a Pydantic model
    both providers are asked to fill in."""
    provider, model = resolve_surface(surface)
    prompt = get_prompt(surface)
    extras = extra_system or []

    if provider is AiProvider.anthropic:
        client = get_client()
        response = await client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=_anthropic_system(prompt.system, extras, cache_extra_system),  # type: ignore[arg-type]
            messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
            output_format=output_format,
        )
        usage = response.usage
        return AiResponse(
            provider=provider,
            model=getattr(response, "model", model),
            prompt_version=prompt.version,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            parsed=response.parsed_output,
        )

    from google.genai import types

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=model,
        contents=_gemini_parts(content),
        config=types.GenerateContentConfig(
            system_instruction=_joined_system(prompt.system, extras),
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=output_format,
        ),
    )
    parsed = response.parsed
    if parsed is None:
        raise ValueError("The AI returned no structured result")
    if isinstance(parsed, dict):  # some SDK versions hand back the raw object
        parsed = output_format.model_validate(parsed)
    return AiResponse(
        provider=provider,
        model=model,
        prompt_version=prompt.version,
        parsed=parsed,
        **_gemini_usage(response),  # type: ignore[arg-type]
    )


async def text_complete(
    *,
    surface: str,
    prompt: str,
    max_tokens: int,
    extra_system: list[str] | None = None,
) -> AiResponse:
    """A plain-text completion for one surface."""
    provider, model = resolve_surface(surface)
    template = get_prompt(surface)
    extras = extra_system or []

    if provider is AiProvider.anthropic:
        client = get_client()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_anthropic_system(template.system, extras, False),  # type: ignore[arg-type]
            messages=[{"role": "user", "content": prompt}],  # type: ignore[typeddict-item]
        )
        usage = response.usage
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return AiResponse(
            provider=provider,
            model=getattr(response, "model", model),
            prompt_version=template.version,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            text=text,
        )

    from google.genai import types

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=model,
        contents=[{"text": prompt}],
        config=types.GenerateContentConfig(
            system_instruction=_joined_system(template.system, extras),
            max_output_tokens=max_tokens,
        ),
    )
    return AiResponse(
        provider=provider,
        model=model,
        prompt_version=template.version,
        text=response.text or "",
        **_gemini_usage(response),
    )


async def stream_complete(
    *,
    surface: str,
    messages: list[dict],
    max_tokens: int,
    extra_system: list[str] | None = None,
    cache_extra_system: bool = False,
    usage: dict | None = None,
) -> AsyncIterator[str]:
    """Stream a reply chunk by chunk. Anthropic-only: streaming is used by the
    student chat surface alone, and adding a second streaming implementation
    for it isn't worth the surface area. When `usage` is passed it is filled in
    with model/provider/prompt_version/token counts once the stream ends, so
    the caller can meter the call on its own session."""
    provider, model = resolve_surface(surface, require_streaming=True)
    template = get_prompt(surface)
    client = get_client()
    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=_anthropic_system(template.system, extra_system or [], cache_extra_system),  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
    ) as stream:
        async for text in stream.text_stream:
            yield text
        if usage is not None:
            final = await stream.get_final_message()
            usage["provider"] = provider.value
            usage["model"] = final.model
            usage["prompt_version"] = template.version
            usage["input_tokens"] = final.usage.input_tokens
            usage["output_tokens"] = final.usage.output_tokens


def _gemini_usage(response: object) -> dict[str, int]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
    }


# --------------------------------------------------------------------------
# Metering
# --------------------------------------------------------------------------

# Per-million-token prices, keyed by model id. Deliberately empty: prices
# change and differ per account, so they are owner-supplied via the
# AI_MODEL_PRICING env var rather than guessed in code. A model with no entry
# records cost_usd = NULL — the analytics endpoint reports unknown cost as
# unknown instead of inventing a number.
MODEL_PRICING: dict[str, dict[str, float]] = {}


@lru_cache
def model_pricing() -> dict[str, dict[str, float]]:
    """MODEL_PRICING merged with the AI_MODEL_PRICING env override (env wins).
    Malformed JSON is ignored rather than breaking every AI call."""
    prices = dict(MODEL_PRICING)
    raw = get_settings().ai_model_pricing
    try:
        configured = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return prices
    if isinstance(configured, dict):
        for model, entry in configured.items():
            if isinstance(entry, dict):
                prices[model] = entry
    return prices


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """None when the model has no configured price — never a guess."""
    entry = model_pricing().get(model)
    if not entry:
        return None
    try:
        return round(
            input_tokens / 1_000_000 * float(entry.get("input_per_1m", 0))
            + output_tokens / 1_000_000 * float(entry.get("output_per_1m", 0)),
            6,
        )
    except (TypeError, ValueError):
        return None


async def record_usage(
    session: AsyncSession,
    response: AiResponse,
    *,
    organization_id: int,
    tutor_id: int,
    student_id: int | None,
    feature: AiFeature,
) -> None:
    """Record one AI call's usage, including its provider, prompt version and
    estimated cost. Best-effort: anything that isn't a normalized AiResponse
    (e.g. a test double) is skipped rather than breaking the calling feature."""
    if not isinstance(response, AiResponse):
        return
    session.add(
        AiUsageEvent(
            organization_id=organization_id,
            tutor_id=tutor_id,
            student_id=student_id,
            feature=feature,
            provider=response.provider.value,
            model=response.model,
            prompt_version=response.prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=estimate_cost_usd(
                response.model, response.input_tokens, response.output_tokens
            ),
        )
    )
