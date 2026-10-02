"""WS4: past papers — tutor uploads once, students self-log attempts, and the
whole thing rides the homework marking pipeline."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import (
    AssessableWork,
    Booklet,
    BookletStatus,
    Evidence,
    EvidenceSource,
    Job,
    JobStatus,
    Mistake,
    MistakeSource,
    MistakeTopic,
    PastPaper,
    PastPaperAttempt,
    PastPaperQuestion,
    QuestionMark,
    Submission,
    SubmissionStatus,
    Topic,
    User,
    UserRole,
    WorkKind,
)
from app.security import create_access_token, hash_password
from app.services import storage
from app.services.submission_kind import PAST_PAPER, kind_of
from app.services.work import create_work, parent_of
from app.workers.jobs import JOB_STALL_SECONDS, process_one_job
from tests.conftest import PDF_BYTES, PNG_BYTES
from tests.factories import make_mistake_category, make_past_paper, subject_defaults
from tests.test_admin_org_scope import _admin_headers


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
    files = [("paper", ("paper.pdf", PDF_BYTES, "application/pdf"))]
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


async def test_a_paper_uploads_without_a_mark_scheme(client, tutor, subject):  # noqa: F811
    """The mark scheme is no longer required (it was a 422 until the product
    owner reversed it). The three mark_scheme columns stay NULL — nothing is
    invented to fill them (`PROD-2`)."""
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 201, resp.text
    assert resp.json()["mark_scheme_name"] is None
    async with async_session() as session:
        paper = await session.scalar(select(PastPaper))
        assert paper.mark_scheme_path is None
        assert paper.mark_scheme_name is None
        assert paper.mark_scheme_mime is None
    # Nothing to serve, and the tutor is told that rather than getting a 500.
    scheme = await client.get(
        f"/api/v1/past-papers/{resp.json()['id']}/mark-scheme", headers=tutor["headers"]
    )
    assert scheme.status_code == 404


async def test_a_single_upload_becomes_a_booklet_of_one(client, tutor, subject):  # noqa: F811
    """Every past paper belongs to a booklet (task 3.5), so a tutor uploading
    one paper gets a booklet holding just it.

    It is `applied` on arrival and carries no draft: there is no list of papers
    to read off a single file and nothing for the tutor to review, so the
    extract-then-review screen a multi-paper booklet goes through is skipped.
    That is what keeps a single upload behaving exactly as it did before
    booklets existed."""
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 201, resp.text

    async with async_session() as session:
        paper = await session.scalar(select(PastPaper))
        booklet = await session.get(Booklet, paper.booklet_id)
        assert booklet is not None
        assert booklet.status == BookletStatus.applied
        assert booklet.draft is None
        # Read off the document by extraction, never typed — absent until then.
        assert booklet.title is None
        assert booklet.display_title == "Untitled booklet"
        # Same tenant and subject as its paper: a booklet is not a way to reach
        # across organizations (`PROD-3`, `SEC-7`).
        assert booklet.organization_id == paper.organization_id
        assert booklet.subject_id == paper.subject_id
        assert booklet.tutor_id == paper.tutor_id
        # The booklet records what arrived; the paper records what gets marked.
        # For a booklet of one they are the same file.
        assert booklet.file_path == paper.paper_path
        # Exactly one booklet, not one per request or one per question.
        assert len((await session.scalars(select(Booklet))).all()) == 1


async def test_a_booklet_cannot_hold_two_papers_at_the_same_index(
    client,
    tutor,
    subject,  # noqa: F811
):
    """The key that makes approving a booklet safe to re-run (`BE-6`).

    A worker that dies mid-approve is requeued and meets a booklet whose papers
    it already part-created. Without this constraint the re-run inserts them
    again; with it the second insert collides and the handler can skip. Proven
    here rather than assumed, because nothing exercises it until spec 7 and a
    missing constraint would look exactly like a working one until then."""
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 201, resp.text

    async with async_session() as session:
        paper = await session.scalar(select(PastPaper))
        assert paper.booklet_index == 1
        # The whole document, not a slice — nothing invented (`PROD-2`).
        assert paper.first_page is None
        assert paper.last_page is None

        work = await create_work(
            session,
            kind=WorkKind.past_paper,
            organization_id=paper.organization_id,
            subject_id=paper.subject_id,
            title=None,
        )
        session.add(
            PastPaper(
                organization_id=paper.organization_id,
                booklet_id=paper.booklet_id,
                subject_id=paper.subject_id,
                booklet_index=1,
                work_id=work.id,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_a_failed_upload_leaves_no_orphaned_files(
    client,
    tutor,
    subject,
    monkeypatch,  # noqa: F811
):
    """Files are written to disk before any row exists, so a failure after that
    point owns their cleanup — a stored object with no row pointing at it is
    invisible and can never be found again (`api/mocks.py:_discard`).

    The failure is forced at `enqueue`, which is the last step before the
    commit and the one with a row already flushed behind it."""

    async def _explode(*args, **kwargs):
        raise RuntimeError("queue is down")

    monkeypatch.setattr("app.api.past_papers.enqueue", _explode)

    # Watch the two storage calls rather than the upload directory itself: the
    # suite runs against a shared directory, so a filesystem diff would depend
    # on what every other test left there.
    saved: list[str] = []
    deleted: list[str] = []
    real_save = storage.save_upload
    real_delete = storage.delete_file

    async def _save(*args, **kwargs):
        result = await real_save(*args, **kwargs)
        saved.append(result[0])
        return result

    async def _delete(path, *args, **kwargs):
        deleted.append(path)
        return await real_delete(path, *args, **kwargs)

    monkeypatch.setattr(storage, "save_upload", _save)
    monkeypatch.setattr(storage, "delete_file", _delete)

    with pytest.raises(RuntimeError):
        await _upload(client, tutor, subject)

    # Both files — the paper and its mark scheme — not just the last one.
    assert saved, "the test proves nothing if nothing was stored"
    assert set(deleted) == set(saved), f"orphaned files left behind: {set(saved) - set(deleted)}"

    async with async_session() as session:
        assert await session.scalar(select(PastPaper)) is None
        assert await session.scalar(select(Booklet)) is None


async def test_a_rejected_mark_scheme_takes_the_paper_file_with_it(
    client,
    tutor,
    subject,
    monkeypatch,  # noqa: F811
):
    """The mark scheme is validated after the paper is already stored.

    A tutor who picks the wrong second file gets a 415 and retries; without
    this the first upload's file is left on disk with no row pointing at it,
    once per retry."""
    deleted: list[str] = []
    real_delete = storage.delete_file

    async def _delete(path, *args, **kwargs):
        deleted.append(path)
        return await real_delete(path, *args, **kwargs)

    monkeypatch.setattr(storage, "delete_file", _delete)

    resp = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"]), "duration_minutes": "90"},
        files=[
            ("paper", ("paper.pdf", PDF_BYTES, "application/pdf")),
            # PNG bytes claiming to be a PDF — rejected by the magic-byte check
            # (`SEC-15`), which runs after the paper is on disk.
            ("mark_scheme", ("ms.pdf", PNG_BYTES, "application/pdf")),
        ],
        headers=tutor["headers"],
    )
    assert resp.status_code == 415, resp.text
    assert len(deleted) == 1, f"the stored paper was not cleaned up: {deleted}"

    async with async_session() as session:
        assert await session.scalar(select(PastPaper)) is None
        assert await session.scalar(select(Booklet)) is None


async def test_a_student_learns_nothing_from_the_mark_scheme_route(
    client,
    tutor,
    subject,
    student,  # noqa: F811
):
    """A mark scheme is tutor-only, and the gate is `TutorUser` in the
    signature (`BE-17`, `SEC-11`), so it refuses before any lookup runs.

    That is why the 403 here is not the `API-7` leak it looks like: the answer
    is identical for a real paper and an invented id, so a student cannot probe
    which ids exist. The assertion is on that equality rather than on the
    number — a handler that looked the paper up and *then* checked the role
    would satisfy a 403-only test while leaking existence."""
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 201, resp.text
    real_id = resp.json()["id"]

    real = await client.get(
        f"/api/v1/past-papers/{real_id}/mark-scheme", headers=student["headers"]
    )
    invented = await client.get(
        f"/api/v1/past-papers/{real_id + 9999}/mark-scheme", headers=student["headers"]
    )
    assert real.status_code == invented.status_code
    assert real.json() == invented.json()

    # The tutor, who may see it, is told plainly that there is none.
    tutor_resp = await client.get(
        f"/api/v1/past-papers/{real_id}/mark-scheme", headers=tutor["headers"]
    )
    assert tutor_resp.status_code == 404


async def test_without_a_mark_scheme_nothing_auto_finalizes(
    client,
    tutor,
    student,
    subject,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The negative case the dropped 422 now rests on (`QA-12`).

    Marking still runs and still drafts a mark per question, but with no scheme
    file in front of the model `scheme_backed()` is false for every question, so
    AI-11/ADR-0009 lets none of them finalize — even at `high` confidence, which
    is exactly what this double returns. Every mark waits for the tutor.
    """
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await _upload(client, tutor, subject, with_scheme=False)
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True  # extraction

    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    assert (await _log_attempt(client, student, resp.json()["id"])).status_code == 201
    assert await process_one_job() is True  # marking

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.needs_review
        marks = (await session.scalars(select(QuestionMark))).all()
        assert len(marks) == 2, "the paper is still marked — only finalizing is withheld"
        assert all(m.ai_marks is not None for m in marks), "the AI still proposed a number"
        assert all(m.needs_review for m in marks)
        assert not any(m.auto_finalized for m in marks)
        assert all(m.final_marks is None for m in marks)
    # And nothing counted: an unfinalized mark is not Evidence (`PROD-5`).
    async with async_session() as session:
        assert (await session.scalars(select(Evidence))).all() == []


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
            ("paper", ("paper.pdf", PDF_BYTES, "application/pdf")),
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


