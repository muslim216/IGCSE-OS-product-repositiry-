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
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Generic, TypedDict, TypeVar

from anthropic import AsyncAnthropic
from anthropic.types import TextBlockParam
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
    "class_brief": AiFeature.report,
    # The stored narrative is a report-shaped paragraph, so it shares that bucket.
    "narrative": AiFeature.report,
}


def resolve_surface(surface: str) -> tuple[AiProvider, str]:
    """(provider, model) for one AI surface, from settings. A blank per-surface
    model falls back to that provider's default model.

    No surface streams today. Streaming was Anthropic-only and existed for the
    student chat surface alone, which 0.3 deleted (AV-57); the provider check
    that went with it went too. Anything added here that needs streaming must
    reject a non-Anthropic provider *at resolve time*, not when the stream is
    opened — routing chat to Gemini once stayed invisible until a student
    opened it, and that is the failure the check existed to prevent."""
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
    model = getattr(settings, f"ai_{surface}_model", "") or (
        settings.gemini_model if provider is AiProvider.gemini else settings.anthropic_model
    )
    return provider, model


ParsedT = TypeVar("ParsedT", bound=BaseModel)


@dataclass
class AiResponse(Generic[ParsedT]):
    """One AI call's result, normalized across providers so callers (and
    record_usage) never branch on which vendor answered.

    Generic in the parsed payload's type: `structured_complete(output_format=X)`
    returns `AiResponse[X]`, so `result: X = response.parsed` at each call site
    (extraction.py, marking.py, readiness_v2_ai.py, syllabus_extraction.py) is
    an assignment mypy actually checks. A bare `Any` here made every one of
    those annotations decorative — the four modules that most need the schema
    guarantee (their `output_format` is the whole contract with the model) were
    exactly the ones mypy could not hold to it. `text_complete` has no schema
    to parametrize by and returns `AiResponse[Any]`."""

    provider: AiProvider
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    parsed: ParsedT | None = None
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


def _anthropic_system(
    system_text: str, extra_system: list[str], cache_extra: bool
) -> list[TextBlockParam]:
    """Assemble Anthropic system blocks. `cache_extra` marks the *last* extra
    block for prompt caching — by convention that's the tutor Knowledge Base,
    which is identical across every call for that tutor and so is worth
    caching; per-student blocks before it are not.

    Typed as the SDK's own `TextBlockParam` rather than `list[dict]` so the
    three call sites need no suppression: a malformed block is then a type
    error here, at the one place blocks are built, instead of being waved
    through at each `system=`."""
    blocks: list[TextBlockParam] = []
    if system_text:
        blocks.append({"type": "text", "text": system_text})
    last = len(extra_system) - 1
    for i, extra in enumerate(extra_system):
        block: TextBlockParam = {"type": "text", "text": extra}
        if cache_extra and i == last:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


def _joined_system(system_text: str, extra_system: list[str]) -> str | None:
    parts = [t for t in [system_text, *extra_system] if t]
    return "\n\n".join(parts) or None


def require_parsed(response: AiResponse[ParsedT]) -> ParsedT:
    """The parsed payload of a `structured_complete` response, typed as
    non-optional.

    `AiResponse.parsed` is `ParsedT | None` on the dataclass because
    `text_complete` never sets it — but every path through `structured_complete`
    itself does: the Anthropic branch returns `response.parsed_output` from an
    SDK call that raises rather than answering with none, and the Gemini branch
    raises `ValueError` itself when `response.parsed` comes back empty. A caller
    that only ever passes a `structured_complete` result through this is
    trading a real (if currently unreachable) `None` for an assertion error with
    a clear message, in exchange for mypy actually checking the schema type
    downstream instead of silently accepting `Any` (the gap this function
    closes — see the `AiResponse` docstring)."""
    if response.parsed is None:
        raise ValueError("structured_complete returned no parsed result")
    return response.parsed


# --------------------------------------------------------------------------
# Unified completion helpers
# --------------------------------------------------------------------------


async def structured_complete(
    *,
    surface: str,
    content: list[dict],
    output_format: type[ParsedT],
    max_tokens: int,
    extra_system: list[str] | None = None,
    cache_extra_system: bool = False,
) -> AiResponse[ParsedT]:
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
            system=_anthropic_system(prompt.system, extras, cache_extra_system),
            # `content` is list[dict] by this module's contract (see the module
            # docstring): call sites build Anthropic-shaped blocks, and the
            # Gemini branch below translates the same dicts. The SDK's block
            # union cannot type that without every caller — marking, extraction,
            # syllabus — importing SDK types, which would put a vendor SDK in
            # modules AI-1 keeps it out of. file_block() is the constructor that
            # holds the shape (CODE-26).
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
        **_gemini_usage(response),
    )


async def text_complete(
    *,
    surface: str,
    prompt: str,
    max_tokens: int,
    extra_system: list[str] | None = None,
) -> AiResponse[Any]:
    """A plain-text completion for one surface. Never sets `parsed` — there is
    no schema to parametrize `AiResponse` by, so callers get `Any` for it."""
    provider, model = resolve_surface(surface)
    template = get_prompt(surface)
    extras = extra_system or []

    if provider is AiProvider.anthropic:
        client = get_client()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_anthropic_system(template.system, extras, False),
            # `prompt` is a plain str, which the SDK's MessageParam does accept;
            # mypy cannot see that through the dict literal's inferred value
            # type. Nothing shape-dependent is masked (CODE-26).
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


class _GeminiUsage(TypedDict):
    """The exact keys _gemini_usage yields.

    A plain `dict[str, int]` would type-check only where the caller happens to
    pass `text=` itself: unpacking it into AiResponse otherwise offers an int to
    `text: str`. Naming the two keys lets mypy match them to the two int fields
    and leaves the `**` unpacking checked rather than suppressed."""

    input_tokens: int
    output_tokens: int


def _gemini_usage(response: object) -> _GeminiUsage:
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
