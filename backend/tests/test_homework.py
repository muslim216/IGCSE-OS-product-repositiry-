import pytest
from sqlalchemy import select

from app.models import (
    Assignment,
    AssignmentQuestion,
    Group,
    MarkConfidence,
    QuestionMark,
    QuestionTopic,
    SubmissionFile,
    Topic,
)
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults

PDF_BYTES = b"%PDF-1.4 fake test pdf"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake test png"


@pytest.fixture
async def subject(client, tutor):
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        s = Subject(
            **await subject_defaults(session),
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
    """Stands in for the AI call in _run_marking, then hands off to the real
    _settle_submission so the submission lands in the same state the live
    pipeline would leave it in (auto-finalized vs review queue)."""
    from app.services.marking import _settle_submission

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
            mark.final_marks = 1
            mark.final_feedback = "Half right"
            mark.auto_finalized = True
        else:
            mark.ai_marks = None
            mark.ai_confidence = MarkConfidence.unsure
            mark.needs_review = True
        session.add(mark)

    assignment = await session.get(Assignment, submission.assignment_id)
    group = await session.get(Group, assignment.group_id)
    await _settle_submission(session, submission, group.subject_id)


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

    # Successful extraction publishes automatically — students aren't blocked
    # on the tutor coming back for a second pass.
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


async def test_create_assignment_without_pdf(client, tutor, group):
    resp = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "No-PDF homework"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["classified_id"] is None
    assert body["status"] == "review"
    assert body["questions"] == []
    return body


async def test_no_pdf_assignment_can_be_published_after_manual_questions(client, tutor, group):
    created = await test_create_assignment_without_pdf(client, tutor, group)
    aid = created["id"]

    replace = await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Explain photosynthesis",
                "max_marks": 5,
                "has_mark_scheme": False,
                "topic_ids": [],
            }
        ],
        headers=tutor["headers"],
    )
    assert replace.status_code == 200, replace.text

    publish = await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])
    assert publish.status_code == 200
    assert publish.json()["status"] == "published"


async def test_no_pdf_assignment_retry_extraction_rejected(client, tutor, group):
    created = await test_create_assignment_without_pdf(client, tutor, group)
    resp = await client.post(
        f"/api/v1/assignments/{created['id']}/retry-extraction", headers=tutor["headers"]
    )
    assert resp.status_code == 409


async def test_no_pdf_assignment_marking_guard_runs_before_ai_call(client, tutor, student, group):
    """Real (unmocked) _run_marking must build the prompt without a classified
    and only fail once it reaches the AI call — proving the classified=None
    guard doesn't crash first."""
    created_resp = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "No-PDF homework"},
        headers=tutor["headers"],
    )
    aid = created_resp.json()["id"]
    await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Explain photosynthesis",
                "max_marks": 5,
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
    await process_one_job()
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    # Fails at the AI call (no API key), not at the classified lookup — the guard worked.
    assert subs.json()[0]["status"] == "ai_failed"
    assert "GEMINI_API_KEY" in detail.json()["ai_error"]


async def test_no_pdf_assignment_marking_does_not_crash(client, tutor, student, group, monkeypatch):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    created_resp = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "No-PDF homework"},
        headers=tutor["headers"],
    )
    aid = created_resp.json()["id"]
    await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Explain photosynthesis",
                "max_marks": 5,
                "has_mark_scheme": False,
                "topic_ids": [],
            }
        ],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])

    submit = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert submit.status_code == 201, submit.text
    assert await process_one_job() is True

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert subs.json()[0]["status"] == "needs_review"


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
    # Q2 has no mark scheme, so the submission waits on the tutor.
    assert subs.json()[0]["status"] == "needs_review"
    sid = subs.json()[0]["id"]

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = detail.json()["marks"]
    assert marks[0]["ai_marks"] == 1
    assert marks[0]["ai_confidence"] == "high"
    assert marks[0]["auto_finalized"] is True
    assert marks[0]["needs_review"] is False
    assert marks[1]["ai_marks"] is None
    assert marks[1]["ai_confidence"] == "unsure"
    assert marks[1]["needs_review"] is True

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
            {
                "question_id": marks[0]["question_id"],
                "final_marks": 1,
                "final_feedback": "Half right",
            },
            {
                "question_id": marks[1]["question_id"],
                "final_marks": 3,
                "final_feedback": "Good diagram",
            },
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


async def test_finalize_requires_all_marks(
    client, tutor, student, published_assignment, monkeypatch
):
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


