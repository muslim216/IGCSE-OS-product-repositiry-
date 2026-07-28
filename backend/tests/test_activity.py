"""The header activity indicator: each role sees only its own work."""

from app.workers.jobs import process_one_job

# The homework fixtures build the group/student/assignment chain this needs;
# importing them into the module namespace is what makes them resolvable here.
from tests.test_homework import (  # noqa: F401
    PNG_BYTES,
    classified,
    fake_marking,
    group,
    published_assignment,
    student,
    subject,
)


async def test_tutor_sees_submissions_awaiting_review(
    client, tutor, student, published_assignment, monkeypatch
):
    empty = await client.get("/api/v1/me/activity", headers=tutor["headers"])
    assert empty.json()["count"] == 0

    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )

    resp = await client.get("/api/v1/me/activity", headers=tutor["headers"])
    assert resp.json()["count"] == 1
    item = resp.json()["items"][0]
    assert item["kind"] == "submission_awaiting_review"
    assert "Sara" in item["label"]
    # The link keeps the class context the restructure introduced.
    assert item["link"].startswith("/tutor/groups/")

    # Finalizing clears it.
    assert await process_one_job() is True
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[
            {"question_id": m["question_id"], "final_marks": 1, "final_feedback": "ok"}
            for m in detail.json()["marks"]
        ],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])

    cleared = await client.get("/api/v1/me/activity", headers=tutor["headers"])
    assert cleared.json()["count"] == 0


async def test_student_sees_their_marked_work_not_the_tutors_queue(
    client, tutor, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    # Pending review for the tutor is not news for the student.
    pending = await client.get("/api/v1/me/activity", headers=student["headers"])
    assert pending.json()["count"] == 0

    assert await process_one_job() is True
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[
            {"question_id": m["question_id"], "final_marks": 1, "final_feedback": "ok"}
            for m in detail.json()["marks"]
        ],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])

    resp = await client.get("/api/v1/me/activity", headers=student["headers"])
    assert resp.json()["count"] == 1
    assert resp.json()["items"][0]["kind"] == "homework_marked"


async def test_another_tutors_queue_stays_private(client, tutor, student, published_assignment):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-activity@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    resp = await client.get("/api/v1/me/activity", headers=headers)
    assert resp.json()["count"] == 0
