"""WS1: per-surface provider routing, the prompt registry, cost estimation
and provider-aware metering (services/ai.py + services/prompts.py)."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import AiFeature, AiUsageEvent, User
from app.services import ai as ai_service
from app.services.ai import (
    SURFACE_FEATURE,
    SURFACES,
    AiProvider,
    AiResponse,
    AIUnavailableError,
    estimate_cost_usd,
    file_block,
    record_usage,
    resolve_surface,
)
from app.services.prompts import PROMPTS, get_prompt


def test_every_surface_has_a_prompt_and_a_feature_bucket():
    assert set(PROMPTS) == set(SURFACES)
    assert set(SURFACE_FEATURE) == set(SURFACES)
    for surface in SURFACES:
        assert get_prompt(surface).version, f"{surface} prompt must carry a version"


def test_get_prompt_rejects_an_unknown_surface():
    with pytest.raises(ValueError):
        get_prompt("not-a-surface")


#: The surfaces that leave their model blank and therefore inherit
#: `anthropic_model` — the one line that moves all four at once.
DEFAULT_MODEL_SURFACES = ("marking", "extraction", "syllabus", "readiness")
#: The surfaces pinned to an explicit model because they diverge on purpose.
PINNED_MODEL_SURFACES = ("reports", "class_brief", "narrative", "marking_rules")


def test_no_surface_routes_to_gemini_any_more():
    """AV-124, task 3.2. The retirement had to happen in one change rather than
    surface by surface, because a half-migrated routing table is worse than the
    Gemini routing it replaces — nothing signals which surfaces have moved.

    So the assertion is exhaustive by construction: every registered surface,
    not a list someone has to remember to extend. The Gemini client and its two
    settings are deliberately kept (unused) in case a surface is ever pointed
    back, which is why this test is the thing standing between "kept" and
    "quietly still in use"."""
    for surface in SURFACES:
        assert resolve_surface(surface)[0] is AiProvider.anthropic, surface


def test_the_blank_model_surfaces_move_with_the_anthropic_default(monkeypatch):
    """Blank is not "unset": it means follow `anthropic_model`. This is what
    makes the next model bump one line rather than seven."""
    monkeypatch.setattr(get_settings(), "anthropic_model", "claude-test")
    for surface in DEFAULT_MODEL_SURFACES:
        assert resolve_surface(surface) == (AiProvider.anthropic, "claude-test"), surface


def test_the_pinned_surfaces_do_not_move_with_it(monkeypatch):
    """Reports, the class brief and the narrative are prose written from data
    the platform already computed, not a judgement about a student's work — so
    they are pinned to Sonnet. Pinned rather than blank precisely so a later
    bump of `anthropic_model` cannot silently drag them back onto Opus."""
    monkeypatch.setattr(get_settings(), "anthropic_model", "claude-test")
    for surface in PINNED_MODEL_SURFACES:
        assert resolve_surface(surface) == (AiProvider.anthropic, "claude-sonnet-5"), surface


def test_every_surface_belongs_to_exactly_one_of_those_two_groups():
    """Exhaustive by subtraction, so a surface added later is covered the day it
    is added rather than quietly escaping both assertions above."""
    assert set(DEFAULT_MODEL_SURFACES) | set(PINNED_MODEL_SURFACES) == set(SURFACES)
    assert not set(DEFAULT_MODEL_SURFACES) & set(PINNED_MODEL_SURFACES)


def test_chat_surface_no_longer_exists():
    """0.3 deleted the student chat surface (AV-57) — `resolve_surface` must
    reject it rather than silently resolving a route nothing serves any more."""
    with pytest.raises(ValueError, match="Unknown AI surface"):
        resolve_surface("chat")


def test_narrative_surface_is_registered_and_routes_like_a_report():
    """The stored narrative (services/narrative.py) is a report-shaped
    paragraph, so it routes to Anthropic by default like class_brief/reports,
    and meters into the same ai_usage_events feature bucket."""
    assert "narrative" in SURFACES
    assert SURFACE_FEATURE["narrative"] is AiFeature.report
    assert resolve_surface("narrative")[0] is AiProvider.anthropic


def test_narrative_surface_model_falls_back_to_the_anthropic_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_narrative_model", "")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    assert resolve_surface("narrative") == (AiProvider.anthropic, "claude-test")


def test_narrative_surface_model_can_be_pinned(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_narrative_model", "claude-narrative-pinned")
    assert resolve_surface("narrative")[1] == "claude-narrative-pinned"


def test_surface_model_falls_back_to_the_providers_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_reports_model", "")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    assert resolve_surface("reports") == (AiProvider.anthropic, "claude-test")

    # The Gemini branch of the fallback, still exercised: no surface routes
    # there by default any more (AV-124), but the code path is deliberately
    # kept, and kept code that nothing tests is how "we can point it back"
    # turns out to be false the day someone tries.
    monkeypatch.setattr(settings, "ai_marking_provider", "gemini")
    monkeypatch.setattr(settings, "ai_marking_model", "")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test")
    assert resolve_surface("marking") == (AiProvider.gemini, "gemini-test")


def test_explicit_surface_model_overrides_the_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_marking_model", "claude-pinned")
    assert resolve_surface("marking")[1] == "claude-pinned"


def test_resolve_surface_rejects_unknown_surface_and_provider(monkeypatch):
    with pytest.raises(ValueError):
        resolve_surface("nope")
    monkeypatch.setattr(get_settings(), "ai_marking_provider", "openai")
    with pytest.raises(ValueError, match="AI_MARKING_PROVIDER"):
        resolve_surface("marking")


def test_gemini_client_without_a_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    with pytest.raises(AIUnavailableError, match="GEMINI_API_KEY"):
        ai_service.get_gemini_client()


def test_file_blocks_translate_to_gemini_parts():
    content = [
        file_block(b"%PDF-1.4 fake", "application/pdf", cache=True),
        file_block(b"\x89PNG fake", "image/png"),
        {"type": "text", "text": "Mark these."},
    ]
    parts = ai_service._gemini_parts(content)
    assert parts[0]["inline_data"]["mime_type"] == "application/pdf"
    # Raw bytes, not the base64 the Anthropic wire format carries.
    assert parts[0]["inline_data"]["data"] == b"%PDF-1.4 fake"
    assert parts[1]["inline_data"]["data"] == b"\x89PNG fake"
    assert parts[2] == {"text": "Mark these."}


def test_gemini_translation_rejects_an_unknown_block_type():
    with pytest.raises(ValueError, match="tool_use"):
        ai_service._gemini_parts([{"type": "tool_use"}])


def test_anthropic_system_caches_only_the_last_extra_block():
    """The tutor Knowledge Base (always last) is stable per tutor and worth
    caching; per-student context before it is not."""
    blocks = ai_service._anthropic_system("base", ["student context", "kb"], True)
    assert [b["text"] for b in blocks] == ["base", "student context", "kb"]
    assert "cache_control" not in blocks[1]
    assert blocks[2]["cache_control"] == {"type": "ephemeral"}


def test_cost_is_none_for_a_model_with_no_configured_price(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_model_pricing", "{}")
    ai_service.model_pricing.cache_clear()
    assert estimate_cost_usd("some-unpriced-model", 1_000_000, 1_000_000) is None


def test_cost_is_computed_from_configured_pricing(monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "ai_model_pricing",
        '{"priced-model": {"input_per_1m": 3.0, "output_per_1m": 15.0}}',
    )
    ai_service.model_pricing.cache_clear()
    # 500k input at $3/M + 200k output at $15/M = 1.5 + 3.0
    assert estimate_cost_usd("priced-model", 500_000, 200_000) == 4.5
    ai_service.model_pricing.cache_clear()


def test_malformed_pricing_config_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_model_pricing", "not json{")
    ai_service.model_pricing.cache_clear()
    assert estimate_cost_usd("anything", 10, 10) is None
    ai_service.model_pricing.cache_clear()


async def test_record_usage_writes_provider_prompt_version_and_cost(client, tutor, monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "ai_model_pricing",
        '{"gemini-test": {"input_per_1m": 1.0, "output_per_1m": 2.0}}',
    )
    ai_service.model_pricing.cache_clear()
    response = AiResponse(
        provider=AiProvider.gemini,
        model="gemini-test",
        prompt_version="v1",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    async with async_session() as session:
        tutor_user = await session.get(User, tutor["user"]["id"])
        await record_usage(
            session,
            response,
            organization_id=tutor_user.organization_id,
            tutor_id=tutor_user.id,
            student_id=None,
            feature=AiFeature.marking,
        )
        await session.commit()

    async with async_session() as session:
        event = await session.scalar(select(AiUsageEvent))
        assert event.provider == "gemini"
        assert event.model == "gemini-test"
        assert event.prompt_version == "v1"
        assert event.cost_usd == 2.0  # 1.0 + 1.0
    ai_service.model_pricing.cache_clear()


async def test_record_usage_skips_anything_that_is_not_an_ai_response(client, tutor):
    """A test double or a raw SDK object must not break the calling feature."""

    class NotAnAiResponse:
        model = "x"

    async with async_session() as session:
        tutor_user = await session.get(User, tutor["user"]["id"])
        await record_usage(
            session,
            NotAnAiResponse(),
            organization_id=tutor_user.organization_id,
            tutor_id=tutor_user.id,
            student_id=None,
            feature=AiFeature.marking,
        )
        await session.commit()
    async with async_session() as session:
        assert (await session.scalar(select(AiUsageEvent))) is None