async def test_a_student_can_read_the_paper_but_never_the_mark_scheme(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    paper = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/paper", headers=student["headers"]
    )
    assert paper.status_code == 200
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
        assert kind_of(submission) is PAST_PAPER
        assert (await parent_of(session, submission)).id == past_paper["id"]
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
            ("paper", ("p.pdf", PDF_BYTES, "application/pdf")),
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
        paper = await session.get(PastPaper, past_paper["id"])
        before = (
            await session.scalar(select(Submission).where(Submission.work_id == paper.work_id))
        ).submitted_at

    again = await _log_attempt(client, student, past_paper["id"])
    assert again.status_code in (200, 201), again.text
    async with async_session() as session:
        paper = await session.get(PastPaper, past_paper["id"])
        rows = (
            await session.scalars(select(Submission).where(Submission.work_id == paper.work_id))
        ).all()
    # Replaced, not appended — one attempt per student per paper.
    assert len(rows) == 1
    assert rows[0].submitted_at > before


async def test_replacing_an_attempt_clears_its_mistakes_and_the_analysed_mark(
    client, student, past_paper
):
    """A replacement is the whole answer again, so the mistakes tagged on the
    previous answer go with the marks they describe.

    Left behind, a Mistake row points at a QuestionMark being deleted — an
    orphan its foreign key does not cascade away — and `mistakes_analysed_at`
    would still say the submission had been examined, so the replacement's
    fresh marks would count as already looked at (PROD-2)."""
    assert (await _log_attempt(client, student, past_paper["id"])).status_code in (200, 201)

    async with async_session() as session:
        paper = await session.get(PastPaper, past_paper["id"])
        submission = await session.scalar(
            select(Submission).where(Submission.work_id == paper.work_id)
        )
        question = await session.scalar(
            select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == paper.id)
        )
        mark = QuestionMark(
            submission_id=submission.id,
            past_paper_question_id=question.id,
            final_marks=3,
        )
        session.add(mark)
        await session.flush()
        mistake_category = await make_mistake_category(
            session, organization_id=paper.organization_id, subject_id=paper.subject_id
        )
        mistake = Mistake(
            student_id=submission.student_id,
            question_mark_id=mark.id,
            category_id=mistake_category.id,
            severity=2,
            source=MistakeSource.ai,
        )
        session.add(mistake)
        await session.flush()
        topic = await session.scalar(select(Topic).where(Topic.subject_id == paper.subject_id))
        session.add(MistakeTopic(mistake_id=mistake.id, topic_id=topic.id))
        submission.mistakes_analysed_at = submission.submitted_at
        await session.commit()

    assert (await _log_attempt(client, student, past_paper["id"])).status_code in (200, 201)

    async with async_session() as session:
        paper = await session.get(PastPaper, past_paper["id"])
        submission = await session.scalar(
            select(Submission).where(Submission.work_id == paper.work_id)
        )
        assert submission.mistakes_analysed_at is None
        assert (await session.scalars(select(Mistake))).all() == []
        # And the topic links go with them. `mistake_topics.mistake_id` has no
        # cascade either, so a link left behind points at a mistake that no
        # longer exists — and the suite runs SQLite with foreign keys off, so
        # nothing here or in CI would raise (RISK-3). 4.4's topic rollups read
        # these rows, and an orphan is a mistake counted against a topic for an
        # answer the student has already replaced.
        assert (await session.scalars(select(MistakeTopic))).all() == []


