"""WS4: past papers — tutor uploads once, students self-log attempts, and the
whole thing rides the homework marking pipeline."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Evidence,
    EvidenceSource,
    PastPaper,
    PastPaperAttempt,
    PastPaperQuestion,
    QuestionMark,
    Submission,
    SubmissionStatus,
)
from app.workers.jobs import process_one_job
from tests.conftest import PDF_BYTES, PNG_BYTES
from tests.factories import subject_defaults


def _extraction_double(fake_ai):
    from app.services.extraction import ExtractedQuestion, PastPaperExtractionResult

    return fake_ai(
        PastPaperExtractionResult(
            title="Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice November 2026",
            session_label="November 2026",
            paper_number="Paper 2",
            questions=[
                ExtractedQuestion(
                    number="1",
                    text_summary="Define an isotope",
                    max_marks=2,
                    topic_codes=["1.3"],
                    has_mark_scheme=True,
                ),
                ExtractedQuestion(
                    number="2",
                    text_summary="Explain ionic bonding",
                    max_marks=4,
                    topic_codes=["1.6"],
                    has_mark_scheme=True,
                ),
            ],
        )
    )


def _marking_double(fake_ai, *, confidence="high"):
    from app.services.marking import MarkingResult, QuestionMarkDraft

    return fake_ai(
        MarkingResult(
            questions=[
                QuestionMarkDraft(
                    number="1",
                    transcription="a",
                    proposed_marks=2,
                    feedback="Correct.",
                    confidence=confidence,
                ),
                QuestionMarkDraft(
                    number="2",
                    transcription="b",
                    proposed_marks=3,
                    feedback="Nearly.",
                    confidence=confidence,
                ),
            ]
        )
    )


async def _upload(client, tutor, subject, *, with_scheme=True):  # noqa: F811
    files = [("booklet", ("paper.pdf", PDF_BYTES, "application/pdf"))]
    if with_scheme:
        files.append(("mark_scheme", ("ms.pdf", PDF_BYTES, "application/pdf")))
    return await client.post(
        "/api/v1/past-papers",
        data={
            "subject_id": str(subject["id"]),
            "duration_minutes": "90",
        },
        files=files,
        headers=tutor["headers"],
    )


@pytest.fixture
async def past_paper(client, tutor, subject, monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True  # extraction
    return resp.json()


async def test_upload_requires_the_official_mark_scheme(client, tutor, subject):  # noqa: F811
    """A full paper's marks feed a predicted grade — they can't rest on the
    AI's own judgement."""
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 422


