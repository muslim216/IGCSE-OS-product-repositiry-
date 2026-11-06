"""The AI work the app cannot move on without (T-028, owner 5 Nov 2026).

Reading a syllabus and weighting a teaching plan's chapters are *essential*: a
tutor cannot set anything else up until they finish. They get the model's full
answer length and a long deadline, and they draw on allowances of their own so
other AI use can never block them. Everything else (homework, marking, reports)
keeps its limits. No test here reaches a real provider (`QA-8`).
"""

import logging

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db import async_session
from app.models import User
from app.services import ai as ai_service
from app.services.ai import (
    ESSENTIAL_SURFACES,
    AIDailyLimitError,
    AIKeyMissingError,
    AiProvider,
    AiResponse,
    AITimeoutError,
    output_ceiling,
    structured_complete,
)
from app.services.rate_limit import (
    ALL_LIMITERS,
    RateLimiter,
    ai_daily_limiter,
    essential_platform_daily_limiter,
    plan_daily_limiter,
    syllabus_daily_limiter,
)
from app.services.syllabus_extraction import SyllabusExtractionResult
from app.workers import jobs
from app.workers.handlers import register_all
from app.workers.jobs import JOB_TIMEOUT_MARGIN_SECONDS, is_permanent, job_timeout_seconds
from tests.ai_stream_fakes import Trickle, http

API = "/api/v1"
PDF_BYTES = b"%PDF-1.4 fake test syllabus pdf"


def _allow(monkeypatch, limiter: RateLimiter, n: int) -> None:
    """`n` more uses from here: what a fixture already spent is forgotten."""
    limiter.local._hits.clear()
    monkeypatch.setattr(limiter, "limit", n)
    monkeypatch.setattr(limiter.local, "limit", n)


async def _org(user: dict) -> int:
    async with async_session() as session:
        return (await session.get(User, user["user"]["id"])).organization_id


def _syllabus_result() -> SyllabusExtractionResult:
    return SyllabusExtractionResult(
        exam_board="Edexcel IGCSE",
        code="4CH1",
        name="Chemistry",
        grade_scale="9-1",
        level="igcse",
        chapters=[
            {
                "code": "1",
                "title": "Principles",
                "topics": [{"code": "1.1", "title": "States", "weight": 1.0, "children": []}],
            }
        ],
    )


def _capturing(parsed, seen: dict):
    async def _call(**kwargs) -> AiResponse:
        seen.update(kwargs)
        return AiResponse(
            provider=AiProvider.anthropic, model="m", prompt_version="v", parsed=parsed
        )

    return _call


