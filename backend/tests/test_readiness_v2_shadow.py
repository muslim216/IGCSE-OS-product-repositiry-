"""Readiness Engine v2 Phase 4: shadow-run dual-enqueue behind the
readiness_v2_shadow_enabled flag, and the read-only /readiness/v2 endpoints."""

from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Job
from app.workers.jobs import process_one_job
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_v2_switched_off_enqueues_only_v1(client, tutor, world, monkeypatch):
    """READINESS_V2_SHADOW_ENABLED=false is the kill switch — v2 stops being
    computed and the app runs on v1 alone."""
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", False)
    resp = await client.post(
        "/api/v1/observations",
        json={
            "student_id": world["student_id"],
            "topic_id": world["topic1"],
            "comment": "Doing well",
            "rating": 80,
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201
    # Exactly one job (v1's recompute_readiness) — nothing else queued.
    assert await process_one_job() is True
    assert await process_one_job() is False


async def test_v2_enqueues_alongside_v1_and_creates_a_snapshot(client, tutor, world, monkeypatch):
    assert get_settings().readiness_v2_shadow_enabled is True, "v2 is on by default"

    resp = await client.post(
        "/api/v1/observations",
        json={
            "student_id": world["student_id"],
            "topic_id": world["topic1"],
            "comment": "Doing well",
            "rating": 80,
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201

    # v1's recompute_readiness runs immediately; v2's compute_readiness_v2 is
    # queued but debounced (see enqueue_readiness_v2_debounced), so it is not
    # yet due and the worker finds nothing else to claim.
    assert await process_one_job() is True
    assert await process_one_job() is False

    async with async_session() as session:
        v2_job = await session.scalar(select(Job).where(Job.type == "compute_readiness_v2"))
        assert v2_job is not None
        assert v2_job.run_after is not None, "the v2 job must be scheduled, not immediate"
        v2_job.run_after = None  # fast-forward past the coalescing window
        await session.commit()

    assert await process_one_job() is True
    assert await process_one_job() is False

    v2 = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert v2.status_code == 200
    body = v2.json()
    assert len(body["subjects"]) == 1
    subject = body["subjects"][0]
    assert subject["subject_id"] == world["subject_id"]
    # No ANTHROPIC_API_KEY in tests -> AI synthesis fails gracefully, but the
    # deterministic factor breakdown must still be there.
    assert subject["status"] == "failed"
    assert len(subject["factors"]) > 0
    topic1_factor = next(
        f
        for f in subject["factors"]
        if f["factor"] == "topic_mastery" and f["topic_id"] == world["topic1"]
    )
    assert topic1_factor["score"] is None  # observation feeds Evidence, not QuestionMark


async def test_v2_endpoint_idempotent_before_any_snapshot(client, tutor, world):
    """No snapshot exists yet -> an empty subjects list, and the GET itself
    must not trigger any computation (no jobs get queued)."""
    resp = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["subjects"] == []
    assert await process_one_job() is False


async def test_v2_endpoint_access_control(client, tutor, world):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-v2@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=other_headers
    )
    assert resp.status_code == 404
