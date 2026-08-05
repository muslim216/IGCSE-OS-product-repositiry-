"""The activity hub: what's waiting, derived from live rows rather than a
read/unread table."""

from app.workers.jobs import process_one_job

# Reuse the homework fixtures rather than rebuilding a tutor/group/student.
from tests.test_homework import (  # noqa: F401
    PNG_BYTES,
    classified,
    group,
    published_assignment,
    student,
    subject,
)


def marked_by_ai(fake_ai, monkeypatch):
    """Run the real marking path against a fabricated AI response, patching the
    normalized boundary rather than the marking function itself."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    result = MarkingResult(
        questions=[
            QuestionMarkDraft(
                number="1",
                transcription="An isotope has the same protons, different neutrons.",
                proposed_marks=1,
                feedback="Half right.",
                confidence="high",
            ),
            QuestionMarkDraft(
                number="2",
                transcription="Ionic bonding is electrostatic attraction.",
                proposed_marks=2,
                feedback="Say more about the ions.",
                confidence="high",
            ),
        ]
    )
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(result))


async def test_activity_is_empty_before_anything_happens(client, tutor):
    resp = await client.get("/api/v1/me/activity", headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "items": []}


async def test_tutor_sees_work_awaiting_review(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    marked_by_ai(fake_ai, monkeypatch)
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
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    marked_by_ai(fake_ai, monkeypatch)
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


async def test_a_tutor_never_sees_another_tutors_work(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    """There has to be work to leak before an empty result proves anything."""
    marked_by_ai(fake_ai, monkeypatch)
    await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True
    # The first tutor can see it...
    assert (await client.get("/api/v1/me/activity", headers=tutor["headers"])).json()["count"] == 1

    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    # ...and a tutor in another organization sees nothing of it.
    body = (await client.get("/api/v1/me/activity", headers=headers)).json()
    assert body == {"count": 0, "items": []}


async def test_a_parent_sees_a_ready_report_for_their_child(client, tutor, student):
    """Parents get reports, not the tutor's queue."""
    from app.db import async_session
    from app.models import Report, ReportAudience, ReportStatus

    # Link the parent through the real invite flow so the account is built the
    # way the app builds it (organization, roles and all).
    code = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    registered = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code.json()["code"],
            "name": "Parent",
            "email": "parent@example.com",
            "password": "password123",
        },
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

    # Nothing to show until a report is actually ready.
    assert (await client.get("/api/v1/me/activity", headers=headers)).json()["count"] == 0

    async with async_session() as session:
        session.add(
            Report(
                student_id=student["user"]["id"],
                generated_by_id=tutor["user"]["id"],
                title="Progress report",
                audience=ReportAudience.parent,
                status=ReportStatus.ready,
                content="All going well.",
            )
        )
        await session.commit()

    body = (await client.get("/api/v1/me/activity", headers=headers)).json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "report_ready"
    assert "Sara" in body["items"][0]["label"]


async def test_count_is_the_true_total_not_the_page_size(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    """`count` drives the badge, so it must report everything outstanding even
    when `items` is capped — otherwise a busy feed silently plateaus."""
    marked_by_ai(fake_ai, monkeypatch)
    await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    # A second piece of work, so there is more than one thing waiting.
    second = await client.post(
        "/api/v1/assignments",
        json={"group_id": published_assignment["group_id"], "title": "HW2"},
        headers=tutor["headers"],
    )
    aid = second.json()["id"]
    await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Define an isotope",
                "max_marks": 2,
                # No mark scheme, so the AI's mark is discarded and this lands
                # in the tutor's queue rather than auto-finalizing.
                "has_mark_scheme": False,
                "topic_ids": [],
            }
        ],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    monkeypatch.setattr("app.services.activity.ACTIVITY_LIMIT", 1)
    body = (await client.get("/api/v1/me/activity", headers=tutor["headers"])).json()
    assert len(body["items"]) == 1
    assert body["count"] == 2
