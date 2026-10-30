"""A tutor can send work the AI could not mark back to the AI.

Until this, `ai_failed` had one way out: the tutor marking every question by
hand, however passing the cause (a provider outage, a missing key put back).
The retry is a tutor action on one submission, and it must never double the
marking of the same pages."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, Submission, SubmissionStatus
from app.services.ai import AIKeyMissingError
from app.services.marking import ALREADY_MARKING, NOT_RETRYABLE
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES
from tests.redo_world import _colleague_headers
from tests.test_auto_marking import _confident_result, assignment_all_scheme  # noqa: F401
from tests.test_past_papers import _log_attempt, past_paper  # noqa: F401

API = "/api/v1"


@pytest.fixture
def ai_fails(monkeypatch):
    async def _no_key(**_kwargs):
        raise AIKeyMissingError("marking")

    monkeypatch.setattr("app.services.marking.structured_complete", _no_key)


@pytest.fixture
def ai_marks(monkeypatch, fake_ai):
    def _now_it_works():
        monkeypatch.setattr(
            "app.services.marking.structured_complete", fake_ai(_confident_result())
        )

    return _now_it_works


async def _hand_in(client, student, assignment_id) -> int:
    response = await client.post(
        f"{API}/assignments/{assignment_id}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert response.status_code == 201
    async with async_session() as session:
        return (await session.scalars(select(Submission.id))).one()


async def _submission(sid: int) -> Submission:
    async with async_session() as session:
        row = await session.get(Submission, sid)
        assert row is not None
        return row


async def _marking_jobs(status: JobStatus | None = None) -> list[Job]:
    async with async_session() as session:
        query = select(Job).where(Job.type == "mark_submission")
        if status is not None:
            query = query.where(Job.status == status)
        return list((await session.scalars(query)).all())


@pytest.fixture
async def failed_attempt(client, student, assignment_all_scheme, ai_fails):  # noqa: F811
    """Handed in, and the AI could not mark it: the key is missing, which is
    not retried, so the job fails at once and the attempt is `ai_failed`."""
    sid = await _hand_in(client, student, assignment_all_scheme)
    assert await process_one_job() is True
    row = await _submission(sid)
    assert row.status is SubmissionStatus.ai_failed
    assert row.ai_error
    return sid


async def test_a_tutor_can_send_failed_work_back_to_the_ai(client, tutor, failed_attempt, ai_marks):
    response = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=tutor["headers"]
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["ai_error"] is None
    assert len(await _marking_jobs(JobStatus.pending)) == 1

    ai_marks()
    assert await process_one_job() is True

    row = await _submission(failed_attempt)
    assert row.status in (SubmissionStatus.auto_finalized, SubmissionStatus.needs_review)
    assert row.ai_error is None


async def test_work_that_is_not_failed_is_refused_and_untouched(
    client,
    tutor,
    student,
    assignment_all_scheme,  # noqa: F811
):
    """`submitted` already has its job queued; a second would mark the same
    pages twice and bill for both."""
    sid = await _hand_in(client, student, assignment_all_scheme)

    response = await client.post(f"{API}/submissions/{sid}/retry-marking", headers=tutor["headers"])

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_RETRYABLE
    assert len(await _marking_jobs()) == 1
    assert (await _submission(sid)).status is SubmissionStatus.submitted


async def test_a_retry_already_waiting_is_brought_forward_not_doubled(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    ai_marks,  # noqa: F811
):
    """The worker's own retry waits a minute, and a tutor pressing "Try
    marking again" inside that minute must not queue a second job beside it."""

    async def _blip(**_kwargs):
        raise RuntimeError("provider hiccup")

    monkeypatch.setattr("app.services.marking.structured_complete", _blip)
    sid = await _hand_in(client, student, assignment_all_scheme)
    assert await process_one_job() is True
    [waiting] = await _marking_jobs(JobStatus.pending)
    assert waiting.run_after is not None, "the worker's retry is waiting out its backoff"

    response = await client.post(f"{API}/submissions/{sid}/retry-marking", headers=tutor["headers"])

    assert response.status_code == 200
    [job] = await _marking_jobs(JobStatus.pending)
    assert job.id == waiting.id
    assert job.attempts == 0, "a fresh job: whatever made it fail is what changed"
    run_after = job.run_after
    assert run_after is None or run_after.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)


async def test_work_being_marked_right_now_is_refused(client, tutor, failed_attempt):
    """The attempt still reads `ai_failed` while the worker's retry runs."""
    async with async_session() as session:
        session.add(
            Job(
                type="mark_submission",
                payload={"submission_id": failed_attempt},
                status=JobStatus.running,
                attempts=2,
                claimed_by="a-worker",
                claimed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    response = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=tutor["headers"]
    )

    assert response.status_code == 409
    assert response.json()["detail"] == ALREADY_MARKING
    assert (await _submission(failed_attempt)).status is SubmissionStatus.ai_failed


async def test_a_second_press_is_refused(client, tutor, failed_attempt):
    first = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=tutor["headers"]
    )
    second = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=tutor["headers"]
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(await _marking_jobs(JobStatus.pending)) == 1


# --- Who may (QA-12) --------------------------------------------------------


async def test_a_student_cannot_retry_marking(client, student, failed_attempt):
    response = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=student["headers"]
    )

    assert response.status_code == 403
    assert (await _submission(failed_attempt)).status is SubmissionStatus.ai_failed