async def test_an_attempt_joins_the_paper_it_answers_rather_than_making_a_second_one(
    client, student, past_paper
):
    """A submission answers work that already exists, so it takes that work's
    parent row. Creating a fresh one instead would give the same paper two
    identities, and every count that goes through the parent would see two
    pieces of work where the student uploaded one."""
    assert (await _log_attempt(client, student, past_paper["id"])).status_code in (200, 201)
    async with async_session() as session:
        paper = await session.get(PastPaper, past_paper["id"])
        submission = await session.scalar(
            select(Submission).where(Submission.work_id == paper.work_id)
        )
        assert submission.work_id == paper.work_id
        parents = (
            await session.scalars(
                select(AssessableWork).where(AssessableWork.kind == WorkKind.past_paper)
            )
        ).all()
    assert [p.id for p in parents] == [paper.work_id]


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
            "paper": ("paper.pdf", PDF_BYTES, "application/pdf"),
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

    Why the guard exists is task 3.5: an upload's papers are named by the AI,
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
        # The `past_paper` fixture's extraction double is still patched in, so a
        # regressed guard would quietly succeed rather than fail on the model
        # call. The id comparison below is what catches it.
        await extract_past_paper(session, {"past_paper_id": past_paper["id"]})
        await session.commit()
        after = (
            await session.scalars(
                select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper["id"])
            )
        ).all()
        assert [q.id for q in after] == [q.id for q in before]


