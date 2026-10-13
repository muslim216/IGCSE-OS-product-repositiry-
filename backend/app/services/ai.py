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

import asyncio
import base64
import contextlib
import enum
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Generic, TypedDict, TypeVar

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import TextBlockParam
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AiFeature, AiUsageEvent
from app.services.prompts import get_prompt

log = logging.getLogger(__name__)


class AIUnavailableError(RuntimeError):
    """Raised when AI features are used without an API key configured."""


class AIKeyMissingError(AIUnavailableError):
    """The routed provider's API key is not set. Narrower than its parent so a
    caller can degrade for exactly this (`AI-20`, `INF-9`) without also
    swallowing a missing optional SDK or a misrouted provider, which are
    deployment faults that should fail loudly."""

    #: Read by the job worker (`workers/jobs.py:is_permanent`): a second
    #: attempt a minute later meets the same missing key, so the job is not
    #: retried. Only this subclass is marked; the parent keeps its retry.
    job_retryable = False


# Said in more than one place, so defined once. Tests assert on the literal text
# on purpose, so a reworded message still fails one.
_TIMEOUT_MESSAGE = "The AI did not answer in time"
_INTERRUPTED_MESSAGE = "The AI's answer was interrupted"


class AICallFailedError(RuntimeError):
    """A call to the model was made and produced no usable answer.

    Deliberately *not* a subclass of `AIUnavailableError`. That type has always
    meant "AI is not configured", and callers degrade quietly on it —
    `narrative.py` catches it and stores nothing, with no retry. A one-off
    timeout or a cut-off answer is a transient failure of a configured system;
    if it were swallowed the same way the work would be silently dropped where
    it used to fail the job and be retried. Keeping the two apart in the type
    hierarchy means no caller has to learn the difference.

    `model` and the token counts are filled whenever the stream delivered a final
    message with usage, so a later change can record what a failed call cost.

    `job_retryable` is what the job worker reads (`workers/jobs.py:is_permanent`)
    to decide whether the job's one retry is worth making. True unless the
    failure is one the same request would meet again: an answer cut off at the
    output limit, a refusal, an input too large to read, or a request the
    provider rejected outright (a bad key, an unknown model, a malformed
    request). A timeout, a dropped connection, a rate limit and a provider
    fault all keep the retry."""

    job_retryable: bool = True

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        job_retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        # Left to the class default unless a raise site says otherwise, so a
        # subclass can decide for all of its instances.
        if job_retryable is not None:
            self.job_retryable = job_retryable


class AIOutputTruncatedError(AICallFailedError):
    """The model stopped at the output limit before it finished answering.

    Its own type so a caller (or a log search) can tell "raise the limit" from
    "the AI is down". Before this, a cut-off structured answer surfaced as a
    pydantic schema error about unterminated JSON, which looked like a model
    fault rather than a limit.

    Not retried: the same request stops at the same limit, and each attempt
    bills the whole cut-off answer."""

    job_retryable = False


class AITimeoutError(AICallFailedError):
    """The AI did not answer in time — either the whole-call deadline or the
    SDK's per-request silence timeout. Both kinds look the same to a caller."""


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
    # Condenses a tutor's marking rules into what the marking prompt is given
    # (task 3.2c). A separate surface rather than a mode of "marking" because it
    # is routed, priced and metered as its own call — and because `AI-2` says a
    # call site names a surface, and "summarise these rules" is not "mark this
    # work".
    "marking_rules",
    # Reads an uploaded booklet into the list of whole papers inside it. Its own
    # surface rather than a mode of "extraction" because it answers a different
    # question — which papers are in here and on which pages, not which
    # questions — and `AI-2` routes per surface.
    "booklet",
    # Tags a settled submission's lost-marks questions with the tutor's own
    # mistake categories and the topics the question tests (task 4.2). Its own
    # surface rather than a mode of "marking": it answers "what went wrong and
    # why", not "how many marks", it runs text-only off `ai_feedback` where
    # marking is document work, and `mark_submission` already skips the model
    # entirely once every question is decided (services/marking.py:397-400) —
    # so tagging cannot ride on that call and needs its own routing, pricing
    # and metering (`AI-2`).
    "mistake_tagging",
    # Relative chapter weights for the teaching plan (task 6.3, AV-14, E5). Its
    # own surface because it is routed and metered on its own: a judgement about
    # a syllabus and a tutor's guidance document, not about a student's work or
    # a document's structure (`AI-2`).
    "plan_weighting",
)

