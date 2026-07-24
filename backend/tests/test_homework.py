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

    detail = await client.get(f"/api/v1/assignments/{assignment['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "review"
    assert len(detail.json()["questions"]) == 2

    publish = await client.post(
        f"/api/v1/assignments/{assignment['id']}/publish", headers=tutor["headers"]
    )
    assert publish.status_code == 200
    return publish.json()


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
    assert subs.json()[0]["status"] == "ai_marked"


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
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(fake_result)
    )

    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    assert subs.json()[0]["status"] == "ai_marked"
    sid = subs.json()[0]["id"]

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    marks = {m["question_id"]: m for m in detail.json()["marks"]}
    q1_mark, q2_mark = marks[published_assignment["questions"][0]["id"]], marks[
        published_assignment["questions"][1]["id"]
    ]

    assert q1_mark["ai_marks"] == 2, "proposed 10 must be clamped to the question's max of 2"
    assert q1_mark["ai_confidence"] == "high"
    assert q2_mark["ai_marks"] is None, "no mark scheme -> AI marks must be discarded"
    assert q2_mark["ai_confidence"] == "tutor_only"


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
    student2_headers = {
        "Authorization": f"Bearer {reg.json()['tokens']['access_token']}"
    }

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
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(fake_result)
    )

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
    assert q2["ai_confidence"] == "tutor_only"
    assert "did not return a result" in q2["ai_transcription"]