async def _upload_and_read(client, tutor) -> int:
    resp = await client.post(
        f"{API}/syllabus-uploads",
        data={"title": "Chemistry"},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await jobs.process_one_job() is True
    return resp.json()["id"]


# --- 1. Answer length -----------------------------------------------------


def test_the_essential_surfaces_are_the_syllabus_and_the_plan():
    assert frozenset({"syllabus", "plan_weighting"}) == ESSENTIAL_SURFACES
    assert ESSENTIAL_SURFACES <= set(ai_service.SURFACES)


def test_the_ceiling_follows_the_provider_the_surface_is_routed_to(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_syllabus_provider", "anthropic", raising=False)
    assert output_ceiling("syllabus") == 128_000
    # Gemini refuses a request above this, so it is never sent above it.
    monkeypatch.setattr(get_settings(), "ai_syllabus_provider", "gemini", raising=False)
    assert output_ceiling("syllabus") == 65_536


async def test_a_syllabus_read_asks_for_the_routed_ceiling_and_the_long_deadline(
    client, tutor, monkeypatch
):
    seen: dict = {}
    monkeypatch.setattr(
        "app.services.syllabus_extraction.structured_complete",
        _capturing(_syllabus_result(), seen),
    )
    await _upload_and_read(client, tutor)

    assert seen["surface"] == "syllabus"
    assert seen["max_tokens"] == 128_000
    assert seen["timeout_seconds"] == get_settings().ai_essential_call_timeout_seconds


async def test_a_syllabus_routed_to_gemini_asks_for_gemini_s_ceiling(client, tutor, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_syllabus_provider", "gemini", raising=False)
    seen: dict = {}
    monkeypatch.setattr(
        "app.services.syllabus_extraction.structured_complete",
        _capturing(_syllabus_result(), seen),
    )
    await _upload_and_read(client, tutor)

    assert seen["max_tokens"] == 65_536


async def test_a_homework_extraction_still_asks_for_16000(
    client, tutor, group, classified, monkeypatch
):
    """Not essential: its limit and its deadline stay where they were."""
    seen: dict = {}

    async def _stop(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr("app.services.extraction.structured_complete", _stop)
    resp = await client.post(
        f"{API}/assignments",
        json={
            "group_id": group["id"],
            "classified_id": classified["id"],
            "title": "HW1",
            "question_range": "Q1-2",
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await jobs.process_one_job() is True

    assert seen["surface"] == "extraction"
    assert seen["max_tokens"] == 16000
    assert seen.get("timeout_seconds") is None


# --- 2. Time ---------------------------------------------------------------


@pytest.fixture
def anthropic_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test", raising=False)


@pytest.fixture
def trickling_provider(monkeypatch, anthropic_key):
    """A provider that keeps the stream open and never finishes the answer."""
    transport = http.MockTransport(
        lambda request: http.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Trickle()
        )
    )
    monkeypatch.setattr(ai_service, "_transport", transport)


async def _structured(surface: str, **kwargs):
    return await structured_complete(
        organization_id=1,
        surface=surface,
        content=[{"type": "text", "text": "x"}],
        output_format=SyllabusExtractionResult,
        max_tokens=500,
        **kwargs,
    )


async def test_a_structured_call_honours_its_own_timeout(monkeypatch, trickling_provider):
    # The normal limit is long; only the one the caller passed may stop this.
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 3600.0, raising=False)
    with pytest.raises(AITimeoutError, match="did not answer in time"):
        await _structured("readiness", timeout_seconds=0.1)


async def test_without_a_timeout_a_structured_call_keeps_the_normal_deadline(
    monkeypatch, trickling_provider
):
    seen: list[float] = []
    real_deadline = ai_service._call_deadline

    def spy(surface, limit):
        seen.append(limit)
        return real_deadline(surface, 0.1)  # still end the test quickly

    monkeypatch.setattr(ai_service, "_call_deadline", spy)
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 840.0, raising=False)
    with pytest.raises(AITimeoutError):
        await _structured("readiness")
    with pytest.raises(AITimeoutError):
        await _structured("syllabus", timeout_seconds=2700.0)
    assert seen == [840.0, 2700.0]


async def test_an_essential_call_that_runs_out_its_deadline_is_not_retried(
    monkeypatch, trickling_provider
):
    """One stuck read costs one deadline and one call, not two of each."""
    with pytest.raises(AITimeoutError) as caught:
        await _structured("syllabus", timeout_seconds=0.1)
    assert caught.value.job_retryable is False
    assert is_permanent(caught.value)


async def test_any_other_call_that_runs_out_its_deadline_keeps_its_retry(
    monkeypatch, trickling_provider
):
    with pytest.raises(AITimeoutError) as caught:
        await _structured("readiness", timeout_seconds=0.1)
    assert caught.value.job_retryable is True
    assert not is_permanent(caught.value)


async def test_an_essential_call_keeps_its_retry_for_any_other_failure(
    monkeypatch, anthropic_key
):
    """The SDK's own silence timeout is a dropped connection, not our deadline."""

    def silent(request):
        raise http.ReadTimeout("no bytes", request=request)

    monkeypatch.setattr(ai_service, "_transport", http.MockTransport(silent))
    monkeypatch.setattr(get_settings(), "ai_max_retries", 0, raising=False)
    with pytest.raises(AITimeoutError) as caught:
        await _structured("syllabus", timeout_seconds=60.0)
    assert caught.value.job_retryable is True


async def test_a_gemini_essential_call_past_its_deadline_is_not_retried(monkeypatch):
    import asyncio

    class _Models:
        async def generate_content(self, **kwargs):
            await asyncio.sleep(3600)

    class _Aio:
        models = _Models()

    class _Gemini:
        aio = _Aio()

    monkeypatch.setattr(get_settings(), "ai_syllabus_provider", "gemini", raising=False)
    monkeypatch.setattr(ai_service, "get_gemini_client", lambda: _Gemini())
    with pytest.raises(AITimeoutError) as caught:
        await _structured("syllabus", timeout_seconds=0.05)
    assert caught.value.job_retryable is False


# --- 3. Job limits and settings ---------------------------------------------


@pytest.mark.parametrize("job_type", ["extract_syllabus", "draft_plan"])
def test_an_essential_job_s_limit_ends_after_its_ai_deadline(monkeypatch, job_type):
    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_timeouts", {})
    monkeypatch.setattr(jobs, "_background", set())
    register_all()

    essential = get_settings().ai_essential_call_timeout_seconds
    assert job_timeout_seconds(job_type) == essential + JOB_TIMEOUT_MARGIN_SECONDS
    assert job_timeout_seconds(job_type) > essential
    # Run where marking never waits behind it (`CAP-2`).
    assert job_type in jobs._background
    assert "mark_submission" not in jobs._background


def test_the_essential_deadline_defaults_to_45_minutes():
    assert Settings().ai_essential_call_timeout_seconds == 2700


@pytest.mark.parametrize("bad", [0, -1])
def test_an_essential_deadline_of_zero_or_less_is_refused(bad):
    with pytest.raises(ValidationError, match="AI_ESSENTIAL_CALL_TIMEOUT_SECONDS"):
        Settings(ai_essential_call_timeout_seconds=bad)


def test_an_essential_deadline_below_the_normal_one_is_refused():
    with pytest.raises(ValidationError, match="AI_ESSENTIAL_CALL_TIMEOUT_SECONDS"):
        Settings(ai_call_timeout_seconds=840, ai_essential_call_timeout_seconds=839)
    # Equal is allowed: it is never shorter than an ordinary call.
    assert Settings(ai_call_timeout_seconds=840, ai_essential_call_timeout_seconds=840)


def test_the_allowance_defaults():
    settings = Settings()
    assert settings.daily_syllabus_ai_calls_per_workspace == 10
    assert settings.daily_plan_ai_calls_per_workspace == 30
    assert settings.daily_essential_ai_calls_platform == 300


# --- 4. Allowances ----------------------------------------------------------


async def _call(organization_id: int, surface: str) -> None:
    await structured_complete(
        organization_id=organization_id,
        surface=surface,
        content=[{"type": "text", "text": "x"}],
        output_format=SyllabusExtractionResult,
        max_tokens=10,
    )


@pytest.mark.usefixtures("no_ai_key")
@pytest.mark.parametrize("surface", sorted(ESSENTIAL_SURFACES))
async def test_a_spent_general_allowance_does_not_block_an_essential_call(
    monkeypatch, tutor, surface
):
    _allow(monkeypatch, ai_daily_limiter, 0)
    org = await _org(tutor)
    # Past the allowance check and on to the missing key.
    with pytest.raises(AIKeyMissingError):
        await _call(org, surface)
    # And it did not spend the general allowance either.
    assert ai_daily_limiter.local._hits == {}


@pytest.mark.usefixtures("no_ai_key")
@pytest.mark.parametrize(
    ("surface", "limiter"),
    [("syllabus", syllabus_daily_limiter), ("plan_weighting", plan_daily_limiter)],
)
async def test_a_spent_essential_allowance_blocks_that_surface_for_that_workspace_only(
    monkeypatch, client, tutor, surface, limiter
):
    _allow(monkeypatch, limiter, 1)
    org = await _org(tutor)
    other = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "B", "email": "b@example.com", "password": "password123"},
    )
    other_org = await _org(other.json())

    with pytest.raises(AIKeyMissingError):
        await _call(org, surface)
    with pytest.raises(AIDailyLimitError, match="today's limit"):
        await _call(org, surface)
    with pytest.raises(AIKeyMissingError):
        await _call(other_org, surface)


@pytest.mark.usefixtures("no_ai_key")
async def test_the_two_essential_surfaces_do_not_share_an_allowance(monkeypatch, tutor):
    _allow(monkeypatch, syllabus_daily_limiter, 0)
    org = await _org(tutor)
    with pytest.raises(AIDailyLimitError):
        await _call(org, "syllabus")
    with pytest.raises(AIKeyMissingError):
        await _call(org, "plan_weighting")


@pytest.mark.usefixtures("no_ai_key")
async def test_the_platform_cap_blocks_every_workspace_and_says_so_in_an_error_log(
    monkeypatch, client, tutor, caplog
):
    _allow(monkeypatch, essential_platform_daily_limiter, 1)
    org = await _org(tutor)
    other = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "B", "email": "b@example.com", "password": "password123"},
    )
    other_org = await _org(other.json())

    with pytest.raises(AIKeyMissingError):
        await _call(org, "syllabus")
    with caplog.at_level(logging.ERROR, logger="app.services.ai"):
        # A different workspace, and a different essential surface: one shared cap.
        with pytest.raises(AIDailyLimitError):
            await _call(other_org, "plan_weighting")
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "reaching the platform cap must log an ERROR"
    message = errors[-1].getMessage()
    assert "platform" in message.lower()
    assert "not this workspace's own" in message