# Which ai_usage_events.feature bucket each surface meters into. Several
# surfaces deliberately share a bucket (syllabus is extraction; the class
# brief is a report) — AiFeature is the billing-facing grouping, the surface
# is the routing key.
SURFACE_FEATURE: dict[str, AiFeature] = {
    "marking": AiFeature.marking,
    "extraction": AiFeature.extraction,
    "syllabus": AiFeature.extraction,
    # Billed as extraction: reading a document the tutor uploaded, same bucket.
    "booklet": AiFeature.extraction,
    "reports": AiFeature.report,
    "readiness": AiFeature.readiness,
    "class_brief": AiFeature.report,
    "marking_rules": AiFeature.marking_rules,
    # The stored narrative is a report-shaped paragraph, so it shares that bucket.
    "narrative": AiFeature.report,
    # Its own bucket, not `marking`: reusing marking's would bury tagging's
    # spend inside marking's and make "what does tagging cost" unanswerable
    # (PROD-1) — see the AiFeature.mistake_tagging comment in models/ai_usage.py.
    "mistake_tagging": AiFeature.mistake_tagging,
    # Own bucket for the same reason as mistake_tagging: "what does planning
    # cost" must not vanish into another feature's total (PROD-1).
    "plan_weighting": AiFeature.plan_weighting,
}


