"""WS2: the auto-marking trust model — confident scheme-backed marks count
without a tutor, everything else queues for review, overrides are audited, and
a student can contest any mark that counted."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Evidence,
    MarkOverrideAudit,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    Submission,
    SubmissionStatus,
)
from app.workers.jobs import process_one_job
from tests.test_homework import (  # noqa: F401 - shared fixtures
    PNG_BYTES,
    classified,
    fake_extraction,
    group,
    published_assignment,
    student,
    subject,
)


@pytest.fixture
async def assignment_all_scheme(client, tutor, group, monkeypatch):  # noqa: F811
    """A published assignment whose questions all have mark-scheme coverage —
    the case that should need no tutor at all."""
    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "Fully covered homework"},
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
    return aid


def _confident_result(*, confidence="high"):
    from app.services.marking import MarkingResult, QuestionMarkDraft

    return MarkingResult(
        questions=[
            QuestionMarkDraft(
                number="1",
                transcription="Same protons, different neutrons.",
                proposed_marks=2,
                feedback="Correct.",
                confidence=confidence,
            ),
            QuestionMarkDraft(
                number="2",
                transcription="Electrostatic attraction between oppositely charged ions.",
                proposed_marks=3,
                feedback="Nearly — mention the transfer of electrons.",
                confidence=confidence,
            ),
        ]
    )


async def _submit(client, aid, student):  # noqa: F811
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True


async def test_confident_scheme_backed_marks_auto_finalize_with_no_tutor_action(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)

    subs = await client.get(
        f"/api/v1/assignments/{assignment_all_scheme}/submissions", headers=tutor["headers"]
    )
    assert subs.json()[0]["status"] == "auto_finalized"
    assert subs.json()[0]["total_final"] == 5

    # The student sees the marks immediately — no tutor step happened.
    view = await client.get(
        f"/api/v1/assignments/{assignment_all_scheme}/my-submission",
        headers=student["headers"],
    )
    assert view.json()["status"] == "marked"
    assert view.json()["total"] == 5

    # And nothing is waiting for the tutor.
    queue = await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])
    assert queue.json() == []


async def test_auto_finalized_marks_become_readiness_evidence(
    client, tutor, student, published_assignment, monkeypatch, fake_ai  # noqa: F811
):
    """The whole point: marks that count feed the Readiness Engine without
    waiting for a tutor who may never get to them."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1",
                        transcription="ok",
                        proposed_marks=2,
                        feedback="Good.",
                        confidence="high",
                    ),
                    QuestionMarkDraft(
                        number="2",
                        transcription="ok",
                        proposed_marks=3,
                        feedback="Good.",
                        confidence="high",
                    ),
                ]
            )
        ),
    )
    # published_assignment's Q2 has no mark scheme, so nothing settles yet.
    await _submit(client, published_assignment["id"], student)
    async with async_session() as session:
        assert (await session.scalar(select(Evidence))) is None

    # Tutor rules on the one unsure question -> finalize -> evidence appears.
    sid = (
        await client.get(
            f"/api/v1/assignments/{published_assignment['id']}/submissions",
            headers=tutor["headers"],
        )
    ).json()[0]["id"]
    detail = (await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])).json()
    unsure = next(m for m in detail["marks"] if m["needs_review"])
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": unsure["question_id"], "final_marks": 3}],
        headers=tutor["headers"],
    )
    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200, final.text

    async with async_session() as session:
        assert (await session.scalar(select(Evidence))) is not None


async def test_a_low_confidence_mark_goes_to_review_even_with_a_scheme(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(_confident_result(confidence="low")),
    )
    await _submit(client, assignment_all_scheme, student)

    queue = (
        await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])
    ).json()
    assert len(queue) == 1
    assert queue[0]["unsure_count"] == 2
    assert queue[0]["remark_request_count"] == 0
    assert queue[0]["student_name"] == "Sara"