@pytest.mark.usefixtures("no_ai_key")
async def test_a_workspace_refused_its_own_allowance_does_not_spend_the_platform_s(
    monkeypatch, tutor
):
    _allow(monkeypatch, syllabus_daily_limiter, 0)
    _allow(monkeypatch, essential_platform_daily_limiter, 5)
    org = await _org(tutor)
    with pytest.raises(AIDailyLimitError):
        await _call(org, "syllabus")
    assert essential_platform_daily_limiter.local._hits == {}


async def test_the_platform_cap_is_keyed_globally_not_per_workspace():
    key = essential_platform_daily_limiter.key("platform")
    assert ":global:" in key


def test_the_new_allowances_are_reported_with_the_other_limiters():
    purposes = {limiter.purpose for limiter in ALL_LIMITERS}
    assert {
        syllabus_daily_limiter.purpose,
        plan_daily_limiter.purpose,
        essential_platform_daily_limiter.purpose,
    } <= purposes
    assert syllabus_daily_limiter.limit == get_settings().daily_syllabus_ai_calls_per_workspace
    assert plan_daily_limiter.limit == get_settings().daily_plan_ai_calls_per_workspace
    assert (
        essential_platform_daily_limiter.limit == get_settings().daily_essential_ai_calls_platform
    )


