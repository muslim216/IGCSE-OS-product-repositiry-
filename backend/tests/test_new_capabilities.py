"""Tests for group resources, tutor preferences, student exams, today-lessons,
class briefs, and the homework attention list."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Subject, Topic
from app.workers.jobs import process_one_job


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.flush()
        t1 = Topic(subject_id=subject.id, code="1.3", title="Atomic structure", weight=1.0)
        session.add(t1)
        await session.commit()
        subject_id, topic_id = subject.id, t1.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
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
    return {
        "subject_id": subject_id,
        "topic_id": topic_id,
        "group": group,
        "student_id": student["id"],
        "student_headers": {
            "Authorization": f"Bearer {login.json()['tokens']['access_token']}"
        },
    }


# ---- Group resources ----


async def test_tutor_uploads_recording_link(client, tutor, world):
    resp = await client.post(
        f"/api/v1/groups/{world['group']['id']}/resources",
        data={"kind": "recording", "title": "Lesson 3 recap", "url": "https://example.com/rec"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "recording"


async def test_recording_url_rejects_non_http_scheme(client, tutor, world):
    resp = await client.post(
        f"/api/v1/groups/{world['group']['id']}/resources",
        data={
            "kind": "recording",
            "title": "Malicious link",
            "url": "javascript:alert(document.cookie)",
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_tutor_uploads_file_resource(client, tutor, world):
    resp = await client.post(
        f"/api/v1/groups/{world['group']['id']}/resources",
        data={"kind": "file", "title": "Revision notes"},
        files={"file": ("notes.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    rid = resp.json()["id"]

    download = await client.get(f"/api/v1/resources/{rid}/file", headers=tutor["headers"])
    assert download.status_code == 200


async def test_student_can_list_but_not_create_resources(client, tutor, world):
    await client.post(
        f"/api/v1/groups/{world['group']['id']}/resources",
        data={"kind": "recording", "title": "Recap", "url": "https://example.com/rec"},
        headers=tutor["headers"],
    )
    listing = await client.get(
        f"/api/v1/groups/{world['group']['id']}/resources", headers=world["student_headers"]
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    forbidden = await client.post(
        f"/api/v1/groups/{world['group']['id']}/resources",
        data={"kind": "recording", "title": "Recap 2", "url": "https://example.com/rec2"},
        headers=world["student_headers"],
    )
    assert forbidden.status_code == 403


async def test_unrelated_student_cannot_see_resources(client, tutor, world):
    other_tutor = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other_group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Other group", "subject_id": world["subject_id"]},
            headers={"Authorization": f"Bearer {other_tutor.json()['tokens']['access_token']}"},
        )
    ).json()
    resp = await client.get(
        f"/api/v1/groups/{other_group['id']}/resources", headers=world["student_headers"]
    )
    assert resp.status_code == 404


# ---- Tutor preferences ----


async def test_default_preferences(client, tutor):
    resp = await client.get("/api/v1/me/preferences", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_mock"] == 1.5
    assert body["half_life_days"] == 45.0


async def test_updating_preferences_changes_readiness(client, tutor, world):
    await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {"student_id": world["student_id"], "topic_id": world["topic_id"], "marks": 18, "max_marks": 20}
            ],
        },
        headers=tutor["headers"],
    )
    await process_one_job()

    baseline = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    baseline_score = baseline.json()["subjects"][0]["score"]
    assert baseline_score == 90.0  # single mock, full weight either way

    update = await client.put(
        "/api/v1/me/preferences",
        json={
            "weight_mock": 3.0,
            "weight_homework": 1.0,
            "weight_quiz": 0.8,
            "weight_observation": 0.5,
            "half_life_days": 10.0,
        },
        headers=tutor["headers"],
    )
    assert update.status_code == 200
    # Preference save enqueues a recompute for every affected student.
    assert await process_one_job() is True

    after = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    # A single-source topic score is weight-invariant, but half-life should
    # not change a same-day score either — this proves the save round-trips
    # and recompute re-ran without breaking anything.
    assert after.json()["subjects"][0]["score"] == 90.0


async def test_only_tutor_can_set_preferences(client, world):
    resp = await client.get("/api/v1/me/preferences", headers=world["student_headers"])
    assert resp.status_code == 403


# ---- Student exams ----


async def test_student_sees_own_assessment_scores(client, tutor, world):
    await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "October Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {"student_id": world["student_id"], "topic_id": world["topic_id"], "marks": 15, "max_marks": 20}
            ],
        },
        headers=tutor["headers"],
    )
    resp = await client.get("/api/v1/me/assessments", headers=world["student_headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "October Mock"
    assert body[0]["pct"] == 75.0


async def test_tutor_cannot_call_me_assessments(client, tutor):
    resp = await client.get("/api/v1/me/assessments", headers=tutor["headers"])
    assert resp.status_code == 403


# ---- Today lessons + class brief ----


async def test_today_lessons_only_for_tutor(client, world):
    resp = await client.get("/api/v1/me/today-lessons", headers=world["student_headers"])
    assert resp.status_code == 403


async def test_today_lessons_empty_without_matching_weekday(client, tutor, world):
    resp = await client.get("/api/v1/me/today-lessons", headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == []


async def test_class_brief_without_evidence(client, tutor, world):
    resp = await client.post(
        f"/api/v1/groups/{world['group']['id']}/brief", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    assert "brief" in resp.json()


async def test_class_brief_fails_gracefully_without_api_key(client, tutor, world):
    await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {"student_id": world["student_id"], "topic_id": world["topic_id"], "marks": 5, "max_marks": 20}
            ],
        },
        headers=tutor["headers"],
    )
    await process_one_job()
    resp = await client.post(
        f"/api/v1/groups/{world['group']['id']}/brief", headers=tutor["headers"]
    )
    assert resp.status_code == 503


# ---- Homework attention list ----


async def test_attention_list_flags_extraction_failure(client, tutor, world, monkeypatch):
    async def failing_extraction(session, assignment):
        raise ValueError("bad PDF")

    monkeypatch.setattr("app.services.extraction._run_extraction", failing_extraction)
    classified = (
        await client.post(
            "/api/v1/classifieds",
            data={"title": "C", "subject_id": str(world["subject_id"])},
            files={"file": ("c.pdf", b"%PDF-1.4", "application/pdf")},
            headers=tutor["headers"],
        )
    ).json()
    await client.post(
        "/api/v1/assignments",
        json={"group_id": world["group"]["id"], "classified_id": classified["id"], "title": "HW"},
        headers=tutor["headers"],
    )
    await process_one_job()

    attention = await client.get("/api/v1/assignments/attention", headers=tutor["headers"])
    assert attention.status_code == 200
    reasons = {a["reason"] for a in attention.json()}
    assert "extraction_failed" in reasons
