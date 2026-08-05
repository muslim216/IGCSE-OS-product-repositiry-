"""WS1: AI spend analytics — GET /ai-usage/analytics."""

from datetime import datetime, timezone

from app.db import async_session
from app.models import AiFeature, AiUsageEvent, User
from tests.test_homework import group, student, subject  # noqa: F401 - shared fixtures


async def _seed_events(tutor_id: int) -> None:
    async with async_session() as session:
        tutor = await session.get(User, tutor_id)
        org = tutor.organization_id
        session.add_all(
            [
                AiUsageEvent(
                    organization_id=org,
                    tutor_id=tutor_id,
                    feature=AiFeature.marking,
                    provider="gemini",
                    model="gemini-test",
                    prompt_version="v1",
                    input_tokens=1000,
                    output_tokens=500,
                    cost_usd=0.25,
                    created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
                ),
                AiUsageEvent(
                    organization_id=org,
                    tutor_id=tutor_id,
                    feature=AiFeature.marking,
                    provider="gemini",
                    model="gemini-test",
                    prompt_version="v1",
                    input_tokens=2000,
                    output_tokens=1000,
                    cost_usd=0.75,
                    created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                ),
                # No configured price for this model -> unknown cost, not zero.
                AiUsageEvent(
                    organization_id=org,
                    tutor_id=tutor_id,
                    feature=AiFeature.readiness,
                    provider="anthropic",
                    model="unpriced-model",
                    prompt_version="v1",
                    input_tokens=100,
                    output_tokens=50,
                    cost_usd=None,
                    created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                ),
            ]
        )
        await session.commit()


async def test_analytics_groups_by_feature(client, tutor):
    await _seed_events(tutor["user"]["id"])
    resp = await client.get("/api/v1/ai-usage/analytics", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["group_by"] == "feature"
    by_bucket = {b["bucket"]: b for b in body["buckets"]}
    assert by_bucket["marking"]["call_count"] == 2
    assert by_bucket["marking"]["input_tokens"] == 3000
    assert by_bucket["marking"]["cost_usd"] == 1.0
    assert by_bucket["marking"]["unpriced_call_count"] == 0
    assert body["total_cost_usd"] == 1.0


async def test_unpriced_calls_are_reported_not_counted_as_free(client, tutor):
    await _seed_events(tutor["user"]["id"])
    body = (
        await client.get("/api/v1/ai-usage/analytics", headers=tutor["headers"])
    ).json()
    readiness = next(b for b in body["buckets"] if b["bucket"] == "readiness")
    assert readiness["cost_usd"] == 0.0
    assert readiness["unpriced_call_count"] == 1
    assert body["unpriced_call_count"] == 1, (
        "the total must flag that some spend is unknown rather than implying $0"
    )


async def test_analytics_groups_by_month(client, tutor):
    await _seed_events(tutor["user"]["id"])
    body = (
        await client.get(
            "/api/v1/ai-usage/analytics?group_by=month", headers=tutor["headers"]
        )
    ).json()
    by_bucket = {b["bucket"]: b for b in body["buckets"]}
    assert set(by_bucket) == {"2026-06", "2026-07"}
    assert by_bucket["2026-06"]["cost_usd"] == 0.25
    assert by_bucket["2026-07"]["call_count"] == 2


async def test_analytics_groups_by_provider(client, tutor):
    await _seed_events(tutor["user"]["id"])
    body = (
        await client.get(
            "/api/v1/ai-usage/analytics?group_by=provider", headers=tutor["headers"]
        )
    ).json()
    by_bucket = {b["bucket"]: b for b in body["buckets"]}
    assert by_bucket["gemini"]["call_count"] == 2
    assert by_bucket["anthropic"]["call_count"] == 1


async def test_analytics_is_scoped_to_the_callers_organization(client, tutor):
    await _seed_events(tutor["user"]["id"])
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-usage@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    body = (await client.get("/api/v1/ai-usage/analytics", headers=headers)).json()
    assert body["buckets"] == []
    assert body["total_cost_usd"] == 0.0


async def test_analytics_requires_a_tutor_account(client, tutor, student):  # noqa: F811
    """Org-wide AI spend is tutor-facing; a student must never see it."""
    resp = await client.get("/api/v1/ai-usage/analytics", headers=student["headers"])
    assert resp.status_code == 403


async def test_analytics_rejects_an_unknown_group_by(client, tutor):
    resp = await client.get(
        "/api/v1/ai-usage/analytics?group_by=nonsense", headers=tutor["headers"]
    )
    assert resp.status_code == 422