def resolve_surface(surface: str) -> tuple[AiProvider, str]:
    """(provider, model) for one AI surface, from settings. A blank per-surface
    model falls back to that provider's default model.

    No surface streams *to a user* today. User-facing streaming was
    Anthropic-only and existed for the student chat surface alone, which 0.3
    deleted (AV-57); the provider check that went with it went too. (The
    Anthropic helpers below do use the SDK's streaming transport, but only to
    receive one complete answer — nothing reaches a browser incrementally, so
    that is not a surface that streams and needs no provider check.) Anything
    added here that streams to a user must reject a non-Anthropic provider *at
    resolve time*, not when the stream is opened — routing chat to Gemini once
    stayed invisible until a student opened it, and that is the failure the
    check existed to prevent."""
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
    # Stripped before the fallback: a per-surface model saved as a lone space is
    # truthy, and would otherwise go to the provider as the model id.
    model = (getattr(settings, f"ai_{surface}_model", "") or "").strip() or (
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
    #: The model stopped at `max_tokens` rather than finishing. Only the Anthropic
    #: branches can know this; Gemini leaves it False. `structured_complete`
    #: raises instead of returning a cut-off answer, so it is only ever True on
    #: a `text_complete` result, where a partial paragraph is still usable.
    truncated: bool = False


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------


# Test seam: when set, the Anthropic client sends through this transport instead
# of the network, so tests can drive the real SDK (request building, streaming,
# the max_tokens guard) against a canned server. None in production, which keeps
# the SDK's own default transport. Typed loosely on purpose: the SDK is built on
# whichever HTTP library it vendors (httpx before 1.x, httpx2 since), and this
# module must not import either — only the SDK's own re-exports.
_transport: Any = None

# (event loop, settings fingerprint, client). One slot, not a dict: production
# has one loop and so one client, and a client's connection pool is bound to the
# loop it first ran on, so a client must never be handed to a different one.
# pytest gives every test its own loop; a single slot means a later test simply
# replaces the entry instead of inheriting a client bound to another loop.
_client_slot: tuple[asyncio.AbstractEventLoop, tuple[Any, ...], AsyncAnthropic] | None = None


def get_client() -> AsyncAnthropic:
    global _client_slot
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AIKeyMissingError(
            "AI is not configured: set ANTHROPIC_API_KEY in the backend environment"
        )
    # Everything that shapes the client is in the fingerprint, because tests (and
    # a rotated key) change settings at runtime and must not get a stale client.
    fingerprint = (
        settings.anthropic_api_key,
        settings.ai_request_timeout_seconds,
        settings.ai_max_retries,
        _transport,
    )

    def build() -> AsyncAnthropic:
        return AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            # connect is fixed and short: an unreachable host should fail fast
            # rather than spend the whole read timeout finding out.
            timeout=anthropic.Timeout(settings.ai_request_timeout_seconds, connect=5.0),
            max_retries=settings.ai_max_retries,
            http_client=(
                anthropic.DefaultAsyncHttpxClient(transport=_transport) if _transport else None
            ),
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # called outside a loop: nothing to bind a cache to
        return build()
    slot = _client_slot
    if slot is not None and slot[0] is loop and slot[1] == fingerprint:
        return slot[2]
    client = build()
    _client_slot = (loop, fingerprint, client)
    return client


@contextlib.asynccontextmanager
async def _call_deadline(surface: str, limit: float) -> AsyncIterator[None]:
    """Cap the total time of one provider call, and make both kinds of timeout
    look the same to a caller.

    The client's own timeout only bounds a single silent request, and with a
    streamed answer the clock restarts on every chunk, so a connection that
    trickles bytes could hold the worker — which shares the API's event loop —
    for as long as it likes. This is the bound on the whole call (`BE-13`). The
    SDK's per-request timeout (`APITimeoutError`) is translated here too, so a
    caller handles one timeout type."""
    try:
        async with asyncio.timeout(limit) as deadline:
            yield
    except TimeoutError as exc:
        # Only a timeout that is ours: a TimeoutError raised from inside the call
        # for another reason must not be relabelled as the deadline.
        if not deadline.expired():
            raise
        log.error("AI call on surface %r exceeded its %ss deadline", surface, limit)
        raise AITimeoutError(_TIMEOUT_MESSAGE) from exc
    except anthropic.APITimeoutError as exc:
        log.error("AI request on surface %r timed out", surface)
        raise AITimeoutError(_TIMEOUT_MESSAGE) from exc


# Module roots of the HTTP stack the SDK sits on. Named, not imported: this
# module must not import either library (the SDK vendors `httpx2` from 1.x,
# `httpx` before), and which one is installed changes with the SDK version.
_HTTP_STACK_ROOTS = frozenset({"httpx", "httpx2", "httpcore", "httpcore2"})


def _from_http_stack(exc: BaseException) -> bool:
    """Whether `exc` is an error of the HTTP library under the SDK. Decided by
    the class's module name rather than `isinstance`, because the point is to
    recognise errors from libraries we deliberately do not import. The SDK wraps
    transport errors only while it sends the request; once the response body is
    being read they escape as themselves."""
    return type(exc).__module__.split(".")[0] in _HTTP_STACK_ROOTS


def _is_timeout(exc: BaseException) -> bool:
    return any(
        cls.__name__ == "TimeoutException" or cls.__name__.endswith("Timeout")
        for cls in type(exc).__mro__
    )


#: What a person is told for each kind of failure the provider reports, and
#: whether asking again could go differently. The wording is shown to a tutor
#: as it is (`submission.ai_error`, `extraction_error`, the class brief), so it
#: says what happened and carries no key, request id or provider text; those go
#: to the log. Keyed by the provider's own error type rather than the HTTP
#: status, because an error that arrives partway through a streamed answer has
#: a type and a status of 200.
_REJECTED = ("The AI provider rejected the request", False)
_PROVIDER_FAULT = ("The AI provider had a problem", True)
_BILLING = ("The AI provider's account has a billing problem", False)
_FAILURES_BY_KIND: dict[str, tuple[str, bool]] = {
    "invalid_request_error": _REJECTED,
    "authentication_error": ("The AI provider did not accept the API key", False),
    "billing_error": _BILLING,
    "permission_error": ("The AI provider refused access for this API key", False),
    "not_found_error": ("The AI provider does not have the model that was asked for", False),
    "request_too_large": ("The request was too large for the AI provider", False),
    "rate_limit_error": (
        "The AI provider is limiting how many requests it accepts right now",
        True,
    ),
    "overloaded_error": ("The AI provider is overloaded right now", True),
    "timeout_error": ("The AI provider took too long to answer", True),
    "api_error": _PROVIDER_FAULT,
}
#: The error type each status means, for a response that carries no readable
#: body. 422 is the provider's other way of saying the request was malformed.
_KIND_BY_STATUS = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "billing_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    422: "invalid_request_error",
    429: "rate_limit_error",
    504: "timeout_error",
    529: "overloaded_error",
}
#: The 4xx statuses that are about the moment and not the request. The SDK
#: retries exactly these and no other 4xx, and the worker follows it.
_TRANSIENT_4XX = frozenset({408, 409, 429})

