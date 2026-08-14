"""PR 19 — the class page's headline endpoint.

The property that matters: NEEDS YOU is selected on direction, not level. A
learner sliding from a grade 8 to a 6 is the one the tutor can still help; a
learner who has been a stable grade 4 all year is why the class carries its
status and is not news. Both stay visible under Learners.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    ReadinessConfidence,
    ReadinessHistory,
    Subject,
    Topic,
    TopicReadiness,
)

BOUNDARIES = [
    {"grade": "9", "min": 90},
    {"grade": "8", "min": 80},
    {"grade": "7", "min": 70},
    {"grade": "6", "min": 60},
    {"grade": "5", "min": 50},
    {"grade": "4", "min": 40},
    {"grade": "U", "min": 0},
]


@pytest.fixture
async def subject_id():
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=BOUNDARIES,
        )
        session.add(subject)
        await session.flush()
        session.add(Topic(subject_id=subject.id, code="1.3", title="Atoms", weight=1.0))
        await session.commit()
        return subject.id


async def _class_with(client, tutor, subject_id):
    return (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()


async def _learner(client, tutor, group_id, name, username, score, history=()):
    student = (
        await client.post(
            f"/api/v1/groups/{group_id}/students",
            json={"name": name, "username": username, "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        topic_id = await session.scalar(select(Topic.id))
        session.add(
            TopicReadiness(
                student_id=student["id"],
                topic_id=topic_id,
                score=score,
                confidence=ReadinessConfidence.high,
                evidence_count=3,
            )
        )
        base = datetime.now(timezone.utc) - timedelta(days=30)
        for i, h in enumerate(history):
            session.add(
                ReadinessHistory(
                    student_id=student["id"],
                    subject_id=(await session.scalar(select(Topic.subject_id))),
                    score=h,
                    recorded_at=base + timedelta(days=i * 5),
                )
            )
        await session.commit()
    return student


async def test_declining_high_learner_is_in_needs_you(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    # Was a grade 8, now a 6 — still a good grade, but the movement is the story.
    await _learner(client, tutor, group["id"], "Slider", "slide01", 62.0, history=(85.0, 62.0))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    names = [r["student_name"] for r in body["needs_you"]]
    assert names == ["Slider"]
    assert body["needs_you"][0]["direction"] == "down"


async def test_stable_low_learner_is_absent_from_needs_you_but_present_under_learners(
    client, tutor, subject_id
):
    group = await _class_with(client, tutor, subject_id)
    # A steady grade 4 all year: why the class carries its status, but not news.
    await _learner(client, tutor, group["id"], "Steady", "steady01", 42.0, history=(41.0, 42.0))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    assert body["needs_you"] == []
    assert [r["student_name"] for r in body["learners"]] == ["Steady"]
    assert body["learners"][0]["direction"] == "flat"


async def test_one_history_point_yields_no_direction_never_flat(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "New", "new01", 70.0, history=(70.0,))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    # One point is not a trend: null, so the surface renders no arrow at all.
    assert body["learners"][0]["direction"] is None


async def test_a_learner_without_evidence_is_absent_not_zeroed(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ghost", "username": "ghost01", "password": "password123"},
        headers=tutor["headers"],
    )
    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    assert body["learners"] == []
    assert body["member_count"] == 1
    assert body["students_with_evidence"] == 0
    assert body["score"] is None


async def test_another_tutors_class_is_404_not_403(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    other = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "T2", "email": "t2@example.com", "password": "password123"},
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/today/classes/{group['id']}", headers=headers)
    assert resp.status_code == 404


async def test_a_student_cannot_reach_the_class_overview(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0)
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "aya01", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/today/classes/{group['id']}", headers=headers)
    assert resp.status_code == 403
