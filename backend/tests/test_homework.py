import pytest
from sqlalchemy import select

from app.models import (
    AssignmentQuestion,
    MarkConfidence,
    QuestionMark,
    QuestionTopic,
    Topic,
)
from app.workers.jobs import process_one_job

PDF_BYTES = b"%PDF-1.4 fake test pdf"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake test png"


@pytest.fixture
async def subject(client, tutor):
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        s = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(s)
        await session.flush()
        t1 = Topic(subject_id=s.id, code="1.3", title="Atomic structure")
        t2 = Topic(subject_id=s.id, code="1.6", title="Ionic bonding")
        session.add_all([t1, t2])
        await session.commit()
        return {"id": s.id, "topic1": t1.id, "topic2": t2.id}


@pytest.fixture
async def group(client, tutor, subject):
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    return resp.json()


@pytest.fixture
async def student(client, tutor, group):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


@pytest.fixture
async def classified(client, tutor, subject):
    resp = await client.post(
        "/api/v1/classifieds",
        data={"title": "Atomic structure classified", "subject_id": str(subject["id"])},
        files={
            "file": ("classified.pdf", PDF_BYTES, "application/pdf"),
            "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def fake_extraction(subject):
    async def _fake(session, assignment):
        q1 = AssignmentQuestion(
            assignment_id=assignment.id,
            position=0,
            number="1",
            text_summary="Define an isotope",
            max_marks=2,
            has_mark_scheme=True,
        )
        q2 = AssignmentQuestion(
            assignment_id=assignment.id,
            position=1,
            number="2",
            text_summary="Explain ionic bonding in NaCl",
            max_marks=4,
            has_mark_scheme=False,
        )
        session.add_all([q1, q2])
        await session.flush()
        session.add(QuestionTopic(question_id=q1.id, topic_id=subject["topic1"]))
        session.add(QuestionTopic(question_id=q2.id, topic_id=subject["topic2"]))

    return _fake


async def fake_marking(session, submission):
    questions = (
        await session.scalars(
            select(AssignmentQuestion).where(
                AssignmentQuestion.assignment_id == submission.assignment_id
            )
        )
    ).all()
    for q in questions:
        mark = QuestionMark(submission_id=submission.id, question_id=q.id)
        mark.ai_transcription = f"Student answer for Q{q.number}"
        if q.has_mark_scheme:
            mark.ai_marks = 1
            mark.ai_feedback = "Half right"
            mark.ai_confidence = MarkConfidence.high
        else:
            mark.ai_marks = None
            mark.ai_confidence = MarkConfidence.tutor_only
        session.add(mark)


@pytest.fixture
async def published_assignment(client, tutor, group, classified, subject, monkeypatch):
    monkeypatch.setattr("app.services.extraction._run_extraction", fake_extraction(subject))
    resp = await client.post(
        "/api/v1/assignments",
        json={
            "group_id": group["id"],
            "classified_id": classified["id"],
            "title": "HW1 — Atomic structure",
            "question_range": "Q1-2",
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assignment = resp.json()
    assert assignment["status"] == "extracting"
    assert await process_one_job() is True

    # Extraction that produced questions publishes itself, so students aren't
    # blocked waiting for the tutor to come back and press a button.
    detail = await client.get(f"/api/v1/assignments/{assignment['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "published"
    assert len(detail.json()["questions"]) == 2
    return detail.json()


async def test_extraction_flow(published_assignment):
    q1, q2 = published_assignment["questions"]
    assert q1["has_mark_scheme"] is True
    assert q1["topics"][0]["code"] == "1.3"
    assert q2["has_mark_scheme"] is False


async def test_student_sees_published_assignment(client, student, published_assignment):
    resp = await client.get("/api/v1/me/assignments", headers=student["headers"])
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["title"] == "HW1 — Atomic structure"
    assert items[0]["total_marks"] == 6
    assert items[0]["submission_status"] == "not_submitted"


async def test_full_marking_lifecycle(client, tutor, student, published_assignment, monkeypatch):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]

    submit = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[
            ("files", ("page1.png", PNG_BYTES, "image/png")),
            ("files", ("page2.png", PNG_BYTES, "image/png")),
        ],
        headers=student["headers"],
    )
    assert submit.status_code == 201, submit.text
    assert submit.json()["status"] == "submitted"

    assert await process_one_job() is True

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert subs.json()[0]["status"] == "ai_marked"
    sid = subs.json()[0]["id"]

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = detail.json()["marks"]
    assert marks[0]["ai_marks"] == 1
    assert marks[0]["ai_confidence"] == "high"
    assert marks[1]["ai_marks"] is None
    assert marks[1]["ai_confidence"] == "tutor_only"

    # Students never see the AI draft.
    student_view = await client.get(
        f"/api/v1/assignments/{aid}/my-submission", headers=student["headers"]
    )
    assert student_view.json()["status"] == "being_marked"
    assert student_view.json()["marks"] == []

    # Tutor accepts Q1's AI mark, overrides nothing, and marks Q2 manually.
    save = await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[
            {"question_id": marks[0]["question_id"], "final_marks": 1, "final_feedback": "Half right"},
            {"question_id": marks[1]["question_id"], "final_marks": 3, "final_feedback": "Good diagram"},
        ],
        headers=tutor["headers"],
    )
    assert save.status_code == 200, save.text

    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200
    assert final.json()["status"] == "finalized"

    student_view = await client.get(
        f"/api/v1/assignments/{aid}/my-submission", headers=student["headers"]
    )
    body = student_view.json()
    assert body["status"] == "marked"
    assert body["total"] == 4
    assert body["total_max"] == 6
    assert body["marks"][1]["final_feedback"] == "Good diagram"


async def test_finalize_requires_all_marks(client, tutor, student, published_assignment, monkeypatch):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    await process_one_job()
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]
    resp = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert resp.status_code == 422
    assert "missing" in resp.json()["detail"].lower()


async def test_marking_fails_gracefully_without_api_key(client, tutor, student, published_assignment):
    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    # Run the real marking handler (twice: it retries once) — no API key configured.
    await process_one_job()
    await process_one_job()
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert subs.json()[0]["status"] == "ai_failed"
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    assert "ANTHROPIC_API_KEY" in detail.json()["ai_error"]

    # The tutor can still mark manually and finalize.
    marks = detail.json()["marks"]
    save = await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": m["question_id"], "final_marks": 1} for m in marks],
        headers=tutor["headers"],
    )
    assert save.status_code == 200
    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200