# --- The plan's answer length ----------------------------------------------


async def test_plan_weighting_asks_for_4000_plus_300_per_chapter(monkeypatch):
    from app.services import plan_drafting

    seen: dict = {}

    async def _stop(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(plan_drafting, "structured_complete", _stop)
    monkeypatch.setattr(plan_drafting, "_guidance_block", _no_guidance)
    with pytest.raises(RuntimeError, match="stop here"):
        await plan_drafting.weigh_chapters(
            group=_Group(), subject=object(), chapters=[_chapter(i) for i in range(7)]
        )
    assert seen["surface"] == "plan_weighting"
    assert seen["max_tokens"] == 4000 + 300 * 7
    assert seen["timeout_seconds"] == get_settings().ai_essential_call_timeout_seconds


async def test_plan_weighting_never_asks_above_the_ceiling(monkeypatch):
    from app.services import plan_drafting

    seen: dict = {}

    async def _stop(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(plan_drafting, "structured_complete", _stop)
    monkeypatch.setattr(plan_drafting, "_guidance_block", _no_guidance)
    monkeypatch.setattr(get_settings(), "ai_plan_weighting_provider", "gemini", raising=False)
    # 4,000 + 300 x 300 = 94,000, above Gemini's 65,536.
    with pytest.raises(RuntimeError, match="stop here"):
        await plan_drafting.weigh_chapters(
            group=_Group(), subject=object(), chapters=[_chapter(i) for i in range(300)]
        )
    assert seen["max_tokens"] == 65_536


class _Group:
    id = 1
    organization_id = 1
    tutor_id = 1


def _chapter(i: int):
    from app.models import Chapter

    return Chapter(id=i + 1, subject_id=1, code=f"C{i}", title=f"Chapter {i}", position=i)


async def _no_guidance(subject):
    return None, None