#: A rejected request is the one failure a tutor can sometimes fix themselves,
#: by uploading the file again. The provider says which in its own words, so
#: those words are read for a few known phrases; anything unrecognised gets the
#: general sentence. Matching the provider's wording is fragile on purpose-built
#: text, which is why a miss costs only a vaguer message, never a wrong retry:
#: every row here is as final as the general one.
_UNREADABLE_FILE = (
    "The AI provider could not read one of the files. It may be damaged, "
    "password-protected, too long or too large"
)
_INPUT_TOO_LARGE = "The input was too large for the AI to read in one go"
_REJECTION_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("credit balance", "billing"), _BILLING[0]),
    (("prompt is too long", "too many tokens", "context window"), _INPUT_TOO_LARGE),
    (("pdf", "image", "password", "pages"), _UNREADABLE_FILE),
)
#: How much of the provider's own text one log line keeps. It normally names a
#: field of the request; nothing promises it stays short.
_PROVIDER_TEXT_LOG_LIMIT = 500


def _provider_error_detail(exc: anthropic.APIStatusError) -> tuple[str | None, str]:
    """The provider's error type and message, read from the response body when
    it has the usual shape and from the exception otherwise."""
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error")
    error = error if isinstance(error, dict) else {}
    kind = error.get("type") or getattr(exc, "type", None)
    text = error.get("message") or str(exc)
    return (kind if isinstance(kind, str) else None), str(text)


def _classify_provider_failure(status: int, kind: str | None, text: str) -> tuple[str, bool]:
    """Message and `job_retryable` for a failure the provider reported.

    An error status decides on its own. Below 400 the error came inside a
    streamed answer that had already started as a 200, and only its type says
    what it was. An unlisted 4xx is not retried and an unlisted anything else
    is, which is the SDK's own rule for what a second request can change."""
    known = _KIND_BY_STATUS.get(status) if status >= 400 else kind
    if known not in _FAILURES_BY_KIND:
        permanent = 400 <= status < 500 and status not in _TRANSIENT_4XX
        return _REJECTED if permanent else _PROVIDER_FAULT
    message, retryable = _FAILURES_BY_KIND[known]
    if known == "invalid_request_error":
        lowered = text.lower()
        for phrases, specific in _REJECTION_PHRASES:
            if any(phrase in lowered for phrase in phrases):
                return specific, False
    return message, retryable


@contextlib.asynccontextmanager
async def _provider_errors_as_ai_errors(surface: str) -> AsyncIterator[None]:
    """Turn what the provider or the HTTP library under it raises into one of
    our own errors, so a caller sees one family (`AICallFailedError`), a
    readable message instead of a bare class name (`submission.ai_error` was
    just "ReadTimeout"), and a `job_retryable` flag the job worker can act on.
    Wraps the whole stream block, so it also covers an error raised while
    leaving it.

    Four sources. A failure the provider reported (`APIStatusError`), either as
    the status of the response or as an error event inside an answer that had
    begun; the SDK has already made its own retry by the time one reaches here.
    A request that never got an answer (`APIConnectionError`; its timeout
    subclass is translated further in, by `_call_deadline`). Any other error of
    the SDK's own, such as a response it could not parse. And a raw
    HTTP-library error from partway through the answer, which the SDK does not
    wrap.

    Everything else — `ValidationError`, our own errors, cancellation — passes
    through untouched. Each branch logs what it swallowed: the message a caller
    gets is written for a tutor and leaves out what an operator needs."""
    try:
        yield
    except anthropic.APIStatusError as exc:
        kind, text = _provider_error_detail(exc)
        message, retryable = _classify_provider_failure(exc.status_code, kind, text)
        log.log(
            logging.WARNING if retryable else logging.ERROR,
            "AI call on surface %r failed at the provider: status %s, type %s, request %s: %s",
            surface,
            exc.status_code,
            kind,
            exc.request_id,
            text[:_PROVIDER_TEXT_LOG_LIMIT],
        )
        raise AICallFailedError(message, job_retryable=retryable) from exc
    except anthropic.APIConnectionError as exc:
        # The SDK's own message is always "Connection error."; what failed (DNS,
        # TLS, a refused connection) is only on the cause.
        cause = exc.__cause__
        log.warning(
            "AI call on surface %r could not reach the provider: %s: %s",
            surface,
            type(cause).__name__ if cause is not None else type(exc).__name__,
            cause if cause is not None else exc,
        )
        raise AICallFailedError("Could not reach the AI provider") from exc
    except anthropic.APIError as exc:
        log.warning("AI call on surface %r failed inside the SDK: %r", surface, exc)
        raise AICallFailedError("The AI provider's answer could not be read") from exc
    except Exception as exc:
        if not _from_http_stack(exc):
            raise
        log.warning(
            "AI call on surface %r lost its connection mid-answer: %s: %s",
            surface,
            type(exc).__name__,
            exc,
        )
        if _is_timeout(exc):
            raise AITimeoutError(_TIMEOUT_MESSAGE) from exc
        raise AICallFailedError("The connection to the AI dropped mid-answer") from exc


