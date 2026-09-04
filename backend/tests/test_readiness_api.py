"""Integration tests: finalize homework / enter mocks -> evidence -> readiness."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Evidence,
    EvidenceSource,
    Subject,
    Topic,
)
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults


@pytest.fixture
async def world(client, tutor):
    """A tutor, a subject with topics, a group, and a student in it."""
    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[
                {"grade": "9", "min": 90},
                {"grade": "7", "min": 70},
                {"grade": "4", "min": 40},
                {"grade": "U", "min": 0},
            ],
        )
        session.add(subject)
        await session.flush()
        t1 = Topic(subject_id=subject.id, code="1.3", title="Atomic structure", weight=1.0)
        t2 = Topic(subject_id=subject.id, code="1.6", title="Ionic bonding", weight=2.0)
        session.add_all([t1, t2])
        await session.commit()
        subject_id, t1_id, t2_id = subject.id, t1.id, t2.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student_resp = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Sara", "username": "sara01", "password": "password123"},
        headers=tutor["headers"],
    )
    student = student_resp.json()
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara01", "password": "password123"}
    )
    return {
        "subject_id": subject_id,
        "topic1": t1_id,
        "topic2": t2_id,
        "group": group,
        "student_id": student["id"],
        "student_headers": {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"},
    }


async def test_mock_entry_produces_readiness_and_grade(client, tutor, world):
    resp = await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "October Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {
                    "student_id": world["student_id"],
                    "topic_id": world["topic1"],
                    "marks": 18,
                    "max_marks": 20,
                },
                {
                    "student_id": world["student_id"],
                    "topic_id": world["topic2"],
                    "marks": 8,
                    "max_marks": 20,
                },
            ],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text

    assert await process_one_job() is True  # recompute_readiness

    summary = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    assert summary.status_code == 200
    body = summary.json()
    subject = body["subjects"][0]
    # topic1 = 90%, topic2 = 40%, weighted (1*90 + 2*40)/3 = 56.7
    assert subject["score"] == pytest.approx(56.7, abs=0.2)
    assert subject["predicted_grade"] == "4"  # 56.7 -> grade 4
    # Band is positional: this subject's boundary list is [9, 7, 4, U], so "4"
    # sits at index 2 — inside the top band — regardless of the 56.7 percentage.
    assert subject["status"] == "on_track"
    # Weak topics need medium+ confidence; a single mock is low confidence,
    # so nothing is surfaced as weak yet.
    assert subject["weak_topics"] == []


async def test_homework_finalize_feeds_readiness(client, tutor, world, monkeypatch):
    from app.models import AssignmentQuestion, QuestionTopic
    from tests.test_homework import PDF_BYTES, PNG_BYTES, fake_marking

    # Build a published assignment via a fake extraction tied to this subject.
    async def fake_extraction(session, assignment):
        q = AssignmentQuestion(
            assignment_id=assignment.id,
            position=0,
            number="1",
            text_summary="Atomic structure question",
            max_marks=10,
            has_mark_scheme=True,
        )
        session.add(q)
        await session.flush()
        session.add(QuestionTopic(question_id=q.id, topic_id=world["topic1"]))

    monkeypatch.setattr("app.services.extraction._run_extraction", fake_extraction)
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)

    classified = (
        await client.post(
            "/api/v1/classifieds",
            data={"title": "C", "subject_id": str(world["subject_id"])},
            files={
                "file": ("c.pdf", PDF_BYTES, "application/pdf"),
                "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
            },
            headers=tutor["headers"],
        )
    ).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "group_id": world["group"]["id"],
                "classified_id": classified["id"],
                "title": "HW1",
            },
            headers=tutor["headers"],
        )
    ).json()
    await process_one_job()  # extraction
    await client.post(f"/api/v1/assignments/{assignment['id']}/publish", headers=tutor["headers"])

    await client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        files=[("files", ("p.png", PNG_BYTES, "image/png"))],
        headers=world["student_headers"],
    )
    await process_one_job()  # marking

    subs = await client.get(
        f"/api/v1/assignments/{assignment['id']}/submissions", headers=tutor["headers"]
    )
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    qid = detail.json()["marks"][0]["question_id"]
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": qid, "final_marks": 8, "final_feedback": "Good"}],
        headers=tutor["headers"],
    )
    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200

    # Finalize should have created evidence and enqueued a recompute.
    async with async_session() as session:
        ev = (
            await session.scalars(
                select(Evidence).where(Evidence.student_id == world["student_id"])
            )
        ).all()
        assert len(ev) == 1
        assert ev[0].source_type == EvidenceSource.homework
        assert ev[0].score_pct == 80.0

    await process_one_job()  # recompute
    summary = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    subject = summary.json()["subjects"][0]
    topic1 = next(t for t in subject["topics"] if t["topic_id"] == world["topic1"])
    assert topic1["score"] == 80.0

    # The one finalized piece is also the whole of the averaging grade: 8/10,
    # mapped through the same boundaries as the prediction ([9, 7, 4, U]).
    assert subject["averaging_score"] == 80.0
    assert subject["averaging_grade"] == "7"
    assert subject["marked_piece_count"] == 1


async def test_tutor_only_sees_own_students_readiness(client, world):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other2@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/readiness/students/{world['student_id']}", headers=headers)
    assert resp.status_code == 404


async def test_observation_with_rating_feeds_readiness(client, tutor, world):
    resp = await client.post(
        "/api/v1/observations",
        json={
            "student_id": world["student_id"],
            "topic_id": world["topic1"],
            "comment": "Strong grasp of electron shells",
            "rating": 85,
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201
    await process_one_job()
    ev = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/topics/{world['topic1']}/evidence",
        headers=tutor["headers"],
    )
    assert ev.status_code == 200
    assert ev.json()["evidence"][0]["source_type"] == "observation"
    assert ev.json()["evidence"][0]["score_pct"] == 85.0


async def test_group_analytics_and_agreement(client, tutor, world):
    # Enter a mock so there is readiness data.
    await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {
                    "student_id": world["student_id"],
                    "topic_id": world["topic2"],
                    "marks": 5,
                    "max_marks": 20,
                },
            ],
        },
        headers=tutor["headers"],
    )
    await process_one_job()
    analytics = await client.get(
        f"/api/v1/analytics/groups/{world['group']['id']}", headers=tutor["headers"]
    )
    assert analytics.status_code == 200
    body = analytics.json()
    assert any(w["student_id"] == world["student_id"] for w in body["weak_students"])
    assert body["agreement"]["total_marked_questions"] == 0
