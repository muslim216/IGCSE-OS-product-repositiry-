"""Metering gaps from the launch audit: cache tokens (C-3), calls with no
tutor (C-14), and a malformed price table (CFG-5). No provider is called."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import Settings, get_settings, parse_model_pricing
from app.db import async_session
from app.models import AiFeature, AiUsageEvent, User
from app.services import ai as ai_service
from app.services.ai import AiProvider, AiResponse, estimate_cost_usd, record_usage

PRICES = (
    '{"cached": {"input_per_1m": 3, "output_per_1m": 15,'
    ' "cache_write_per_1m": 3.75, "cache_read_per_1m": 0.3},'
    ' "plain": {"input_per_1m": 3, "output_per_1m": 15}}'
)


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_model_pricing", PRICES)
    ai_service.model_pricing.cache_clear()
    yield
    ai_service.model_pricing.cache_clear()


def test_cache_tokens_are_priced_at_their_own_rates(prices):
    # 1M input $3 + 1M output $15 + 1M write $3.75 + 1M read $0.30
    assert estimate_cost_usd("cached", 1_000_000, 1_000_000, 1_000_000, 1_000_000) == 22.05


def test_cache_tokens_without_a_rate_are_unpriced_not_free(prices):
    assert estimate_cost_usd("plain", 1000, 1000, cache_read_tokens=500) is None
    assert estimate_cost_usd("plain", 1000, 1000, cache_write_tokens=500) is None
    # No cache tokens used: the missing cache rate is irrelevant.
    assert estimate_cost_usd("plain", 1_000_000, 0) == 3.0


def test_anthropic_cache_counters_are_separate_from_input():
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=3000,
    )
    assert ai_service._anthropic_usage(usage) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_write_tokens": 200,
        "cache_read_tokens": 3000,
    }


def test_gemini_cached_tokens_come_out_of_input_so_nothing_is_double_counted():
    meta = SimpleNamespace(
        prompt_token_count=1000, candidates_token_count=40, cached_content_token_count=600
    )
    got = ai_service._gemini_usage(SimpleNamespace(usage_metadata=meta))
    assert got == {"input_tokens": 400, "output_tokens": 40, "cache_read_tokens": 600}


async def test_record_usage_stores_cache_tokens_and_cost(client, tutor, prices):
    response = AiResponse(
        provider=AiProvider.anthropic,
        model="cached",
        prompt_version="v1",
        input_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await record_usage(
            session,
            response,
            organization_id=user.organization_id,
            tutor_id=user.id,
            student_id=None,
            feature=AiFeature.marking,
        )
        await session.commit()
    async with async_session() as session:
        event = await session.scalar(select(AiUsageEvent))
        assert (event.cache_write_tokens, event.cache_read_tokens) == (1_000_000, 1_000_000)
        assert event.cost_usd == 7.05


async def test_a_call_with_no_tutor_is_recorded_as_system_usage(client, tutor, prices):
    response = AiResponse(
        provider=AiProvider.anthropic, model="plain", prompt_version="v1", input_tokens=10
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await record_usage(
            session,
            response,
            organization_id=user.organization_id,
            tutor_id=None,
            student_id=None,
            feature=AiFeature.report,
        )
        await session.commit()
    async with async_session() as session:
        event = await session.scalar(select(AiUsageEvent))
        assert event.tutor_id is None
        assert event.organization_id == user.organization_id
    # The organization's reports still count it.
    summary = (await client.get("/api/v1/ai-usage/summary", headers=tutor["headers"])).json()
    assert summary["total_input_tokens"] == 10


@pytest.mark.parametrize(
    "raw",
    [
        "not json{",
        "[]",
        '{"m": 3}',
        '{"m": {"input_per_1m": -1}}',
        '{"m": {"input_per_1m": "3"}}',
        '{"m": {"input_per_1m": true}}',
        '{"m": {"inputs_per_1m": 3}}',
    ],
)
def test_a_malformed_price_table_is_refused_at_settings_load(raw):
    with pytest.raises(ValueError, match="AI_MODEL_PRICING"):
        Settings(_env_file=None, ai_model_pricing=raw)  # type: ignore[call-arg]


@pytest.mark.parametrize("raw", ["", "  ", "{}", PRICES])
def test_an_empty_or_valid_price_table_loads(raw):
    Settings(_env_file=None, ai_model_pricing=raw)  # type: ignore[call-arg]


def test_empty_table_leaves_every_model_unpriced():
    assert parse_model_pricing("") == {}