# --- An unreadable paper is the tutor's to check and fix ---------------------
#
# Owner decision, 2026-10-02: a past paper the AI could not read goes on the
# tutor's to-do list, and the shelf offers the fix — read it again, or swap in
# a clearer copy. Students keep the paper throughout (`hide_past_paper`), so
# anyone who already sent answers is marked once it has been read.


def _fail_extraction(monkeypatch, fake_ai):
    from app.services.extraction import ExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete", fake_ai(ExtractionResult(questions=[]))
    )


@pytest.fixture
async def unreadable_paper(client, tutor, subject, monkeypatch, fake_ai):  # noqa: F811
    _fail_extraction(monkeypatch, fake_ai)
    created = await _upload(client, tutor, subject)
    assert created.status_code == 201, created.text
    assert await process_one_job() is True  # extraction, which fails
    async with async_session() as session:
        paper = await session.get(PastPaper, created.json()["id"])
        assert paper.extraction_error
    return created.json()


async def _attention(client, headers) -> list[dict]:
    resp = await client.get("/api/v1/assignments/attention", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _items_for(items: list[dict], paper_id: int) -> list[dict]:
    return [item for item in items if item["past_paper_id"] == paper_id]


async def _other_tutor_headers(client) -> dict:
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-shelf@example.com", "password": "password123"},
    )
    assert other.status_code == 201, other.text
    return {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}


def _clearer_copy(content: bytes = PDF_BYTES) -> list:
    return [("paper", ("clearer.pdf", content, "application/pdf"))]


async def test_an_unreadable_paper_goes_on_the_tutors_to_do_list(client, tutor, unreadable_paper):
    [item] = _items_for(await _attention(client, tutor["headers"]), unreadable_paper["id"])
    assert item["reason"] == "extraction_failed"
    assert item["assignment_id"] is None
    assert item["submission_id"] is None
    # Unread means unnamed, so the tutor is shown the file they uploaded rather
    # than one more "Untitled paper" — their own metadata, nothing invented.
    assert item["assignment_title"] == "paper.pdf"
    assert "No questions were found" in item["detail"]


async def test_a_paper_that_was_read_is_not_on_the_to_do_list(client, tutor, past_paper):
    assert _items_for(await _attention(client, tutor["headers"]), past_paper["id"]) == []


async def test_a_paper_taken_off_the_shelf_leaves_the_to_do_list(client, tutor, unreadable_paper):
    removed = await client.delete(
        f"/api/v1/past-papers/{unreadable_paper['id']}", headers=tutor["headers"]
    )
    assert removed.status_code == 204
    assert _items_for(await _attention(client, tutor["headers"]), unreadable_paper["id"]) == []


async def test_another_organizations_unreadable_paper_never_reaches_my_list(
    client, unreadable_paper
):
    """QA-12's negative case: the list is the reader's own organization's,
    admins included (`SEC-7`)."""
    other = await _other_tutor_headers(client)
    assert _items_for(await _attention(client, other), unreadable_paper["id"]) == []
    foreign_admin = await _admin_headers()
    assert _items_for(await _attention(client, foreign_admin), unreadable_paper["id"]) == []


async def test_an_admin_sees_an_unreadable_paper_and_a_colleague_does_not(client, unreadable_paper):
    """The homework rule, applied to papers: the to-do belongs to the tutor who
    uploaded it, and an admin oversees their whole organization."""
    async with async_session() as session:
        org_id = (await session.get(PastPaper, unreadable_paper["id"])).organization_id
        colleague = User(
            email="colleague@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.tutor,
            name="Colleague",
            organization_id=org_id,
        )
        session.add(colleague)
        await session.commit()
        colleague_headers = {
            "Authorization": f"Bearer {create_access_token(colleague.id, colleague.token_version)}"
        }
    admin = await _admin_headers(org_id)
    assert len(_items_for(await _attention(client, admin), unreadable_paper["id"])) == 1
    assert _items_for(await _attention(client, colleague_headers), unreadable_paper["id"]) == []


