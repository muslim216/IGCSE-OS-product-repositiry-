"""Direction of travel — the arrow beside a readiness score (UX-31).

The pure rule is tested directly; the wiring is tested through the API so the
direction a surface receives is proven to come from the same series the trend
line is drawn from.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    ReadinessConfidence,
    ReadinessHistory,
    ReadinessSnapshot,
    Subject,
    Topic,
    TopicReadiness,
)
from app.services.readiness_summary import DIRECTION_NOISE_BAND, trend_direction
from tests.factories import subject_defaults

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


# ---- The pure rule ----


def test_single_point_yields_null_direction():
    # One point is not a trend. Absent, never "flat" — a "→" beside a first
    # ever score would claim a movement nobody measured (PROD-2, edge case 7).
    assert trend_direction([61.0]) is None


def test_empty_series_yields_null_direction():
    assert trend_direction([]) is None


def test_rising_series_yields_up():
    assert trend_direction([50.0, 60.0, 72.0]) == "up"


def test_falling_series_yields_down():
    assert trend_direction([72.0, 60.0, 50.0]) == "down"


def test_series_within_noise_band_yields_flat():
    # Net movement inside the dead-zone is not a direction.
    assert trend_direction([60.0, 61.0, 62.0]) == "flat"
    assert trend_direction([62.0, 61.0, 60.0]) == "flat"


def test_noise_band_boundary_is_flat_not_up():
    # Exactly the band is still flat; a hair past it is a direction.
    assert trend_direction([60.0, 60.0 + DIRECTION_NOISE_BAND]) == "flat"
    assert trend_direction([60.0, 60.0 + DIRECTION_NOISE_BAND + 0.1]) == "up"


def test_direction_is_net_not_last_tick():
    # A dip on the way up is still up: the arrow describes the window, not the
    # most recent recomputation.
    assert trend_direction([40.0, 80.0, 70.0]) == "up"


# ---- Wired through the API ----


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.flush()
        topic = Topic(subject_id=subject.id, code="1.1", title="Forces", weight=1.0)
        session.add(topic)
        await session.commit()
        subject_id, topic_id = subject.id, topic.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set A", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara01", "password": "password123"}
    )
    world = {
        "subject_id": subject_id,
        "topic_id": topic_id,
        "student_id": student["id"],
        "headers": {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"},
    }
    # A current v1 score, so the summary has a value for an arrow to describe.
    # Without one the score is None and the direction is correctly suppressed —
    # which is its own test below, not the state these cases are exercising.
    async with async_session() as session:
        session.add(
            TopicReadiness(
                student_id=world["student_id"],
                topic_id=topic_id,
                score=68.0,
                confidence=ReadinessConfidence.high,
                evidence_count=4,
            )
        )
        await session.commit()
    return world


async def record_history(world, scores):
    """Write a v1 history series, oldest first."""
    async with async_session() as session:
        for offset, score in enumerate(scores):
            session.add(
                ReadinessHistory(
                    student_id=world["student_id"],
                    subject_id=world["subject_id"],
                    score=score,
                    recorded_at=NOW - timedelta(days=len(scores) - offset),
                )
            )
        await session.commit()


async def direction_from_api(client, world):
    resp = await client.get("/api/v1/readiness/me", headers=world["headers"])
    assert resp.status_code == 200
    return resp.json()["subjects"][0]["direction"]


async def test_no_history_reports_no_direction(client, tutor, world):
    assert await direction_from_api(client, world) is None


async def test_a_subject_with_no_score_carries_no_arrow(client, tutor, world):
    """Even with a full history, a subject reporting no score reports no
    direction — the arrow describes the value shown, and there isn't one."""
    from sqlalchemy import delete

    async with async_session() as session:
        await session.execute(
            delete(TopicReadiness).where(TopicReadiness.student_id == world["student_id"])
        )
        await session.commit()
    await record_history(world, [40.0, 55.0, 68.0])
    resp = await client.get("/api/v1/readiness/me", headers=world["headers"])
    subject = resp.json()["subjects"][0]
    assert subject["score"] is None
    assert subject["direction"] is None


async def test_single_history_point_reports_no_direction(client, tutor, world):
    await record_history(world, [55.0])
    assert await direction_from_api(client, world) is None


async def test_rising_history_reports_up(client, tutor, world):
    await record_history(world, [40.0, 55.0, 68.0])
    assert await direction_from_api(client, world) == "up"


async def test_falling_history_reports_down(client, tutor, world):
    await record_history(world, [68.0, 55.0, 40.0])
    assert await direction_from_api(client, world) == "down"


async def test_direction_matches_the_trend_endpoint_series(client, tutor, world):
    """The arrow and the line are the same claim — both read one series."""
    await record_history(world, [40.0, 55.0, 68.0])
    trend = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/trend", headers=world["headers"]
    )
    points = [p["score"] for p in trend.json()[0]["points"]]
    assert points == [40.0, 55.0, 68.0]
    assert await direction_from_api(client, world) == trend_direction(points)


# ---- The v2 path ----


async def write_snapshots(world, scores):
    """A ready v2 snapshot per score, oldest first. A None score is a
    no-evidence run, which v2 writes as ready with score=None."""
    async with async_session() as session:
        for offset, score in enumerate(scores):
            session.add(
                ReadinessSnapshot(
                    evaluation_run_id=str(uuid.uuid4()),
                    student_id=world["student_id"],
                    subject_id=world["subject_id"],
                    status=AiSynthesisStatus.ready,
                    score=score,
                    predicted_grade=None if score is None else "6",
                    weak_topics=[],
                    rationale="r",
                    recommended_revision=None,
                    created_at=NOW - timedelta(days=len(scores) - offset),
                )
            )
        await session.commit()


async def test_v2_rising_snapshots_report_up(client, tutor, world):
    await write_snapshots(world, [45.0, 60.0, 78.0])
    assert await direction_from_api(client, world) == "up"


async def test_v2_single_snapshot_reports_no_direction(client, tutor, world):
    await write_snapshots(world, [45.0])
    assert await direction_from_api(client, world) is None


async def test_v2_no_evidence_snapshot_carries_no_arrow(client, tutor, world):
    """The regression this guards: a subject whose latest run found no evidence
    shows "not enough data yet". Older scored snapshots must not lend it an
    arrow — that would describe a score the card is not showing (PROD-2)."""
    await write_snapshots(world, [45.0, 60.0, 78.0, None])
    resp = await client.get("/api/v1/readiness/me", headers=world["headers"])
    subject = resp.json()["subjects"][0]
    assert subject["score"] is None
    assert subject["direction"] is None


async def test_v1_score_is_not_paired_with_a_v2_arrow(client, tutor, world):
    """build_summary is the v1 engine and reports v1's score, so its arrow must
    come from v1 history — never from a v2 series the score did not come from."""
    from app.db import async_session as session_factory
    from app.models import User
    from app.services.readiness_summary import build_summary

    await record_history(world, [60.0, 61.0])  # v1 history: flat
    await write_snapshots(world, [10.0, 90.0])  # v2 snapshots: sharply up

    async with session_factory() as session:
        student = await session.get(User, world["student_id"])
        summary = await build_summary(session, student, [world["subject_id"]])

    subject = summary.subjects[0]
    assert subject.score == 68.0  # v1's own number
    # "flat" from v1 history — not the "up" the v2 series would have given.
    assert subject.direction == "flat"