async def test_marking_fails_gracefully_without_api_key(
    client, tutor, student, published_assignment
):
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
    assert "GEMINI_API_KEY" in detail.json()["ai_error"]

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


async def test_resubmission_resets_marking(
    client, tutor, student, published_assignment, monkeypatch
):
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


async def test_ai_marking_clamps_marks_and_enforces_mark_scheme_rule(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    """Exercises the real _run_marking mapping logic (not the fake_marking test
    double used elsewhere) against a fabricated AI response, to check the
    actual marking rules: clamping to the question's max, the hard
    has_mark_scheme=false -> no AI marks rule, and 'Q' prefix tolerance."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    fake_result = MarkingResult(
        questions=[
            # Q1 has_mark_scheme=True, max_marks=2 — AI over-proposes; must clamp to 2.
            QuestionMarkDraft(
                number="Q1",
                transcription="An isotope is an atom with the same protons, different neutrons.",
                proposed_marks=10,
                feedback="Good, but be more precise about protons vs neutrons.",
                confidence="high",
            ),
            # Q2 has_mark_scheme=False — AI proposes marks anyway; must be discarded.
            QuestionMarkDraft(
                number="2",
                transcription="Ionic bonding is the electrostatic attraction between ions.",
                proposed_marks=3,
                feedback="Nice explanation.",
                confidence="high",
            ),
        ]
    )
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(fake_result))

    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert subs.json()[0]["status"] == "needs_review"
    sid = subs.json()[0]["id"]

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = {m["question_id"]: m for m in detail.json()["marks"]}
    q1_mark, q2_mark = (
        marks[published_assignment["questions"][0]["id"]],
        marks[published_assignment["questions"][1]["id"]],
    )

    assert q1_mark["ai_marks"] == 2, "proposed 10 must be clamped to the question's max of 2"
    assert q1_mark["ai_confidence"] == "high"
    assert q2_mark["ai_marks"] == 3, "no mark scheme -> the AI still suggests a mark"
    assert q2_mark["final_marks"] is None, "...but it does not count until a tutor rules"
    assert q2_mark["needs_review"] is True


async def test_ai_marking_handles_question_missing_from_ai_response(
    client, tutor, student, group, monkeypatch, fake_ai
):
    """If the AI's response omits a question entirely, that question must get
    a safe tutor_only fallback rather than crashing or losing the record."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "No-PDF homework"},
        headers=tutor["headers"],
    )
    aid = created.json()["id"]
    await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Define an isotope",
                "max_marks": 2,
                "has_mark_scheme": True,
                "topic_ids": [],
            },
            {
                "number": "2",
                "text_summary": "Explain ionic bonding",
                "max_marks": 4,
                "has_mark_scheme": True,
                "topic_ids": [],
            },
        ],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])

    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Ali",
            "email": "ali2@example.com",
            "password": "password123",
        },
    )
    student2_headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

    fake_result = MarkingResult(
        questions=[
            QuestionMarkDraft(
                number="1",
                transcription="An isotope is an atom of the same element with a different mass number.",
                proposed_marks=2,
                feedback="Well explained.",
                confidence="high",
            ),
            # Q2 intentionally omitted.
        ]
    )
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(fake_result))

    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student2_headers,
    )
    assert await process_one_job() is True

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = detail.json()["marks"]
    q1 = next(m for m in marks if m["ai_marks"] == 2)
    q2 = next(m for m in marks if m is not q1)
    assert q2["ai_marks"] is None
    assert q2["ai_confidence"] == "unsure"
    assert q2["needs_review"] is True
    assert "did not return a result" in q2["ai_transcription"]


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
    detail = await client.get(f"/api/v1/assignments/{assignment['id']}", headers=tutor["headers"])
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


async def test_iphone_photos_are_converted_to_jpeg():
    """HEIC is what an iPhone camera produces, but the AI image API won't take it."""
    import io

    import pillow_heif
    from PIL import Image

    from app.services import storage

    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 30, 30)).save(buffer, format="HEIF")
    heic_bytes = buffer.getvalue()

    key, _name, mime = await storage.save_bytes(
        heic_bytes, "image/heic", "work.heic", organization_id=1
    )
    assert mime == "image/jpeg"
    assert key.endswith(".jpg")
    assert (await storage.read_file(key)).startswith(b"\xff\xd8")  # JPEG magic bytes


async def test_heic_that_cannot_be_decoded_is_rejected():
    """Bytes merely claiming to be HEIC must fail cleanly, not get stored."""
    from app.services import storage

    with pytest.raises(ValueError, match="couldn't be read"):
        await storage.save_bytes(
            b"definitely not an image", "image/heic", "fake.heic", organization_id=1
        )