async def test_student_cannot_access_tutor_endpoints(client, student, published_assignment):
    aid = published_assignment["id"]
    resp = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=student["headers"])
    assert resp.status_code == 403


async def test_other_tutor_cannot_see_assignment(client, published_assignment):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/assignments/{published_assignment['id']}", headers=headers)
    assert resp.status_code == 404


async def test_resubmission_resets_marking(client, tutor, student, published_assignment, monkeypatch):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    first = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert first.status_code == 201
    await process_one_job()

    second = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("better.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert second.status_code == 201
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert len(subs.json()) == 1
    assert subs.json()[0]["status"] == "submitted"


async def test_upload_and_set_homework_in_one_request(client, tutor, group, subject, monkeypatch):
    """A tutor should be able to drop a paper in and be done."""
    monkeypatch.setattr("app.services.extraction._run_extraction", fake_extraction(subject))
    resp = await client.post(
        "/api/v1/assignments/upload",
        data={"group_id": group["id"]},
        files={"file": ("4CH1 June 2023 Paper 1.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assignment = resp.json()
    # Title falls back to the file name rather than being a required field.
    assert assignment["title"] == "4CH1 June 2023 Paper 1"
    assert assignment["status"] == "extracting"

    # One request created both the classified and the assignment.
    classifieds = await client.get("/api/v1/classifieds", headers=tutor["headers"])
    assert len(classifieds.json()) == 1

    assert await process_one_job() is True
    detail = await client.get(
        f"/api/v1/assignments/{assignment['id']}", headers=tutor["headers"]
    )
    assert detail.json()["status"] == "published"


async def test_upload_rejects_a_class_the_tutor_does_not_own(client, tutor, group):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/assignments/upload",
        data={"group_id": group["id"]},
        files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_iphone_photos_are_converted_to_jpeg(client, tutor, group, subject, monkeypatch):
    """HEIC is what an iPhone camera produces, but the AI image API won't take it."""
    import io

    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 30, 30)).save(buffer, format="HEIF")
    heic_bytes = buffer.getvalue()

    from app.services import storage

    path, name, mime = storage.save_bytes(heic_bytes, "image/heic", "work.heic")
    assert mime == "image/jpeg"
    assert path.endswith(".jpg")
    assert storage.read_file(path).startswith(b"\xff\xd8")  # JPEG magic bytes


async def test_unsupported_file_type_is_rejected_clearly():
    from fastapi import HTTPException

    from app.services import storage

    with pytest.raises(HTTPException) as excinfo:
        storage.save_bytes(b"not a real file", "application/zip", "notes.zip")
    assert excinfo.value.status_code == 415
    assert "HEIC" in excinfo.value.detail


async def test_mime_aliases_are_normalised():
    """Some clients report image/jpg; it must not be rejected as unknown."""
    from app.services import storage

    _, _, mime = storage.save_bytes(b"\xff\xd8\xff fake jpeg", "image/jpg", "photo.jpg")
    assert mime == "image/jpeg"


async def test_questions_stay_editable_until_work_is_submitted(
    client, tutor, student, published_assignment, monkeypatch
):
    """Auto-publishing must not mean the tutor can never correct the AI."""
    aid = published_assignment["id"]
    questions = published_assignment["questions"]
    edited = [
        {
            "number": q["number"],
            "text_summary": "Corrected wording" if i == 0 else q["text_summary"],
            "max_marks": q["max_marks"],
            "has_mark_scheme": q["has_mark_scheme"],
            "topic_ids": [t["id"] for t in q["topics"]],
        }
        for i, q in enumerate(questions)
    ]
    resp = await client.put(
        f"/api/v1/assignments/{aid}/questions", json=edited, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["questions"][0]["text_summary"] == "Corrected wording"

    # Once a student has submitted, editing would orphan their marks.
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    submit = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert submit.status_code == 201

    blocked = await client.put(
        f"/api/v1/assignments/{aid}/questions", json=edited, headers=tutor["headers"]
    )
    assert blocked.status_code == 409
    assert "submitted" in blocked.json()["detail"]