async def test_upload_no_longer_accepts_session_label_or_paper_number(client, tutor, subject):  # noqa: F811
    """The tutor stops typing the paper's name — extraction reads it off the
    document instead. Extra form fields are simply ignored, not rejected."""
    resp = await client.post(
        "/api/v1/past-papers",
        data={
            "subject_id": str(subject["id"]),
            "session_label": "should be ignored",
            "paper_number": "should be ignored",
        },
        files=[
            ("booklet", ("paper.pdf", PDF_BYTES, "application/pdf")),
            ("mark_scheme", ("ms.pdf", PDF_BYTES, "application/pdf")),
        ],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["session_label"] is None
    assert resp.json()["paper_number"] is None


async def test_before_extraction_a_paper_is_untitled(past_paper):  # noqa: F811
    """`past_paper` here is the raw upload response, captured before the
    extraction job ran — the tutor's old typed guess is gone, and nothing
    fabricates a name in its place (`PROD-2`).

    Both fields are asserted because their difference is the point: `title` is
    null, so a client can tell "not read yet" from "a paper genuinely called
    that", and `display_title` carries the fallback for anything that only
    renders it. Collapsing them would let task 3.5's review form round-trip the
    literal string "Untitled paper" back into the column.
    """
    assert past_paper["title"] is None
    assert past_paper["display_title"] == "Untitled paper"
    assert past_paper["session_label"] is None
    assert past_paper["paper_number"] is None


async def test_upload_extracts_the_question_list(client, tutor, past_paper):
    detail = await client.get(f"/api/v1/past-papers/{past_paper['id']}", headers=tutor["headers"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["question_count"] == 2
    assert [q["number"] for q in body["questions"]] == ["1", "2"]
    # total_marks is filled in from the extracted questions when not given.
    assert body["total_marks"] == 6
    # The paper's name, session and paper number all come off the document —
    # the AI's structured output, not anything the tutor typed.
    assert (
        body["title"] == "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice November 2026"
    )
    assert body["session_label"] == "November 2026"
    assert body["paper_number"] == "Paper 2"
    async with async_session() as session:
        question = await session.scalar(select(PastPaperQuestion))
        assert question.ai_prompt_version == "test", "extraction records its prompt version"


async def test_a_student_can_read_the_booklet_but_never_the_mark_scheme(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    booklet = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/booklet", headers=student["headers"]
    )
    assert booklet.status_code == 200
    scheme = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/mark-scheme", headers=student["headers"]
    )
    assert scheme.status_code == 403
    # And the listing never leaks its filename either.
    listed = await client.get("/api/v1/past-papers", headers=student["headers"])
    assert listed.json()[0]["mark_scheme_name"] is None


async def test_a_tutor_can_download_the_mark_scheme(client, tutor, past_paper):
    resp = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/mark-scheme", headers=tutor["headers"]
    )
    assert resp.status_code == 200


async def _log_attempt(client, student, paper_id, **overrides):  # noqa: F811
    data = {"attempted_at": "2026-07-01", "timed": "true", "time_taken_minutes": "85"}
    data.update(overrides)
    return await client.post(
        f"/api/v1/past-papers/{paper_id}/attempts",
        data=data,
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )


async def test_a_student_self_logs_an_attempt_and_it_is_auto_marked(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    resp = await _log_attempt(client, student, past_paper["id"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["timed"] is True
    assert resp.json()["time_taken_minutes"] == 85

    assert await process_one_job() is True  # marking
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.auto_finalized
        assert submission.past_paper_id == past_paper["id"]
        assert submission.assignment_id is None
        marks = (await session.scalars(select(QuestionMark))).all()
        assert len(marks) == 2
        assert all(m.past_paper_question_id is not None for m in marks)
        assert all(m.question_id is None for m in marks)


async def test_a_settled_attempt_rolls_up_for_the_past_paper_factor(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True

    async with async_session() as session:
        attempt = await session.scalar(select(PastPaperAttempt))
        assert attempt is not None
        assert attempt.raw_marks == 5  # 2 + 3
        assert attempt.max_marks == 6  # out of the whole paper, not just what was done
        assert attempt.timed is True
        assert attempt.time_taken_minutes == 85
        assert str(attempt.attempted_at) == "2026-07-01"


async def test_marks_become_per_topic_past_paper_evidence(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Past papers feed Topic Mastery too, not just the Past Paper factor."""
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True

    async with async_session() as session:
        evidence = (await session.scalars(select(Evidence))).all()
        assert len(evidence) == 2  # one per topic
        assert all(e.source_type == EvidenceSource.past_paper for e in evidence)


async def test_an_unsure_question_sends_the_attempt_to_the_review_queue(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Past papers inherit the review queue with no extra code, because an
    attempt is just a Submission."""
    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        _marking_double(fake_ai, confidence="low"),
    )
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True

    queue = await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert queue.json()[0]["unsure_count"] == 2


async def test_marking_without_an_api_key_fails_gracefully(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    await _log_attempt(client, student, past_paper["id"])
    await process_one_job()
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.ai_failed
        # Anthropic since task 3.2 (AV-124) — a past-paper attempt goes through
        # the same marking surface, so it names the same key.
        assert "ANTHROPIC_API_KEY" in submission.ai_error


async def test_a_student_cannot_log_the_same_paper_twice_once_marked(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True
    again = await _log_attempt(client, student, past_paper["id"])
    assert again.status_code == 409


async def test_re_logging_before_marking_replaces_the_pages(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    first = await _log_attempt(client, student, past_paper["id"])
    assert first.status_code == 201
    second = await _log_attempt(client, student, past_paper["id"], time_taken_minutes="70")
    assert second.status_code == 201
    async with async_session() as session:
        submissions = (await session.scalars(select(Submission))).all()
        assert len(submissions) == 1
        assert submissions[0].time_taken_minutes == 70


async def test_my_attempt_reports_the_result(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    before = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/my-attempt", headers=student["headers"]
    )
    assert before.json() is None

    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True

    after = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/my-attempt", headers=student["headers"]
    )
    body = after.json()
    assert body["status"] == "marked"
    assert body["raw_marks"] == 5
    assert body["max_marks"] == 6


async def test_a_student_only_sees_papers_for_subjects_they_take(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    from app.models import Subject

    async with async_session() as session:
        other = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add(other)
        await session.commit()
        other_id = other.id

    resp = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(other_id)},
        files=[
            ("booklet", ("p.pdf", PDF_BYTES, "application/pdf")),
            ("mark_scheme", ("ms.pdf", PDF_BYTES, "application/pdf")),
        ],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201
    physics_id = resp.json()["id"]

    listed = await client.get("/api/v1/past-papers", headers=student["headers"])
    assert [p["id"] for p in listed.json()] == [past_paper["id"]]
    denied = await client.get(f"/api/v1/past-papers/{physics_id}", headers=student["headers"])
    assert denied.status_code == 404


async def test_another_organizations_paper_is_invisible(client, tutor, past_paper):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-pp@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    assert (await client.get("/api/v1/past-papers", headers=headers)).json() == []
    assert (
        await client.get(f"/api/v1/past-papers/{past_paper['id']}", headers=headers)
    ).status_code == 404


async def test_re_extraction_replaces_the_question_list(
    client,
    tutor,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    from app.services.extraction import extract_past_paper

    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    async with async_session() as session:
        await extract_past_paper(session, {"past_paper_id": past_paper["id"]})
        await session.commit()
    detail = await client.get(f"/api/v1/past-papers/{past_paper['id']}", headers=tutor["headers"])
    assert detail.json()["question_count"] == 2


async def test_a_tutor_can_review_and_finalize_a_past_paper_attempt(
    client,
    tutor,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The tutor's whole review path — open, override, finalize — works on a
    past paper without a single past-paper-specific screen."""
    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        _marking_double(fake_ai, confidence="low"),
    )
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True

    queue = (await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])).json()
    sid = queue[0]["submission_id"]
    assert queue[0]["past_paper_id"] == past_paper["id"]
    assert queue[0]["assignment_id"] is None
    assert (
        queue[0]["assignment_title"]
        == "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice November 2026"
    )

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    assert detail.status_code == 200, detail.text
    marks = detail.json()["marks"]
    assert len(marks) == 2
    assert all(m["needs_review"] for m in marks)

    save = await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[
            {"question_id": marks[0]["question_id"], "final_marks": 2},
            {"question_id": marks[1]["question_id"], "final_marks": 4},
        ],
        headers=tutor["headers"],
    )
    assert save.status_code == 200, save.text
    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200, final.text

    async with async_session() as session:
        attempt = await session.scalar(select(PastPaperAttempt))
        assert attempt.raw_marks == 6
    assert (
        await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])
    ).json() == []


async def test_relogging_a_paper_moves_it_back_up_the_review_queue(client, student, past_paper):
    """Re-logging replaces the attempt, so the clock restarts with it.

    The review queue orders by `submitted_at`. Keeping the first attempt's
    timestamp buries a replacement below work the tutor has already seen — it
    sorts as though the student never came back to it. Homework had always got
    this right and the past-paper copy of the same block had not, which is why
    all three arms now share `services/attempts.open_attempt`.
    """
    first = await _log_attempt(client, student, past_paper["id"])
    assert first.status_code in (200, 201), first.text
    async with async_session() as session:
        before = (
            await session.scalar(
                select(Submission).where(Submission.past_paper_id == past_paper["id"])
            )
        ).submitted_at

    again = await _log_attempt(client, student, past_paper["id"])
    assert again.status_code in (200, 201), again.text
    async with async_session() as session:
        rows = (
            await session.scalars(
                select(Submission).where(Submission.past_paper_id == past_paper["id"])
            )
        ).all()
    # Replaced, not appended — one attempt per student per paper.
    assert len(rows) == 1
    assert rows[0].submitted_at > before


async def test_an_overlong_extracted_name_is_clamped_not_left_to_fail_on_postgres(
    client, tutor, subject, monkeypatch, fake_ai
):
    """Nothing bounds what a model reads off a document, and the columns do.

    `title` is String(255), `session_label` 64, `paper_number` 32. SQLite does
    not enforce VARCHAR length, so an over-long value passes every test here and
    raises only on Postgres — and not cleanly: the assignment is flushed inside
    the question loop, which aborts the transaction, so the `commit()` that
    would have recorded `extraction_error` for the tutor fails too and the paper
    sits "Untitled paper" with nothing explaining why. This test pins the clamp
    rather than the symptom, because the symptom is invisible on SQLite
    (`RISK-3`).
    """
    from app.services.extraction import ExtractedQuestion, PastPaperExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        fake_ai(
            PastPaperExtractionResult(
                title="T" * 400,
                session_label="S" * 200,
                paper_number="P" * 100,
                questions=[
                    ExtractedQuestion(
                        number="1",
                        text_summary="Define an isotope",
                        max_marks=2,
                        topic_codes=[],
                        has_mark_scheme=False,
                    )
                ],
            )
        ),
    )
    created = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"])},
        files={
            "booklet": ("paper.pdf", PDF_BYTES, "application/pdf"),
            "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
        },
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text
    assert await process_one_job() is True

    async with async_session() as session:
        paper = await session.get(PastPaper, created.json()["id"])
        assert len(paper.title) == 255
        assert len(paper.session_label) == 64
        assert len(paper.paper_number) == 32


async def test_a_failed_extraction_leaves_the_paper_unnamed_and_says_why(
    client,
    tutor,
    subject,  # noqa: F811
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The title is assigned only after the empty-questions check, and this
    pins that ordering.

    Getting it wrong is not obvious: a paper the model could not read would be
    stamped with whatever it guessed the title was, and the tutor would see a
    confident name on a paper with no questions behind it — a `PROD-1` problem
    (a value with nothing traceable under it) presented as success. Until the
    AI reads it, an unread paper is `display_title` "Untitled paper" and a
    recorded reason, which is `PROD-2`: absent data shown as absent.
    """
    from app.services.extraction import ExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete", fake_ai(ExtractionResult(questions=[]))
    )
    created = await _upload(client, tutor, subject)
    assert created.status_code == 201, created.text
    await process_one_job()

    async with async_session() as session:
        paper = await session.get(PastPaper, created.json()["id"])
        assert paper.title is None
        assert paper.session_label is None
        assert paper.paper_number is None
        assert paper.display_title == "Untitled paper"
        assert "No questions were found" in paper.extraction_error


async def test_re_extraction_never_renames_a_paper_that_already_has_a_name(
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """A paper is named once, on the run that first names it, and never again.

    The second run here returns a *different* name, which is the only way to
    tell the guard apart from a plain overwrite — feeding the same fixture twice
    passes either way and pins nothing.

    Why the guard exists is task 3.5: a booklet's papers are named by the AI,
    corrected by the tutor, and only then do their question lists get extracted.
    That second job lands on this same code and would overwrite the tutor's
    correction with a fresh read — of a file holding a dozen papers, so
    frequently wrong as well as unwanted, and with no audit row. `PROD-7` gives
    the tutor final authority over what the AI produces, and `mark_submission`
    already takes this posture: it never overwrites a tutor-finalized mark.
    """
    from app.services.extraction import (
        ExtractedQuestion,
        PastPaperExtractionResult,
        extract_past_paper,
    )

    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        fake_ai(
            PastPaperExtractionResult(
                title="A completely different paper",
                session_label="June 2025",
                paper_number="Paper 9",
                questions=[
                    ExtractedQuestion(
                        number="1",
                        text_summary="Define an isotope",
                        max_marks=2,
                        topic_codes=[],
                        has_mark_scheme=False,
                    )
                ],
            )
        ),
    )
    async with async_session() as session:
        await extract_past_paper(session, {"past_paper_id": past_paper["id"]})
        await session.commit()
        paper = await session.get(PastPaper, past_paper["id"])
        assert paper.title == (
            "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice November 2026"
        )
        assert paper.session_label == "November 2026"
        assert paper.paper_number == "Paper 2"
        # Only the name is sticky. The question list is still replaced, which
        # is what keeps this from reading as "re-extraction does nothing":
        # the fixture extracted two questions, this run returned one.
        rows = (
            await session.scalars(
                select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper["id"])
            )
        ).all()
        assert len(rows) == 1


async def test_re_extraction_leaves_a_marked_question_list_alone(
    client,
    student,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The past-paper half of the same guard — see the mock arm's twin.

    Skipping only the delete lets extraction insert a second question list
    beside the first, so the paper ends up holding every question twice. The
    handler has to abandon the job outright.
    """
    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        _marking_double(fake_ai, confidence="low"),
    )
    await _log_attempt(client, student, past_paper["id"])
    assert await process_one_job() is True  # marking, which writes QuestionMarks

    from app.services.extraction import extract_past_paper

    async with async_session() as session:
        before = (
            await session.scalars(
                select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper["id"])
            )
        ).all()
        assert len(before) == 2
        # No AI double installed: reaching the model would mean the guard let
        # the job through, and the call would fail this test loudly.
        await extract_past_paper(session, {"past_paper_id": past_paper["id"]})
        await session.commit()
        after = (
            await session.scalars(
                select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper["id"])
            )
        ).all()
        assert [q.id for q in after] == [q.id for q in before]
