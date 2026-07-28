"""The activity hub: what's waiting, derived from live rows rather than a
read/unread table."""

import pytest

from app.workers.jobs import process_one_job

# Reuse the homework fixtures rather than rebuilding a tutor/group/student.
from tests.test_homework import (  # noqa: F401
    PNG_BYTES,
    classified,
    fake_marking,
    group,
    published_assignment,
    student,
    subject,
)


async def test_activity_is_empty_before_anything_happens(client, tutor):
    resp = await client.get("/api/v1/me/activity", headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "items": []}


async def test_tutor_sees_work_awaiting_review(
    client, tutor, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    body = (await client.get("/api/v1/me/activity", headers=tutor["headers"])).json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["kind"] == "submission_awaiting_review"
    assert "Sara" in item["label"]
    # The link must reach the submission the tutor has to act on.
    assert item["link"].startswith("/tutor/submissions/")


async def test_a_student_sees_their_marked_work_not_the_tutor_queue(
    client, tutor, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    # Still needs_review, so nothing is final for the student yet.
    body = (await client.get("/api/v1/me/activity", headers=student["headers"])).json()
    assert body["items"] == []

    subs = await client.get(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        headers=tutor["headers"],
    )
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = [
        {"question_id": m["question_id"], "final_marks": 1, "final_feedback": "ok"}
        for m in detail.json()["marks"]
    ]
    await client.put(f"/api/v1/submissions/{sid}/marks", json=marks, headers=tutor["headers"])
    await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])

    body = (await client.get("/api/v1/me/activity", headers=student["headers"])).json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "homework_marked"

    # And the tutor's queue has emptied now the work is signed off.
    tutor_body = (await client.get("/api/v1/me/activity", headers=tutor["headers"])).json()
    assert tutor_body["count"] == 0


async def test_a_tutor_never_sees_another_tutors_work(client, tutor, published_assignment):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    body = (await client.get("/api/v1/me/activity", headers=headers)).json()
    assert body == {"count": 0, "items": []}