def get_gemini_client():
    """The google-genai client. Imported lazily so the SDK stays an optional
    dependency — an install without it runs fine as long as no surface is
    routed to Gemini."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AIKeyMissingError(
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
    itself does: the Anthropic branch raises `AICallFailedError` when the streamed
    message holds no text (or a subclass when it was cut off or timed out), and
    the Gemini branch raises `ValueError` when `response.parsed` comes back
    empty. A caller that only ever passes a `structured_complete` result through
    this is
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


def _truncated_message(max_tokens: int) -> str:
    return f"The AI's answer was cut off at the output limit ({max_tokens} tokens)"


def _failure(
    cls: type[AICallFailedError],
    message: str,
    final: Any,
    *,
    job_retryable: bool | None = None,
) -> AICallFailedError:
    """A failed-call error carrying whatever the final message says it cost."""
    usage = getattr(final, "usage", None)
    return cls(
        message,
        model=getattr(final, "model", None),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        job_retryable=job_retryable,
    )


async def _final_message(stream: Any) -> Any:
    """The stream's one complete message. The SDK trips a bare `assert` when the
    body ended before any event arrived (a 200 with nothing in it); that is an
    interrupted answer, not a programming error."""
    try:
        final = await stream.get_final_message()
    except AssertionError as exc:
        raise AICallFailedError(_INTERRUPTED_MESSAGE) from exc
    if final is None:  # the same case, for when the SDK's assert is not active
        raise AICallFailedError(_INTERRUPTED_MESSAGE)
    return final


def _raise_for_stop_reason(final: Any, *, max_tokens: int, truncation_ok: bool) -> None:
    """Refuse a message that did not end normally. `truncation_ok` lets a plain
    text answer cut off at the limit through to the caller (see text_complete).

    The stop reason is read here, from the finished message, and the structured
    JSON is parsed only afterwards: the SDK parses at the end of the text block,
    which is before the stop reason arrives, and a cut-off answer would then be
    indistinguishable from a malformed one."""
    reason = final.stop_reason
    if reason is None:  # the stream ended without its closing message_delta
        raise _failure(AICallFailedError, _INTERRUPTED_MESSAGE, final)
    if reason == "max_tokens" and not truncation_ok:
        raise _failure(AIOutputTruncatedError, _truncated_message(max_tokens), final)
    # Neither of these two is retried: the same pages and the same prompt meet
    # the same refusal, and an input that does not fit will not fit a minute on.
    if reason == "refusal":
        raise _failure(AICallFailedError, "The AI declined to answer", final, job_retryable=False)
    if reason == "model_context_window_exceeded":
        raise _failure(
            AICallFailedError,
            _INPUT_TOO_LARGE,
            final,
            job_retryable=False,
        )


def _message_text(final: Any) -> str:
    return "".join(
        getattr(block, "text", "")
        for block in final.content
        if getattr(block, "type", None) == "text"
    )


def _json_schema_format(output_format: type[BaseModel]) -> Any:
    """The request's `output_config`, built exactly as the SDK's own `parse` and
    `stream` build it from a type. We build it ourselves because we must not hand
    the type to `stream()`: given one, the SDK validates the answer as the text
    block closes, before the stop reason is known (see _raise_for_stop_reason).
    A test pins the result to what `messages.parse` sends."""
    schema = anthropic.transform_schema(TypeAdapter(output_format).json_schema())
    return {"format": {"type": "json_schema", "schema": schema}}


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
        # The SDK's transport is streaming, not `messages.parse`. A non-streaming
        # call with a large `max_tokens` is refused client-side, before any
        # request is sent ("Streaming is required for operations that may take
        # longer than 10 minutes", above ~21k tokens), and marking asks for 32k.
        # This is transport only: nothing is passed on incrementally, and we
        # still wait for the one complete message.
        async with (
            _provider_errors_as_ai_errors(surface),
            _call_deadline(surface, get_settings().ai_call_timeout_seconds),
            client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=_anthropic_system(prompt.system, extras, cache_extra_system),
                # `content` is list[dict] by this module's contract (see the
                # module docstring): call sites build Anthropic-shaped
                # blocks, and the Gemini branch below translates the same
                # dicts. The SDK's block union cannot type that without
                # every caller — marking, extraction, syllabus — importing
                # SDK types, which would put a vendor SDK in modules AI-1
                # keeps it out of. file_block() is the constructor that
                # holds the shape (CODE-26).
                messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
                output_config=_json_schema_format(output_format),
            ) as stream,
        ):
            final = await _final_message(stream)
        _raise_for_stop_reason(final, max_tokens=max_tokens, truncation_ok=False)
        text = _message_text(final)
        if not text.strip():
            raise _failure(AICallFailedError, "The AI returned no structured result", final)
        # A ValidationError here is a real model fault (wrong shape), not a
        # transport problem, and propagates unchanged as it did under `parse`.
        parsed = output_format.model_validate_json(text)
        usage = final.usage
        return AiResponse(
            provider=provider,
            model=getattr(final, "model", model),
            prompt_version=prompt.version,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            parsed=parsed,
        )

    from google.genai import types

    client = get_gemini_client()
    async with _call_deadline(surface, get_settings().ai_call_timeout_seconds):
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
    timeout_seconds: float | None = None,
) -> AiResponse[Any]:
    """A plain-text completion for one surface. Never sets `parsed` — there is
    no schema to parametrize `AiResponse` by, so callers get `Any` for it.

    `timeout_seconds` is the total deadline for this call. The default is the
    short text cap, right for a line written inside a web request; a caller that
    writes a long document in a background job passes a longer one."""
    limit = timeout_seconds or get_settings().ai_text_call_timeout_seconds
    provider, model = resolve_surface(surface)
    template = get_prompt(surface)
    extras = extra_system or []

    if provider is AiProvider.anthropic:
        client = get_client()
        # Streaming transport for the same reason as structured_complete: the
        # non-streaming guard refuses large `max_tokens` before sending, and a
        # future caller should not have to know where that line is.
        async with (
            _provider_errors_as_ai_errors(surface),
            _call_deadline(surface, limit),
            client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=_anthropic_system(template.system, extras, False),
                # `prompt` is a plain str, which the SDK's MessageParam does
                # accept; mypy cannot see that through the dict literal's
                # inferred value type. Nothing shape-dependent is masked
                # (CODE-26).
                messages=[{"role": "user", "content": prompt}],  # type: ignore[typeddict-item]
            ) as stream,
        ):
            final = await _final_message(stream)
        text = _message_text(final)
        truncated = final.stop_reason == "max_tokens"
        # A cut-off answer that has some text is let through (below); with none it
        # is refused like every other bad ending.
        _raise_for_stop_reason(final, max_tokens=max_tokens, truncation_ok=bool(text.strip()))
        if not text.strip():
            # An empty string must not reach a caller: narrative.py would store
            # it and hide the previous good paragraph behind a blank one.
            raise _failure(AICallFailedError, "The AI returned an empty answer", final)
        if truncated:
            # Still returned: a plain-text answer cut short is usable (a shorter
            # paragraph), unlike a half-written JSON document. But the caller's
            # limit is too low for what it asked, and that should be findable.
            log.warning(
                "AI answer on surface %r was cut off at the output limit (max_tokens=%s)",
                surface,
                max_tokens,
            )
        usage = final.usage
        return AiResponse(
            provider=provider,
            model=getattr(final, "model", model),
            prompt_version=template.version,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            text=text,
            truncated=truncated,
        )

    from google.genai import types

    client = get_gemini_client()
    async with _call_deadline(surface, limit):
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