async def test_another_organizations_tutor_gets_a_404(client, failed_attempt):
    signup = await client.post(
        f"{API}/auth/register/tutor",
        json={
            "name": "Someone Else",
            "email": "other-org-tutor@example.com",
            "password": "password123",
        },
    )
    assert signup.status_code == 201, signup.text
    headers = {"Authorization": f"Bearer {signup.json()['tokens']['access_token']}"}

    response = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=headers
    )

    assert response.status_code == 404
    assert (await _submission(failed_attempt)).status is SubmissionStatus.ai_failed
    assert await _marking_jobs(JobStatus.pending) == []


async def test_a_missing_submission_is_a_404(client, tutor):
    response = await client.post(
        f"{API}/submissions/999999/retry-marking", headers=tutor["headers"]
    )

    assert response.status_code == 404


async def test_marks_the_tutor_already_entered_survive_the_retry(
    client, tutor, failed_attempt, ai_marks
):
    """A tutor may start marking failed work by hand, then try the AI again
    for the rest. The AI fills in what is left; it never replaces a mark the
    tutor gave (`PROD-7`)."""
    detail = await client.get(f"{API}/submissions/{failed_attempt}", headers=tutor["headers"])
    first = detail.json()["marks"][0]
    saved = await client.put(
        f"{API}/submissions/{failed_attempt}/marks",
        json=[{"question_id": first["question_id"], "final_marks": 1, "final_feedback": "Mine."}],
        headers=tutor["headers"],
    )
    assert saved.status_code == 200, saved.text

    retried = await client.post(
        f"{API}/submissions/{failed_attempt}/retry-marking", headers=tutor["headers"]
    )
    assert retried.status_code == 200
    ai_marks()
    assert await process_one_job() is True

    after = await client.get(f"{API}/submissions/{failed_attempt}", headers=tutor["headers"])
    mine = next(m for m in after.json()["marks"] if m["question_id"] == first["question_id"])
    assert mine["final_marks"] == 1
    assert mine["final_feedback"] == "Mine."


@pytest.fixture
async def failed_past_paper_attempt(client, student, past_paper, ai_fails):  # noqa: F811
    response = await _log_attempt(client, student, past_paper["id"])
    assert response.status_code == 201, response.text
    assert await process_one_job() is True
    async with async_session() as session:
        row = await session.scalar(select(Submission))
        assert row is not None
        assert row.status is SubmissionStatus.ai_failed
        return row.id


async def test_a_colleague_who_does_not_teach_the_student_cannot_retry_a_past_paper(
    client, failed_past_paper_attempt
):
    """A past paper belongs to the organization, so any tutor in it can open
    an attempt. Marking it again spends money and writes the student's
    evidence, so, as for a redo, only a tutor who teaches this student in the
    paper's subject may."""
    response = await client.post(
        f"{API}/submissions/{failed_past_paper_attempt}/retry-marking",
        headers=await _colleague_headers(),
    )

    assert response.status_code == 404
    assert (await _submission(failed_past_paper_attempt)).status is SubmissionStatus.ai_failed
    assert await _marking_jobs(JobStatus.pending) == []


async def test_the_tutor_who_teaches_the_student_can_retry_a_past_paper(
    client, tutor, failed_past_paper_attempt
):
    response = await client.post(
        f"{API}/submissions/{failed_past_paper_attempt}/retry-marking", headers=tutor["headers"]
    )

    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


async def test_a_colleague_teaching_the_student_another_subject_cannot_retry_a_past_paper(
    client, student, failed_past_paper_attempt
):
    """Teaching the student is not enough: it must be in the paper's subject.
    A physics tutor cannot spend on, or write evidence for, a chemistry paper."""
    from app.models import Group, GroupMember, Subject, User
    from tests.factories import org_id, subject_defaults

    headers = await _colleague_headers()
    async with async_session() as session:
        colleague = await session.scalar(select(User).where(User.email == "colleague@example.com"))
        physics = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add(physics)
        await session.flush()
        group = Group(
            organization_id=await org_id(session),
            tutor_id=colleague.id,
            subject_id=physics.id,
            name="Physics class",
        )
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=student["user"]["id"]))
        await session.commit()

    response = await client.post(
        f"{API}/submissions/{failed_past_paper_attempt}/retry-marking", headers=headers
    )

    assert response.status_code == 404
    assert await _marking_jobs(JobStatus.pending) == []


SECRET = "sk-test-LEAK-9f3 at postgres://user:hunter2@db.internal/avora"


async def test_a_marking_failure_stores_a_safe_sentence_and_logs_the_detail(
    client,
    student,
    assignment_all_scheme,
    monkeypatch,
    caplog,  # noqa: F811
):
    async def _boom(**_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.services.marking.structured_complete", _boom)
    sid = await _hand_in(client, student, assignment_all_scheme)
    with caplog.at_level("ERROR"):
        assert await process_one_job() is True

    row = await _submission(sid)
    assert row.status is SubmissionStatus.ai_failed
    assert row.ai_error == "Something went wrong on our side. Try again in a few minutes."
    assert SECRET in caplog.text
    # The worker's retry is unchanged.
    assert len(await _marking_jobs(JobStatus.pending)) == 1


async def test_a_replaced_attempt_still_logs_the_failure_it_discards(
    client,
    student,
    assignment_all_scheme,
    monkeypatch,
    caplog,  # noqa: F811
):
    async def _boom(**_kwargs):
        raise RuntimeError(SECRET)

    async def _replaced(*_args, **_kwargs):
        return False

    monkeypatch.setattr("app.services.marking.structured_complete", _boom)
    monkeypatch.setattr("app.services.marking._still_the_same_attempt", _replaced)
    sid = await _hand_in(client, student, assignment_all_scheme)
    with caplog.at_level("WARNING"):
        assert await process_one_job() is True

    assert (await _submission(sid)).ai_error is None
    assert SECRET in caplog.text
