"""Readiness Engine v2 Phase 4: shadow-run dual-enqueue behind the
readiness_v2_shadow_enabled flag, and the read-only /readiness/v2 endpoints."""

from app.config import get_settings
from app.workers.jobs import process_one_job
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_shadow_disabled_by_default_only_enqueues_v1(client, tutor, world):
    assert get_settings().readiness_v2_shadow_enabled is False
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


async def test_shadow_enabled_dual_enqueues_and_creates_snapshot(client, tutor, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", True)

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

    # Both v1's recompute_readiness and v2's compute_readiness_v2 should run.
    assert await process_one_job() is True
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
        f for f in subject["factors"] if f["factor"] == "topic_mastery" and f["topic_id"] == world["topic1"]
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
