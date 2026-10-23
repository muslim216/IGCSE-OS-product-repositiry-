"""Metering gaps from the launch audit: cache tokens (C-3), calls with no
tutor (C-14), and a malformed price table (CFG-5). No provider is called."""

import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app import config as app_config
from app.config import Settings, get_settings, parse_model_pricing
from app.db import async_session
from app.models import AiFeature, AiUsageEvent, User
from app.services import ai as ai_service
from app.services.ai import (
    AICallFailedError,
    AiProvider,
    AiResponse,
    estimate_cost_usd,
    record_usage,
    structured_complete,
    text_complete,
)
from tests.ai_stream_fakes import CannedServer, http, sse_message

PRICES = (
    '{"cached": {"input_per_1m": 3, "output_per_1m": 15,'
    ' "cache_write_per_1m": 3.75, "cache_read_per_1m": 0.3},'
    ' "plain": {"input_per_1m": 3, "output_per_1m": 15}}'
)


async def _user(tutor):
    async with async_session() as session:
        return await session.get(User, tutor["user"]["id"])


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


def test_gemini_thinking_tokens_are_billed_as_output():
    meta = SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=40,
        thoughts_token_count=25,
        cached_content_token_count=0,
    )
    got = ai_service._gemini_usage(SimpleNamespace(usage_metadata=meta))
    assert got["output_tokens"] == 65


async def test_record_usage_stores_cache_tokens_and_cost(client, tutor, prices):
    response = AiResponse(
        provider=AiProvider.anthropic,
        model="cached",
        prompt_version="v1",
        input_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    user = await _user(tutor)
    async with async_session() as session:
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
    user = await _user(tutor)
    async with async_session() as session:
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


MALFORMED = [
    "not json{",
    "[]",
    '{"m": 3}',
    '{"m": {"input_per_1m": -1, "output_per_1m": 1}}',
    '{"m": {"input_per_1m": "3", "output_per_1m": 1}}',
    '{"m": {"input_per_1m": true, "output_per_1m": 1}}',
    '{"m": {"input_per_1m": 3, "output_per_1m": 1, "inputs_per_1m": 3}}',
    '{"m": {"input_per_1m": 3}}',  # a missing side would price at $0
]


@pytest.mark.parametrize("raw", MALFORMED)
def test_the_strict_parser_detects_every_malformed_shape(raw):
    with pytest.raises(ValueError, match="AI_MODEL_PRICING"):
        parse_model_pricing(raw)


@pytest.mark.parametrize("raw", MALFORMED)
async def test_a_malformed_price_table_boots_logs_error_degrades_health_and_prices_nothing(
    raw, client, monkeypatch, caplog
):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "configured")
    with caplog.at_level(logging.ERROR, logger="app.config"):
        settings = Settings(_env_file=None, ai_model_pricing=raw)  # type: ignore[call-arg]
    assert settings.ai_model_pricing == "{}"
    assert any(
        "AI_MODEL_PRICING" in r.message and r.levelno == logging.ERROR for r in caplog.records
    )
    assert raw not in caplog.text

    body = (await client.get("/api/v1/health/ready")).json()
    assert body["ai_pricing"]["ok"] is False
    assert "AI_MODEL_PRICING" in body["ai_pricing"]["problem"]
    assert body["status"] == "degraded"

    # Mid-request, a bad value patched in must not raise either; nothing is priced.
    monkeypatch.setattr(get_settings(), "ai_model_pricing", raw)
    ai_service.model_pricing.cache_clear()
    assert estimate_cost_usd("m", 1000, 1000) is None
    ai_service.model_pricing.cache_clear()
    Settings(_env_file=None, ai_model_pricing="{}")  # type: ignore[call-arg]
    assert app_config.pricing_problem is None


@pytest.mark.parametrize("raw", ["", "  ", "{}", PRICES])
def test_an_empty_or_valid_price_table_loads_clean(raw):
    Settings(_env_file=None, ai_model_pricing=raw)  # type: ignore[call-arg]
    assert app_config.pricing_problem is None


def test_a_partial_entry_in_code_is_unpriced_not_free(monkeypatch):
    monkeypatch.setattr(ai_service, "MODEL_PRICING", {"half": {"input_per_1m": 3.0}})
    monkeypatch.setattr(get_settings(), "ai_model_pricing", "{}")
    ai_service.model_pricing.cache_clear()
    assert estimate_cost_usd("half", 1000, 1000) is None
    ai_service.model_pricing.cache_clear()


class Verdict(BaseModel):
    mark: int


@pytest.fixture
def serve(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-canned", raising=False)

    def _serve(body: bytes) -> None:
        monkeypatch.setattr(ai_service, "_transport", http.MockTransport(CannedServer(body)))

    return _serve


async def _events():
    async with async_session() as session:
        return (await session.scalars(select(AiUsageEvent))).all()


async def _structured(org: int):
    return await structured_complete(
        organization_id=org,
        surface="marking",
        content=[{"type": "text", "text": "x"}],
        output_format=Verdict,
        max_tokens=50,
    )


async def test_a_truncated_structured_answer_still_records_its_tokens(client, tutor, serve):
    org = (await _user(tutor)).organization_id
    serve(sse_message('{"mark"', stop_reason="max_tokens"))
    with pytest.raises(AICallFailedError):
        await _structured(org)
    (event,) = await _events()
    assert (event.input_tokens, event.output_tokens) == (123, 45)
    assert event.tutor_id is None
    assert event.feature == AiFeature.marking
    assert event.organization_id == org


async def test_a_wrong_shape_structured_answer_still_records_its_tokens(client, tutor, serve):
    org = (await _user(tutor)).organization_id
    serve(sse_message('{"mark": "nope"}'))
    with pytest.raises(ValidationError):
        await _structured(org)
    assert len(await _events()) == 1


async def test_an_empty_text_answer_still_records_its_tokens(client, tutor, serve):
    org = (await _user(tutor)).organization_id
    serve(sse_message(""))
    with pytest.raises(AICallFailedError):
        await text_complete(organization_id=org, surface="narrative", prompt="p", max_tokens=50)
    (event,) = await _events()
    assert event.feature == AiFeature.report


async def test_a_successful_call_is_not_recorded_by_the_helper(client, tutor, serve):
    # The caller records successes with its own tutor/student; no double entry.
    org = (await _user(tutor)).organization_id
    serve(sse_message('{"mark": 3}'))
    await _structured(org)
    assert await _events() == []


async def test_usage_api_sums_cache_tokens(client, tutor, prices):
    org = (await _user(tutor)).organization_id
    async with async_session() as session:
        for _ in range(2):
            await record_usage(
                session,
                AiResponse(
                    provider=AiProvider.anthropic,
                    model="cached",
                    prompt_version="v1",
                    cache_write_tokens=10,
                    cache_read_tokens=100,
                ),
                organization_id=org,
                tutor_id=None,
                student_id=None,
                feature=AiFeature.report,
            )
        await session.commit()
    summary = (await client.get("/api/v1/ai-usage/summary", headers=tutor["headers"])).json()
    assert (summary["total_cache_write_tokens"], summary["total_cache_read_tokens"]) == (20, 200)
    analytics = (await client.get("/api/v1/ai-usage/analytics", headers=tutor["headers"])).json()
    assert analytics["buckets"][0]["cache_read_tokens"] == 200