async def test_mime_aliases_are_normalised():
    """Some clients report image/jpg; it must not be rejected as unknown."""
    from app.services import storage

    _, _, mime = await storage.save_bytes(
        b"\xff\xd8\xff fake jpeg", "image/jpg", "photo.jpg", organization_id=1
    )
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


async def test_published_homework_cannot_be_emptied_of_questions(
    client, tutor, published_assignment
):
    """Publishing guarantees at least one question; clearing the list would
    leave students looking at homework with nothing in it."""
    resp = await client.put(
        f"/api/v1/assignments/{published_assignment['id']}/questions",
        json=[],
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
    assert "at least one question" in resp.json()["detail"].lower()


async def test_oversized_bytes_are_rejected_before_any_decode():
    """The cap applies to the source bytes — a huge HEIC must not be decoded
    first and then measured as a much smaller JPEG."""
    from app.services import storage

    with pytest.raises(ValueError, match="20 MB"):
        await storage.save_bytes(
            b"\x00" * (storage.MAX_FILE_BYTES + 1),
            "image/heic",
            "huge.heic",
            organization_id=1,
        )


def _stored_keys() -> set[str]:
    """Every object the local backend currently holds.

    The StorageBackend contract has no list operation on purpose — nothing in
    the application needs to enumerate a tenant's objects, and an S3 list is a
    paginated network call, not a cheap directory read. The test reaches past
    the interface deliberately.
    """
    from pathlib import Path

    from app.config import get_settings

    root = Path(get_settings().upload_dir)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def test_a_rejected_mark_scheme_leaves_no_orphaned_file(client, tutor, group):
    """The paper is written to disk before the mark scheme is validated, so a
    bad mark scheme must take the already-written paper with it."""

    before = _stored_keys()
    resp = await client.post(
        "/api/v1/assignments/upload",
        data={"group_id": group["id"]},
        files={
            "file": ("paper.pdf", PDF_BYTES, "application/pdf"),
            "mark_scheme": ("scheme.zip", b"PK\x03\x04 not a document", "application/zip"),
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 415
    assert _stored_keys() == before


async def test_submission_files_are_proxied_never_redirected(
    client, tutor, student, published_assignment, signing_storage
):
    """The one rule F3 says must not be simplified away: student submissions
    proxy through the API on every view, even when the configured backend is
    capable of minting a signed URL. A redirect here would hand out a bearer
    credential for a photograph of a named minor's marked work."""
    aid = published_assignment["id"]
    submission = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("work.pdf", PDF_BYTES, "application/pdf"))],
        headers=student["headers"],
    )
    assert submission.status_code == 201, submission.text
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    submission_id = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{submission_id}", headers=tutor["headers"])
    file_id = detail.json()["files"][0]["id"]

    resp = await client.get(
        f"/api/v1/submissions/{submission_id}/files/{file_id}",
        headers=student["headers"],
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == PDF_BYTES
    assert "location" not in resp.headers


async def test_classified_material_gets_a_signed_redirect_by_contrast(
    client, tutor, classified, signing_storage
):
    """The other half of the F3 split: tutor material with no personal data
    does redirect. Proves the local-backend fallback in
    test_submission_files_are_proxied_never_redirected is a deliberate choice
    per endpoint, not the only path the code can take."""
    resp = await client.get(
        f"/api/v1/classifieds/{classified['id']}/file",
        headers=tutor["headers"],
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://objects.example/")


async def test_a_stale_row_returns_404_not_an_unhandled_500(
    client, tutor, student, published_assignment
):
    """The object a row points at can go missing independently of the row —
    a lifecycle policy, a manual bucket edit. That must surface as 404, not a
    bare 500 with no distinguishing signal (backend/app/api/file_responses.py)."""
    from app.db import async_session
    from app.services import storage

    aid = published_assignment["id"]
    submission = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("work.pdf", PDF_BYTES, "application/pdf"))],
        headers=student["headers"],
    )
    assert submission.status_code == 201, submission.text
    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    submission_id = subs.json()[0]["id"]
    detail = await client.get(f"/api/v1/submissions/{submission_id}", headers=tutor["headers"])
    file_id = detail.json()["files"][0]["id"]

    async with async_session() as session:
        row = await session.get(SubmissionFile, file_id)
        await storage.delete_file(row.path)  # the object vanishes; the row stays

    resp = await client.get(
        f"/api/v1/submissions/{submission_id}/files/{file_id}",
        headers=student["headers"],
    )
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