async def test_trying_again_reads_the_paper_and_takes_it_off_the_list(
    client,
    tutor,
    unreadable_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await client.post(
        f"/api/v1/past-papers/{unreadable_paper['id']}/retry-extraction",
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["extraction_error"] is None
    # Off the list as soon as the read is under way — the shelf shows it being
    # read — rather than once it lands.
    assert _items_for(await _attention(client, tutor["headers"]), unreadable_paper["id"]) == []

    assert await process_one_job() is True
    detail = await client.get(
        f"/api/v1/past-papers/{unreadable_paper['id']}", headers=tutor["headers"]
    )
    assert detail.json()["question_count"] == 2
    assert detail.json()["display_title"].startswith("Cambridge IGCSE Chemistry")


async def test_trying_again_brings_the_waiting_retry_forward_instead_of_reading_twice(
    client, tutor, unreadable_paper
):
    """The failed read already has its one automatic retry waiting a minute out,
    and a tutor pressing "Try again" is usually inside that minute. A second job
    beside it would read — and bill — the same paper twice."""
    resp = await client.post(
        f"/api/v1/past-papers/{unreadable_paper['id']}/retry-extraction",
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        [job] = (
            await session.scalars(
                select(Job).where(Job.type == "extract_past_paper", Job.status == JobStatus.pending)
            )
        ).all()
        assert job.run_after is None  # due now, not in a minute
        assert job.attempts == 0  # a fresh read, with its own retry to come


async def test_trying_again_after_the_retries_ran_out_queues_a_new_read(
    client, tutor, unreadable_paper
):
    async with async_session() as session:
        for job in (await session.scalars(select(Job))).all():
            job.status = JobStatus.failed
        await session.commit()
    resp = await client.post(
        f"/api/v1/past-papers/{unreadable_paper['id']}/retry-extraction",
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        pending = (await session.scalars(select(Job).where(Job.status == JobStatus.pending))).all()
        assert [job.payload for job in pending] == [{"past_paper_id": unreadable_paper["id"]}]


async def test_a_paper_that_was_read_cannot_be_read_again_or_replaced(client, tutor, past_paper):
    """Its questions may already carry marks, and a new file under them would
    leave those marks scored against a paper nobody can open."""
    retry = await client.post(
        f"/api/v1/past-papers/{past_paper['id']}/retry-extraction", headers=tutor["headers"]
    )
    assert retry.status_code == 409
    replace = await client.put(
        f"/api/v1/past-papers/{past_paper['id']}/paper",
        files=_clearer_copy(),
        headers=tutor["headers"],
    )
    assert replace.status_code == 409


async def test_a_paper_still_being_read_is_not_read_a_second_time(client, tutor, subject):
    created = await _upload(client, tutor, subject)
    resp = await client.post(
        f"/api/v1/past-papers/{created.json()['id']}/retry-extraction", headers=tutor["headers"]
    )
    assert resp.status_code == 409


async def test_another_organization_cannot_fix_a_paper(client, unreadable_paper):
    """QA-12: a 404, not a 403 — the id is enumerable (`API-7`) — and the paper
    is left exactly as it was."""
    other = await _other_tutor_headers(client)
    paper_id = unreadable_paper["id"]
    retry = await client.post(f"/api/v1/past-papers/{paper_id}/retry-extraction", headers=other)
    assert retry.status_code == 404
    replace = await client.put(
        f"/api/v1/past-papers/{paper_id}/paper", files=_clearer_copy(), headers=other
    )
    assert replace.status_code == 404
    async with async_session() as session:
        paper = await session.get(PastPaper, paper_id)
        assert paper.extraction_error
        assert paper.paper_name == "paper.pdf"


async def test_a_student_cannot_fix_a_paper(client, student, unreadable_paper):
    paper_id = unreadable_paper["id"]
    retry = await client.post(
        f"/api/v1/past-papers/{paper_id}/retry-extraction", headers=student["headers"]
    )
    assert retry.status_code == 403
    replace = await client.put(
        f"/api/v1/past-papers/{paper_id}/paper", files=_clearer_copy(), headers=student["headers"]
    )
    assert replace.status_code == 403


async def test_a_clearer_copy_replaces_the_unreadable_one_and_is_read(
    client,
    tutor,
    unreadable_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    deleted: list[str] = []
    real_delete = storage.delete_file

    async def _delete(path, *args, **kwargs):
        deleted.append(path)
        return await real_delete(path, *args, **kwargs)

    monkeypatch.setattr(storage, "delete_file", _delete)
    async with async_session() as session:
        original = (await session.get(PastPaper, unreadable_paper["id"])).paper_path

    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await client.put(
        f"/api/v1/past-papers/{unreadable_paper['id']}/paper",
        files=_clearer_copy(),
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["paper_name"] == "clearer.pdf"
    assert resp.json()["extraction_error"] is None

    assert await process_one_job() is True
    async with async_session() as session:
        paper = await session.get(PastPaper, unreadable_paper["id"])
        assert paper.paper_path != original
        assert paper.extraction_error is None
        questions = (
            await session.scalars(
                select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == paper.id)
            )
        ).all()
        assert len(questions) == 2
    # A booklet of one shares its file with its paper; the booklet still
    # records what arrived, so the original is kept.
    assert deleted == []


async def _unreadable_slice(tutor, subject, **extra) -> int:
    """An unreadable paper cut from a larger booklet: it owns its slice file,
    which the booklet (holding the whole upload) does not point at."""
    async with async_session() as session:
        tutor_user = await session.get(User, tutor["user"]["id"])
        booklet = Booklet(
            organization_id=tutor_user.organization_id,
            tutor_id=tutor_user.id,
            subject_id=subject["id"],
            status=BookletStatus.applied,
            file_path="booklet.pdf",
            file_name="booklet.pdf",
            file_mime="application/pdf",
        )
        session.add(booklet)
        await session.flush()
        paper = await make_past_paper(
            session,
            organization_id=tutor_user.organization_id,
            subject_id=subject["id"],
            booklet=booklet,
            tutor_id=tutor_user.id,
            paper_path="slice-1.pdf",
            paper_name="booklet — Paper 1.pdf",
            paper_mime="application/pdf",
            extraction_error="No questions were found in the past paper",
            **extra,
        )
        await session.commit()
        return paper.id


async def test_replacing_a_paper_cut_from_a_booklet_deletes_the_old_slice(
    client,
    tutor,
    subject,
    monkeypatch,  # noqa: F811
):
    """A paper cut from a larger booklet owns its slice outright. Replaced and
    left on disk, nothing would point at it, so nothing could ever clean it up."""
    paper_id = await _unreadable_slice(tutor, subject, first_page=12, last_page=23)

    deleted: list[str] = []

    async def _delete(path, *args, **kwargs):
        deleted.append(path)

    monkeypatch.setattr(storage, "delete_file", _delete)
    resp = await client.put(
        f"/api/v1/past-papers/{paper_id}/paper", files=_clearer_copy(), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert deleted == ["slice-1.pdf"]
    # The new file is the whole paper, not pages 12-23 of the booklet, and the
    # row no longer claims it was (`PROD-1`).
    async with async_session() as session:
        replaced = await session.get(PastPaper, paper_id)
        assert replaced.first_page is None
        assert replaced.last_page is None


async def test_a_rejected_copy_leaves_the_paper_as_it_was(client, tutor, unreadable_paper):
    """PNG bytes claiming to be a PDF fail the magic-byte check (`SEC-15`)
    before anything is stored, and the paper stays unread and on the list."""
    resp = await client.put(
        f"/api/v1/past-papers/{unreadable_paper['id']}/paper",
        files=_clearer_copy(PNG_BYTES),
        headers=tutor["headers"],
    )
    assert resp.status_code == 415, resp.text
    async with async_session() as session:
        paper = await session.get(PastPaper, unreadable_paper["id"])
        assert paper.extraction_error
        assert paper.paper_name == "paper.pdf"
    assert len(_items_for(await _attention(client, tutor["headers"]), unreadable_paper["id"])) == 1


async def test_a_copy_that_cannot_be_queued_takes_its_file_with_it(
    client,
    tutor,
    unreadable_paper,
    monkeypatch,  # noqa: F811
):
    """The new file is on disk before the read is queued; a failure there owns
    its cleanup, as `upload_past_paper`'s does."""

    async def _explode(*args, **kwargs):
        raise RuntimeError("queue is down")

    monkeypatch.setattr("app.api.past_papers.queue_past_paper_read", _explode)
    saved: list[str] = []
    deleted: list[str] = []
    real_save = storage.save_upload
    real_delete = storage.delete_file

    async def _save(*args, **kwargs):
        result = await real_save(*args, **kwargs)
        saved.append(result[0])
        return result

    async def _delete(path, *args, **kwargs):
        deleted.append(path)
        return await real_delete(path, *args, **kwargs)

    monkeypatch.setattr(storage, "save_upload", _save)
    monkeypatch.setattr(storage, "delete_file", _delete)

    with pytest.raises(RuntimeError):
        await client.put(
            f"/api/v1/past-papers/{unreadable_paper['id']}/paper",
            files=_clearer_copy(),
            headers=tutor["headers"],
        )
    assert saved, "the test proves nothing if nothing was stored"
    assert deleted == saved
    async with async_session() as session:
        paper = await session.get(PastPaper, unreadable_paper["id"])
        assert paper.extraction_error
        assert paper.paper_name == "paper.pdf"


async def test_answers_sent_before_the_paper_could_be_read_are_marked_once_it_is(
    client,
    tutor,
    student,
    unreadable_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The paper stays on the student's list while it is unreadable, so answers
    can arrive for it. Marking them fails for want of questions, and nothing
    else would ever try again — the paper being read is what they wait for."""
    resp = await _log_attempt(client, student, unreadable_paper["id"])
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True  # marking, with no questions to mark
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.ai_failed

    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    fixed = await client.post(
        f"/api/v1/past-papers/{unreadable_paper['id']}/retry-extraction",
        headers=tutor["headers"],
    )
    assert fixed.status_code == 200, fixed.text
    assert await process_one_job() is True  # the read

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.submitted
        assert submission.ai_error is None
        # One marking job: the failed marking's own retry, brought forward.
        marking = (
            await session.scalars(
                select(Job).where(Job.type == "mark_submission", Job.status == JobStatus.pending)
            )
        ).all()
        assert len(marking) == 1
        assert marking[0].run_after is None

    assert await process_one_job() is True  # the marking
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.auto_finalized


async def test_each_question_says_which_topics_it_counts_towards(
    client, tutor, subject, past_paper
):
    """Past-paper marks feed the student's topic scores through these tags, so
    the tutor can see them (`PROD-1`)."""
    detail = await client.get(f"/api/v1/past-papers/{past_paper['id']}", headers=tutor["headers"])
    topics = {q["number"]: [t["title"] for t in q["topics"]] for q in detail.json()["questions"]}
    assert topics == {"1": ["Atomic structure"], "2": ["Ionic bonding"]}


async def test_a_question_classified_under_no_topic_says_so(
    client,
    tutor,
    subject,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    from app.services.extraction import ExtractedQuestion, PastPaperExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        fake_ai(
            PastPaperExtractionResult(
                title="Cambridge IGCSE Chemistry 0620/41",
                session_label="November 2026",
                paper_number="Paper 4",
                questions=[
                    ExtractedQuestion(
                        number="1",
                        text_summary="A question on no syllabus topic the subject has",
                        max_marks=3,
                        topic_codes=["9.9"],
                        has_mark_scheme=True,
                    )
                ],
            )
        ),
    )
    created = await _upload(client, tutor, subject)
    assert await process_one_job() is True
    detail = await client.get(
        f"/api/v1/past-papers/{created.json()['id']}", headers=tutor["headers"]
    )
    [question] = detail.json()["questions"]
    assert question["topics"] == []


async def test_a_re_read_that_fails_in_the_database_still_says_why(
    client,
    tutor,
    unreadable_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Two questions read with the same number break the paper's unique
    (past_paper_id, number) at flush. Committing the reason on top of that
    failed too, and since a fix clears the reason before it queues the read,
    the paper was stranded "being read": off the to-do list, and refused by
    both fixes."""
    from app.services.extraction import ExtractedQuestion, PastPaperExtractionResult

    question = {"text_summary": "x", "max_marks": 2, "topic_codes": [], "has_mark_scheme": True}
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        fake_ai(
            PastPaperExtractionResult(
                title="T",
                session_label="S",
                paper_number="P",
                questions=[
                    ExtractedQuestion(number="1", **question),
                    ExtractedQuestion(number="1", **question),
                ],
            )
        ),
    )
    paper_id = unreadable_paper["id"]
    retry = await client.post(
        f"/api/v1/past-papers/{paper_id}/retry-extraction", headers=tutor["headers"]
    )
    assert retry.status_code == 200, retry.text
    assert await process_one_job() is True  # the read, failing at flush

    async with async_session() as session:
        paper = await session.get(PastPaper, paper_id)
        assert paper.extraction_error
    # Back on the to-do list, and fixable again.
    assert len(_items_for(await _attention(client, tutor["headers"]), paper_id)) == 1
    again = await client.post(
        f"/api/v1/past-papers/{paper_id}/retry-extraction", headers=tutor["headers"]
    )
    assert again.status_code == 200, again.text


async def test_a_topic_code_read_twice_is_one_tag_not_a_failed_read(
    client,
    tutor,
    subject,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    from app.services.extraction import ExtractedQuestion, PastPaperExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        fake_ai(
            PastPaperExtractionResult(
                title="Cambridge IGCSE Chemistry 0620/41",
                session_label="November 2026",
                paper_number="Paper 4",
                questions=[
                    ExtractedQuestion(
                        number="1",
                        text_summary="Define an isotope",
                        max_marks=2,
                        topic_codes=["1.3", "1.3"],
                        has_mark_scheme=True,
                    )
                ],
            )
        ),
    )
    created = await _upload(client, tutor, subject)
    assert await process_one_job() is True
    detail = await client.get(
        f"/api/v1/past-papers/{created.json()['id']}", headers=tutor["headers"]
    )
    assert detail.json()["extraction_error"] is None
    [question] = detail.json()["questions"]
    assert [t["code"] for t in question["topics"]] == ["1.3"]


async def test_a_retry_the_worker_already_claimed_is_queued_afresh(unreadable_paper):
    """Read, then written: between the two the worker can claim the waiting
    retry, and a running job has read the old state — on a replaced paper, the
    file about to be deleted. Bringing forward a job that is no longer waiting
    must queue a new one rather than rewrite the running one."""
    from app.services.extraction import _run_now

    payload = {"past_paper_id": unreadable_paper["id"]}
    async with async_session() as session:
        waiting = (await session.scalars(select(Job).where(Job.status == JobStatus.pending))).all()
        assert [job.payload for job in waiting] == [payload]
        # The worker's claim lands after the read above.
        claimed = waiting[0]
        claimed.status = JobStatus.running
        claimed.attempts = 2
        await session.commit()

        await _run_now(session, "extract_past_paper", [payload], waiting=waiting)
        await session.commit()

    async with async_session() as session:
        jobs = (await session.scalars(select(Job).order_by(Job.id))).all()
        running = [job for job in jobs if job.status == JobStatus.running]
        pending = [job for job in jobs if job.status == JobStatus.pending]
        assert [job.attempts for job in running] == [2]  # left alone
        assert [job.payload for job in pending] == [payload]  # queued afresh


async def test_a_storage_error_on_the_old_file_does_not_fail_the_replacement(
    client,
    tutor,
    subject,
    monkeypatch,  # noqa: F811
):
    """The replacement is committed before the old slice is deleted. A storage
    backend refusing that delete must not report the replacement as failed:
    the tutor would try again and be refused, the paper already being read."""
    paper_id = await _unreadable_slice(tutor, subject)

    async def _refuse(path, *args, **kwargs):
        raise RuntimeError("storage is down")

    monkeypatch.setattr(storage, "delete_file", _refuse)
    resp = await client.put(
        f"/api/v1/past-papers/{paper_id}/paper", files=_clearer_copy(), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["paper_name"] == "clearer.pdf"


async def test_a_very_long_file_name_is_kept_to_the_column(client, tutor, unreadable_paper):
    """The name is the client's own and unbounded; Postgres refuses a value
    longer than the column, which SQLite never would (`RISK-3`)."""
    long_name = "a" * 300 + ".pdf"
    resp = await client.put(
        f"/api/v1/past-papers/{unreadable_paper['id']}/paper",
        files=[("paper", (long_name, PDF_BYTES, "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        paper = await session.get(PastPaper, unreadable_paper["id"])
        assert len(paper.paper_name) == 255


async def test_a_fix_waits_for_a_read_already_running(client, tutor, unreadable_paper):
    """A running read holds the old file. A second read beside it could finish
    last and leave a replacement marked against the old copy's questions."""
    async with async_session() as session:
        [job] = (await session.scalars(select(Job))).all()
        job.status = JobStatus.running
        job.claimed_at = datetime.now(timezone.utc)
        await session.commit()
    paper_id = unreadable_paper["id"]
    retry = await client.post(
        f"/api/v1/past-papers/{paper_id}/retry-extraction", headers=tutor["headers"]
    )
    assert retry.status_code == 409
    replace = await client.put(
        f"/api/v1/past-papers/{paper_id}/paper", files=_clearer_copy(), headers=tutor["headers"]
    )
    assert replace.status_code == 409
    async with async_session() as session:
        assert (await session.get(PastPaper, paper_id)).paper_name == "paper.pdf"


async def test_a_read_its_dead_worker_left_running_does_not_block_a_fix(
    client, tutor, unreadable_paper
):
    """A worker killed mid-read leaves its job `running` until the orphan sweep,
    hours later. Past the stall threshold it is not a read in progress, and the
    tutor's fix goes ahead."""
    async with async_session() as session:
        [job] = (await session.scalars(select(Job))).all()
        job.status = JobStatus.running
        job.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=JOB_STALL_SECONDS + 60)
        await session.commit()
    retry = await client.post(
        f"/api/v1/past-papers/{unreadable_paper['id']}/retry-extraction",
        headers=tutor["headers"],
    )
    assert retry.status_code == 200, retry.text
