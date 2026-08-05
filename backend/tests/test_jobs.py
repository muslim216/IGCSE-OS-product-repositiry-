"""WS1: the job queue's scheduling primitive (Job.run_after) and the
idempotency guarantees the retrying worker depends on."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import get_settings
from app.db import async_session
from app.models import (
    AssignmentQuestion,
    Job,
    JobStatus,
    QuestionMark,
    QuestionTopic,
    Submission,
)
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced
from app.workers.jobs import enqueue, process_one_job
from tests.test_homework import (  # noqa: F401 - shared fixtures
    PNG_BYTES,
    classified,
    fake_extraction,
    fake_marking,
    group,
    published_assignment,
    student,
    subject,
)


async def test_a_future_dated_job_is_not_claimed_until_it_is_due(client):
    async with async_session() as session:
        await enqueue(
            session,
            "recompute_readiness",
            {"student_id": 1},
            run_after=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await session.commit()

    assert await process_one_job() is False, "a job scheduled for later must not be claimed"

    async with async_session() as session:
        job = await session.scalar(select(Job))
        job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    assert await process_one_job() is True


async def test_a_job_with_no_run_after_is_claimed_immediately(client):
    async with async_session() as session:
        await enqueue(session, "recompute_readiness", {"student_id": 1})
        await session.commit()
    assert await process_one_job() is True


async def test_readiness_v2_triggers_coalesce_into_a_single_job(client, monkeypatch):
    """A burst of triggers for the same (student, subject) must cost one
    synthesis run, not one per trigger — this is the biggest AI-spend lever in
    the auto-marking world."""
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", True)
    async with async_session() as session:
        for _ in range(5):
            await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=3)
        await session.commit()

    async with async_session() as session:
        jobs = (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()
        assert len(jobs) == 1
        assert jobs[0].run_after is not None, "the coalesced run must be scheduled, not immediate"


async def test_coalescing_is_scoped_per_student_and_subject(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", True)
    async with async_session() as session:
        await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=3)
        await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=4)
        await enqueue_readiness_v2_debounced(session, student_id=8, subject_id=3)
        await session.commit()

    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Job.id)).where(Job.type == "compute_readiness_v2")
        )
        assert count == 3


async def test_a_finished_run_no_longer_blocks_the_next_one(client, monkeypatch):
    """Coalescing keys off *pending* jobs only, so once a run has been claimed
    the next trigger schedules a fresh one."""
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", True)
    async with async_session() as session:
        await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=3)
        await session.commit()
    async with async_session() as session:
        job = await session.scalar(select(Job))
        job.status = JobStatus.done
        await session.commit()

    async with async_session() as session:
        await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=3)
        await session.commit()

    async with async_session() as session:
        count = await session.scalar(select(func.count(Job.id)))
        assert count == 2


async def test_coalescing_is_a_no_op_while_v2_is_disabled(client, monkeypatch):
    """The flag is the kill switch: with it off, no v2 work is queued at all
    and readiness falls back to the v1 engine."""
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", False)
    async with async_session() as session:
        await enqueue_readiness_v2_debounced(session, student_id=7, subject_id=3)
        await session.commit()
    async with async_session() as session:
        assert (await session.scalar(select(func.count(Job.id)))) == 0


async def test_re_running_extraction_replaces_questions_instead_of_duplicating(
    client,
    tutor,
    group,
    classified,
    subject,
    monkeypatch,  # noqa: F811
):
    """The worker retries a failed job once, and a tutor can re-trigger
    extraction — neither may leave two copies of every question."""
    monkeypatch.setattr("app.services.extraction._run_extraction", fake_extraction(subject))
    from app.services.extraction import extract_assignment

    created = await client.post(
        "/api/v1/assignments",
        json={
            "group_id": group["id"],
            "title": "Bonding",
            "classified_id": classified["id"],
        },
        headers=tutor["headers"],
    )
    aid = created.json()["id"]
    assert await process_one_job() is True

    async with async_session() as session:
        first = await session.scalar(
            select(func.count(AssignmentQuestion.id)).where(AssignmentQuestion.assignment_id == aid)
        )
        assert first > 0

    # Run the very same job payload a second time.
    async with async_session() as session:
        await extract_assignment(session, {"assignment_id": aid})
        await session.commit()

    async with async_session() as session:
        second = await session.scalar(
            select(func.count(AssignmentQuestion.id)).where(AssignmentQuestion.assignment_id == aid)
        )
        assert second == first, "re-extraction must replace the question list, not append to it"
        # The topic links go with them rather than piling up orphaned.
        topic_links = await session.scalar(select(func.count(QuestionTopic.id)))
        assert topic_links == first


def _marking_double(fake_ai):
    """The real _run_marking driven by a stubbed AI call, so the idempotency
    guards inside it are actually exercised."""
    from app.services.marking import MarkingResult, QuestionMarkDraft

    return fake_ai(
        MarkingResult(
            questions=[
                QuestionMarkDraft(
                    number="1",
                    transcription="An isotope has the same protons, different neutrons.",
                    proposed_marks=2,
                    feedback="Good.",
                    confidence="high",
                ),
                QuestionMarkDraft(
                    number="2",
                    transcription="Ionic bonding is electrostatic attraction.",
                    proposed_marks=3,
                    feedback="Good.",
                    confidence="high",
                ),
            ]
        )
    )


async def test_re_running_marking_does_not_duplicate_marks(
    client,
    tutor,
    student,
    published_assignment,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    from app.services.marking import mark_submission

    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        first = await session.scalar(
            select(func.count(QuestionMark.id)).where(QuestionMark.submission_id == submission.id)
        )
        assert first > 0
        submission_id = submission.id

    async with async_session() as session:
        await mark_submission(session, {"submission_id": submission_id})
        await session.commit()

    async with async_session() as session:
        second = await session.scalar(
            select(func.count(QuestionMark.id)).where(QuestionMark.submission_id == submission_id)
        )
        assert second == first


async def test_re_marking_never_overwrites_a_tutor_finalized_mark(
    client,
    tutor,
    student,
    published_assignment,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """If marking is re-run after a tutor has decided a mark, the tutor's
    number must survive — and with every question decided, no AI call is made
    at all."""
    from app.services.marking import MarkingResult, QuestionMarkDraft, mark_submission

    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    aid = published_assignment["id"]
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        submission_id = submission.id
        marks = (
            await session.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission_id)
            )
        ).all()
        for mark in marks:
            mark.final_marks = 1
        await session.commit()

    # An AI response that would award something different, to prove it isn't used.
    monkeypatch.undo()
    called = {"n": 0}
    fake = fake_ai(
        MarkingResult(
            questions=[
                QuestionMarkDraft(
                    number="1",
                    transcription="different",
                    proposed_marks=2,
                    feedback="different",
                    confidence="high",
                )
            ]
        )
    )

    async def counting_fake(**kwargs):
        called["n"] += 1
        return await fake(**kwargs)

    monkeypatch.setattr("app.services.marking.structured_complete", counting_fake)

    async with async_session() as session:
        await mark_submission(session, {"submission_id": submission_id})
        await session.commit()

    assert called["n"] == 0, "every question already finalized -> no AI call, no spend"
    async with async_session() as session:
        marks = (
            await session.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission_id)
            )
        ).all()
        assert all(m.final_marks == 1 for m in marks)