async def test_a_no_scheme_question_is_marked_but_flagged_unsure(
    client, tutor, student, published_assignment, monkeypatch, fake_ai  # noqa: F811
):
    """The AI marks scheme-less questions from the syllabus rather than
    refusing — but the mark is a suggestion, not a result."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1", transcription="a", proposed_marks=2,
                        feedback="Good.", confidence="high",
                    ),
                    QuestionMarkDraft(
                        number="2", transcription="b", proposed_marks=3,
                        feedback="Reasonable.", confidence="unsure",
                    ),
                ]
            )
        ),
    )
    await _submit(client, published_assignment["id"], student)
    sid = (
        await client.get(
            f"/api/v1/assignments/{published_assignment['id']}/submissions",
            headers=tutor["headers"],
        )
    ).json()[0]["id"]
    marks = (
        await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    ).json()["marks"]
    no_scheme = next(m for m in marks if not m["has_mark_scheme"])
    assert no_scheme["ai_marks"] == 3, "the AI's suggestion is kept for the tutor"
    assert no_scheme["final_marks"] is None, "but it does not count on its own"
    assert no_scheme["needs_review"] is True


async def test_finalize_only_needs_the_unsure_questions_resolved(
    client, tutor, student, published_assignment, monkeypatch, fake_ai  # noqa: F811
):
    from app.services.marking import MarkingResult, QuestionMarkDraft

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1", transcription="a", proposed_marks=2,
                        feedback="Good.", confidence="high",
                    ),
                    QuestionMarkDraft(
                        number="2", transcription="b", proposed_marks=3,
                        feedback="Reasonable.", confidence="unsure",
                    ),
                ]
            )
        ),
    )
    await _submit(client, published_assignment["id"], student)
    sid = (
        await client.get(
            f"/api/v1/assignments/{published_assignment['id']}/submissions",
            headers=tutor["headers"],
        )
    ).json()[0]["id"]
    marks = (
        await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    ).json()["marks"]
    unsure = next(m for m in marks if m["needs_review"])

    # Only the unsure one is submitted — the confident one already has a mark.
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": unsure["question_id"], "final_marks": 2}],
        headers=tutor["headers"],
    )
    final = await client.post(f"/api/v1/submissions/{sid}/finalize", headers=tutor["headers"])
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "finalized"


async def test_overriding_a_mark_that_already_counted_is_audited(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)
    sid = (
        await client.get(
            f"/api/v1/assignments/{assignment_all_scheme}/submissions",
            headers=tutor["headers"],
        )
    ).json()[0]["id"]
    marks = (
        await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    ).json()["marks"]
    q1 = marks[0]
    assert q1["final_marks"] == 2

    resp = await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": q1["question_id"], "final_marks": 1}],
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text

    history = await client.get(
        f"/api/v1/submissions/{sid}/marks/{q1['question_id']}/history",
        headers=tutor["headers"],
    )
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 1
    assert entries[0]["old_marks"] == 2
    assert entries[0]["new_marks"] == 1
    assert entries[0]["changed_by_name"] == "Test Tutor"
    assert entries[0]["reason"] is None


async def test_setting_a_mark_for_the_first_time_is_not_an_override(
    client, tutor, student, published_assignment, monkeypatch, fake_ai  # noqa: F811
):
    from app.services.marking import MarkingResult, QuestionMarkDraft

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1", transcription="a", proposed_marks=2,
                        feedback="Good.", confidence="high",
                    ),
                    QuestionMarkDraft(
                        number="2", transcription="b", proposed_marks=3,
                        feedback="ok", confidence="unsure",
                    ),
                ]
            )
        ),
    )
    await _submit(client, published_assignment["id"], student)
    sid = (
        await client.get(
            f"/api/v1/assignments/{published_assignment['id']}/submissions",
            headers=tutor["headers"],
        )
    ).json()[0]["id"]
    marks = (
        await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    ).json()["marks"]
    unsure = next(m for m in marks if m["needs_review"])
    await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": unsure["question_id"], "final_marks": 3}],
        headers=tutor["headers"],
    )
    async with async_session() as session:
        assert (await session.scalar(select(MarkOverrideAudit))) is None


async def test_a_student_can_contest_an_auto_finalized_mark_once(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        sid = submission.id
        question_id = (
            await session.scalar(
                select(QuestionMark.question_id).where(QuestionMark.submission_id == sid)
            )
        )

    resp = await client.post(
        f"/api/v1/submissions/{sid}/questions/{question_id}/remark-request",
        json={"reason": "I think my working deserved the second mark"},
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "open"

    # It lands in front of the tutor, never in front of the AI.
    queue = (
        await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])
    ).json()
    assert len(queue) == 1
    assert queue[0]["remark_request_count"] == 1

    detail = (
        await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    ).json()
    contested = next(m for m in detail["marks"] if m["question_id"] == question_id)
    assert contested["remark_requested"] is True
    assert "second mark" in contested["remark_reason"]
    # The AI's original reasoning is still there for the tutor to weigh.
    assert contested["ai_marks"] == 2

    # A second request on the same question is refused.
    again = await client.post(
        f"/api/v1/submissions/{sid}/questions/{question_id}/remark-request",
        json={"reason": "still unhappy"},
        headers=student["headers"],
    )
    assert again.status_code == 409


async def test_resolving_a_remark_request_closes_and_audits_it(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)
    async with async_session() as session:
        sid = (await session.scalar(select(Submission))).id
        question_id = await session.scalar(
            select(QuestionMark.question_id).where(QuestionMark.submission_id == sid)
        )
    await client.post(
        f"/api/v1/submissions/{sid}/questions/{question_id}/remark-request",
        json={"reason": "please recheck"},
        headers=student["headers"],
    )

    resp = await client.put(
        f"/api/v1/submissions/{sid}/marks",
        json=[{"question_id": question_id, "final_marks": 1}],
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        request = await session.scalar(select(RemarkRequest))
        assert request.status == RemarkRequestStatus.resolved
        assert request.resolved_at is not None
        audit = await session.scalar(select(MarkOverrideAudit))
        assert audit.reason == "remark_request"
        assert (audit.old_marks, audit.new_marks) == (2, 1)

    # And the question can never be contested again.
    again = await client.post(
        f"/api/v1/submissions/{sid}/questions/{question_id}/remark-request",
        json={"reason": "one more time"},
        headers=student["headers"],
    )
    assert again.status_code == 409


async def test_a_remark_cannot_be_requested_on_an_unmarked_question(
    client, tutor, student, published_assignment, monkeypatch, fake_ai  # noqa: F811
):
    from app.services.marking import MarkingResult, QuestionMarkDraft

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1", transcription="a", proposed_marks=2,
                        feedback="Good.", confidence="high",
                    ),
                    QuestionMarkDraft(
                        number="2", transcription="b", proposed_marks=3,
                        feedback="ok", confidence="unsure",
                    ),
                ]
            )
        ),
    )
    await _submit(client, published_assignment["id"], student)
    async with async_session() as session:
        sid = (await session.scalar(select(Submission))).id
        unmarked = await session.scalar(
            select(QuestionMark.question_id).where(
                QuestionMark.submission_id == sid, QuestionMark.final_marks.is_(None)
            )
        )
    resp = await client.post(
        f"/api/v1/submissions/{sid}/questions/{unmarked}/remark-request",
        json={"reason": "too harsh"},
        headers=student["headers"],
    )
    assert resp.status_code == 409


async def test_a_student_cannot_contest_someone_elses_submission(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)
    async with async_session() as session:
        sid = (await session.scalar(select(Submission))).id
        question_id = await session.scalar(
            select(QuestionMark.question_id).where(QuestionMark.submission_id == sid)
        )

    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Nosy", "email": "nosy@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.post(
        f"/api/v1/submissions/{sid}/questions/{question_id}/remark-request",
        json={"reason": "not mine"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_the_review_queue_is_scoped_to_the_tutors_organization(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(_confident_result(confidence="low")),
    )
    await _submit(client, assignment_all_scheme, student)

    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-queue@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    assert (
        await client.get("/api/v1/submissions/review-queue", headers=headers)
    ).json() == []
    assert (
        len((await client.get("/api/v1/submissions/review-queue", headers=tutor["headers"])).json())
        == 1
    )


async def test_a_student_cannot_see_the_review_queue(client, tutor, student):  # noqa: F811
    resp = await client.get("/api/v1/submissions/review-queue", headers=student["headers"])
    assert resp.status_code == 403


async def test_resubmission_is_blocked_once_marks_have_counted(
    client, tutor, student, assignment_all_scheme, monkeypatch, fake_ai  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.marking.structured_complete", fake_ai(_confident_result())
    )
    await _submit(client, assignment_all_scheme, student)
    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.status == SubmissionStatus.auto_finalized

    resp = await client.post(
        f"/api/v1/assignments/{assignment_all_scheme}/submissions",
        files=[("files", ("page2.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert resp.status_code == 409
