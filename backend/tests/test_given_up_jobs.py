"""When the worker gives up on a job, the row it was working on stops showing as
in progress.

A handler records its own failure in its `except Exception`. Two ways a job can
fail never reach that block: the worker stopping it at its time limit (a
cancellation) and the worker dying while holding it. Both used to leave the
assignment "extracting", the report "generating", the attempt "submitted", with
no error and nothing that would ever move it; for a past paper with no reason
on it, both fixes then refused it too. `on_give_up` is the worker telling the
job type, once, that it has given up."""

import asyncio
import itertools
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    Assignment,
    AssignmentStatus,
    Booklet,
    BookletStatus,
    Job,
    JobStatus,
    Mock,
    MockStatus,
    Notification,
    NotificationKind,
    NotificationStatus,
    PastPaper,
    PastPaperQuestion,
    Report,
    ReportStatus,
    Submission,
    SubmissionStatus,
    SyllabusUpload,
    SyllabusUploadStatus,
)
from app.services.ai import AIKeyMissingError
from app.services.booklets import split_given_up
from app.services.extraction import (
    assignment_read_given_up,
    booklet_read_given_up,
    mock_read_given_up,
    past_paper_read_given_up,
)
from app.services.marking import marking_given_up
from app.services.notifications.service import notification_given_up
from app.services.reports import report_given_up
from app.services.syllabus_extraction import syllabus_read_given_up
from app.workers import jobs
from app.workers.handlers import register_all
from app.workers.jobs import (
    MAX_ATTEMPTS,
    ORPHAN_RECLAIM_SECONDS,
    ORPHANED_MESSAGE,
    enqueue,
    process_one_job,
    reclaim_orphaned_jobs,
    register_handler,
)

JOB = "give_up_probe"
SHORT = 0.25
PAYLOAD = {"thing_id": 7}


@pytest.fixture
def probe(monkeypatch):
    """Register JOB with a handler and a recording give-up hook for one test,
    leaving the process-global registries as they were."""
    calls: list[tuple[dict, str]] = []

    async def _record(session, payload, error):
        calls.append((payload, error))

    def _register(handler, *, on_give_up=_record, timeout_seconds=None):
        monkeypatch.setitem(jobs._handlers, JOB, handler)
        monkeypatch.delitem(jobs._timeouts, JOB, raising=False)
        monkeypatch.delitem(jobs._give_ups, JOB, raising=False)
        if timeout_seconds is not None:
            monkeypatch.setitem(jobs._timeouts, JOB, timeout_seconds)
        if on_give_up is not None:
            monkeypatch.setitem(jobs._give_ups, JOB, on_give_up)
        return calls

    return _register


async def _queue(job_type: str = JOB, payload: dict = PAYLOAD) -> None:
    async with async_session() as session:
        await enqueue(session, job_type, payload)
        await session.commit()


async def _the_job(job_type: str = JOB) -> Job:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == job_type))
        assert job is not None
        return job


async def _skip_backoff(job_type: str = JOB) -> None:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == job_type))
        job.run_after = None
        await session.commit()


async def _run_twice(job_type: str = JOB) -> None:
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    await _skip_backoff(job_type)
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True


async def _hangs(session, payload):
    await asyncio.sleep(30)


# --- When the hook runs ----------------------------------------------------


async def test_a_job_stopped_twice_tells_its_type_once_with_the_reason(client, probe):
    calls = probe(_hangs, timeout_seconds=SHORT)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    assert calls == [], "the first stop is retried, so nothing has been given up yet"

    await _skip_backoff()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert calls == [(PAYLOAD, job.error)]
    assert "time limit" in job.error


async def test_a_failure_that_is_not_retried_tells_its_type_at_once(client, probe):
    async def _no_key(session, payload):
        raise AIKeyMissingError("marking")

    calls = probe(_no_key)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert calls == [(PAYLOAD, job.error)]


async def test_a_job_that_succeeds_or_is_retried_tells_nobody(client, probe):
    async def _fine(session, payload):
        return None

    calls = probe(_fine)
    await _queue()
    assert await process_one_job() is True
    assert (await _the_job()).status == JobStatus.done

    async def _fails_once(session, payload):
        raise RuntimeError("blip")

    probe(_fails_once)
    await _queue(payload={"other": 1})
    assert await process_one_job() is True
    async with async_session() as session:
        retried = await session.scalar(select(Job).where(Job.payload == {"other": 1}))
    assert retried is not None and retried.status == JobStatus.pending
    assert calls == []


async def _orphan(*, attempts: int, job_type: str = JOB, payload: dict = PAYLOAD) -> None:
    """A row a dead worker left `running`: its claimant has no heartbeat row."""
    async with async_session() as session:
        session.add(
            Job(
                type=job_type,
                payload=payload,
                status=JobStatus.running,
                attempts=attempts,
                claimed_by="worker-that-died",
                claimed_at=datetime.now(timezone.utc)
                - timedelta(seconds=ORPHAN_RECLAIM_SECONDS + 60),
            )
        )
        await session.commit()


async def test_a_job_orphaned_with_no_attempts_left_tells_its_type_in_plain_words(client, probe):
    calls = probe(_hangs)
    await _orphan(attempts=MAX_ATTEMPTS)

    assert await reclaim_orphaned_jobs() == 1

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert "worker-that-died" in job.error, "the job keeps the detail for whoever reads the queue"
    assert calls == [(PAYLOAD, ORPHANED_MESSAGE)]
    assert "worker" not in ORPHANED_MESSAGE, "the row gets words a tutor can read"


async def test_a_job_orphaned_with_an_attempt_left_is_requeued_and_tells_nobody(client, probe):
    calls = probe(_hangs)
    await _orphan(attempts=1)

    assert await reclaim_orphaned_jobs() == 1

    assert (await _the_job()).status == JobStatus.pending
    assert calls == []


# --- The hook can never hurt the worker -------------------------------------


async def test_a_hook_that_raises_is_logged_and_the_job_stays_failed(client, probe, caplog):
    async def _broken(session, payload, error):
        raise RuntimeError("hook fell over")

    probe(_hangs, on_give_up=_broken, timeout_seconds=SHORT)
    await _queue()

    await _run_twice()

    assert (await _the_job()).status == JobStatus.failed
    assert any(
        "could not record that job" in r.getMessage()
        and "give_up_probe" in r.getMessage()
        and "thing_id" in r.getMessage()
        and r.exc_info is not None
        for r in caplog.records
    )
    assert await process_one_job() is False, "the worker carries on"


async def test_a_hook_that_hangs_is_stopped(client, probe, monkeypatch, caplog):
    monkeypatch.setattr(jobs, "GIVE_UP_TIMEOUT_SECONDS", SHORT)

    async def _hangs_too(session, payload, error):
        await asyncio.sleep(30)

    probe(_hangs, on_give_up=_hangs_too, timeout_seconds=SHORT)
    await _queue()

    await _run_twice()

    assert (await _the_job()).status == JobStatus.failed
    assert any("could not record" in r.getMessage() for r in caplog.records)


async def test_what_a_hook_writes_is_committed(client, probe):
    async def _writes(session, payload, error):
        await enqueue(session, "written_by_the_hook", {})

    probe(_hangs, on_give_up=_writes, timeout_seconds=SHORT)
    await _queue()

    await _run_twice()

    async with async_session() as session:
        written = await session.scalar(
            select(func.count()).select_from(Job).where(Job.type == "written_by_the_hook")
        )
    assert written == 1


async def test_a_newer_job_for_the_same_row_keeps_the_row(client, probe):
    """A tutor's "try again" (or a student's resubmission) can put the row back
    in progress with a fresh job behind it while the old job was still on its
    last attempt. The row is the fresh job's: failing it would show a failure
    for work that is still going."""
    calls = probe(_hangs, timeout_seconds=SHORT)
    await _queue()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    # The fresh job: same type and payload, not yet due, so the old job's
    # second attempt is what the worker claims next.
    async with async_session() as session:
        fresh = Job(type=JOB, payload=dict(PAYLOAD), status=JobStatus.pending)
        fresh.run_after = datetime.now(timezone.utc) + timedelta(hours=1)
        session.add(fresh)
        await session.commit()
    await _skip_backoff_of_the_first()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    async with async_session() as session:
        statuses = (await session.scalars(select(Job.status).where(Job.type == JOB))).all()
    assert sorted(statuses) == sorted([JobStatus.failed, JobStatus.pending])
    assert calls == []


async def test_a_job_for_another_row_does_not_hold_the_hook_back(client, probe):
    calls = probe(_hangs, timeout_seconds=SHORT)
    await _queue()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    async with async_session() as session:
        other = Job(type=JOB, payload={"thing_id": 8}, status=JobStatus.pending)
        other.run_after = datetime.now(timezone.utc) + timedelta(hours=1)
        session.add(other)
        await session.commit()
    await _skip_backoff_of_the_first()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert len(calls) == 1


async def test_an_orphan_whose_row_has_a_newer_job_keeps_the_row(client, probe):
    calls = probe(_hangs)
    await _orphan(attempts=MAX_ATTEMPTS)
    await _queue()  # the student resubmitted while the old job was stuck

    assert await reclaim_orphaned_jobs() == 1

    assert calls == []


async def test_the_hook_runs_after_the_jobs_failure_is_committed(client, probe):
    seen: list[JobStatus] = []

    async def _reads_the_job(session, payload, error):
        async with async_session() as other:
            job = await other.scalar(select(Job).where(Job.type == JOB))
            seen.append(job.status)

    probe(_hangs, on_give_up=_reads_the_job, timeout_seconds=SHORT)
    await _queue()

    await _run_twice()

    assert seen == [JobStatus.failed]


async def test_stopping_the_worker_during_a_hook_is_not_swallowed(client, probe):
    """Only failures of the hook are contained. A cancellation is the worker
    being shut down, and must reach whoever is shutting it down."""
    entered = asyncio.Event()

    async def _waits(session, payload, error):
        entered.set()
        await asyncio.sleep(30)

    probe(_hangs, on_give_up=_waits)
    await _orphan(attempts=MAX_ATTEMPTS)

    sweep = asyncio.create_task(reclaim_orphaned_jobs())
    await asyncio.wait_for(entered.wait(), timeout=10)
    sweep.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sweep


async def _skip_backoff_of_the_first() -> None:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB).order_by(Job.id).limit(1))
        job.run_after = None
        await session.commit()


def test_registering_without_a_hook_clears_one_left_by_an_earlier_registration(monkeypatch):
    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_give_ups", {})

    async def _hook(session, payload, error):
        return None

    register_handler(JOB, _hangs, on_give_up=_hook)
    assert jobs._give_ups[JOB] is _hook
    register_handler(JOB, _hangs)
    assert JOB not in jobs._give_ups


# --- Every job type that leaves a row in progress has one --------------------

HOOKED = {
    "extract_assignment": assignment_read_given_up,
    "extract_past_paper": past_paper_read_given_up,
    "extract_mock": mock_read_given_up,
    "extract_booklet": booklet_read_given_up,
    "split_booklet": split_given_up,
    "mark_submission": marking_given_up,
    "generate_report": report_given_up,
    "extract_syllabus": syllabus_read_given_up,
    "send_notification": notification_given_up,
}


def test_every_handler_that_leaves_a_row_in_progress_is_wired_to_its_hook(monkeypatch):
    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_timeouts", {})
    monkeypatch.setattr(jobs, "_give_ups", {})
    register_all()
    assert jobs._give_ups == HOOKED


# --- Each hook, on a real row ----------------------------------------------
#
# Three cases for every row type: still in progress (marked failed with the
# reason), already marked failed by its own handler (its reason kept), and moved
# on since (left alone). SQLite in the suite does not enforce foreign keys, so a
# row needs only its own required columns.

ERROR = "The job ran past its 900-second time limit and was stopped"
OWN = "the handler's own reason"


#: `work_id` is unique on every row type that has one, so each row gets its own.
_ids = itertools.count(1)


async def _add(row):
    async with async_session() as session:
        session.add(row)
        await session.commit()
        return row.id


async def _get(model, row_id):
    async with async_session() as session:
        return await session.get(model, row_id)


def _assignment(status, error=None):
    return Assignment(
        group_id=1, title="Homework", work_id=next(_ids), status=status, extraction_error=error
    )


def _mock(status, error=None):
    return Mock(
        organization_id=1,
        tutor_id=1,
        subject_id=1,
        title="Mock",
        paper_path="p",
        paper_name="p.pdf",
        paper_mime="application/pdf",
        work_id=next(_ids),
        status=status,
        extraction_error=error,
    )


def _booklet(status, error=None):
    return Booklet(organization_id=1, subject_id=1, status=status, error=error)


def _upload(status, error=None):
    return SyllabusUpload(
        tutor_id=1,
        title="Syllabus",
        file_path="s",
        file_name="s.pdf",
        file_mime="application/pdf",
        status=status,
        error=error,
    )


def _report(status, error=None):
    return Report(
        student_id=1,
        generated_by_id=1,
        audience="parent",
        title="Report",
        status=status,
        error=error,
    )


def _submission(status, error=None):
    return Submission(work_id=next(_ids), student_id=1, status=status, ai_error=error)


def _notification(status, error=None):
    return Notification(
        organization_id=1,
        recipient_user_id=1,
        kind=NotificationKind.homework_set,
        template="t",
        idempotency_key=f"k{next(_ids)}",
        status=status,
        error=error,
    )


# (hook, payload key, build, error attribute, in progress, failed, moved on)
CASES = [
    pytest.param(
        assignment_read_given_up, "assignment_id", _assignment, "extraction_error",
        [AssignmentStatus.extracting], AssignmentStatus.extraction_failed,
        [AssignmentStatus.published, AssignmentStatus.review],
        id="assignment",
    ),
    pytest.param(
        mock_read_given_up, "mock_id", _mock, "extraction_error",
        [MockStatus.extracting], MockStatus.extraction_failed, [MockStatus.published],
        id="mock",
    ),
    pytest.param(
        booklet_read_given_up, "booklet_id", _booklet, "error",
        [BookletStatus.extracting], BookletStatus.extraction_failed,
        [BookletStatus.review, BookletStatus.applying],
        id="booklet-read",
    ),
    pytest.param(
        split_given_up, "booklet_id", _booklet, "error",
        [BookletStatus.applying], BookletStatus.split_failed,
        [BookletStatus.applied, BookletStatus.review, BookletStatus.extracting],
        id="booklet-split",
    ),
    pytest.param(
        syllabus_read_given_up, "syllabus_upload_id", _upload, "error",
        [SyllabusUploadStatus.extracting], SyllabusUploadStatus.extraction_failed,
        [SyllabusUploadStatus.review, SyllabusUploadStatus.applied],
        id="syllabus",
    ),
    pytest.param(
        report_given_up, "report_id", _report, "error",
        [ReportStatus.generating], ReportStatus.failed, [ReportStatus.ready],
        id="report",
    ),
    pytest.param(
        marking_given_up, "submission_id", _submission, "ai_error",
        [SubmissionStatus.submitted], SubmissionStatus.ai_failed,
        [
            SubmissionStatus.ai_marked,
            SubmissionStatus.needs_review,
            SubmissionStatus.auto_finalized,
            SubmissionStatus.finalized,
        ],
        id="submission",
    ),
    pytest.param(
        notification_given_up, "notification_id", _notification, "error",
        [NotificationStatus.queued], NotificationStatus.failed,
        [NotificationStatus.sent, NotificationStatus.suppressed],
        id="notification",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("hook", "key", "build", "attr", "busy", "failed", "moved_on"), CASES)
async def test_a_row_still_in_progress_is_marked_failed_with_the_reason(
    client, hook, key, build, attr, busy, failed, moved_on
):
    for status in busy:
        row_id = await _add(build(status))
        async with async_session() as session:
            await hook(session, {key: row_id}, ERROR)
            await session.commit()
        row = await _get(type(build(status)), row_id)
        assert row.status is failed, status
        assert getattr(row, attr) == ERROR


@pytest.mark.parametrize(("hook", "key", "build", "attr", "busy", "failed", "moved_on"), CASES)
async def test_a_row_its_handler_marked_or_that_moved_on_is_left_alone(
    client, hook, key, build, attr, busy, failed, moved_on
):
    for status, error in [(failed, OWN), *((s, None) for s in moved_on)]:
        row_id = await _add(build(status, error))
        async with async_session() as session:
            await hook(session, {key: row_id}, ERROR)
            await session.commit()
        row = await _get(type(build(status)), row_id)
        assert row.status is status
        assert getattr(row, attr) == error


@pytest.mark.parametrize(("hook", "key", "build", "attr", "busy", "failed", "moved_on"), CASES)
async def test_a_row_that_is_gone_is_not_an_error(
    client, hook, key, build, attr, busy, failed, moved_on
):
    async with async_session() as session:
        await hook(session, {key: 999_999}, ERROR)


async def _paper(error=None) -> int:
    return await _add(
        PastPaper(
            organization_id=1,
            booklet_id=next(_ids),
            subject_id=1,
            work_id=next(_ids),
            extraction_error=error,
        )
    )


async def test_a_past_paper_left_with_no_questions_and_no_reason_gets_the_reason(client):
    """The case that mattered most: with no reason, both fixes refuse the paper
    (`_require_unread`), so the tutor could never try again."""
    paper_id = await _paper()
    async with async_session() as session:
        await past_paper_read_given_up(session, {"past_paper_id": paper_id}, ERROR)
        await session.commit()
    assert (await _get(PastPaper, paper_id)).extraction_error == ERROR


async def test_a_past_paper_with_its_own_reason_or_with_questions_is_left_alone(client):
    with_reason = await _paper(OWN)
    read = await _paper()
    await _add(
        PastPaperQuestion(past_paper_id=read, position=1, number="1", text_summary="q", max_marks=1)
    )
    async with async_session() as session:
        for paper_id in (with_reason, read, 999_999):
            await past_paper_read_given_up(session, {"past_paper_id": paper_id}, ERROR)
        await session.commit()
    assert (await _get(PastPaper, with_reason)).extraction_error == OWN
    assert (await _get(PastPaper, read)).extraction_error is None


# --- End to end, through the worker ----------------------------------------


async def test_a_report_whose_job_was_stopped_twice_shows_as_failed(client, monkeypatch):
    """The whole path with a real hook: the worker stops a report's job at its
    limit twice, and the report stops showing "generating"."""
    report_id = await _add(_report(ReportStatus.generating))
    monkeypatch.setitem(jobs._handlers, "generate_report", _hangs)
    monkeypatch.setitem(jobs._timeouts, "generate_report", SHORT)
    monkeypatch.setitem(jobs._give_ups, "generate_report", report_given_up)
    await _queue("generate_report", {"report_id": report_id})

    await _run_twice("generate_report")

    report = await _get(Report, report_id)
    assert report.status is ReportStatus.failed
    assert report.error == (await _the_job("generate_report")).error


async def test_an_attempt_whose_marking_worker_died_twice_shows_as_failed(client, monkeypatch):
    submission_id = await _add(_submission(SubmissionStatus.submitted))
    monkeypatch.setitem(jobs._handlers, "mark_submission", _hangs)
    monkeypatch.setitem(jobs._give_ups, "mark_submission", marking_given_up)
    await _orphan(
        attempts=MAX_ATTEMPTS, job_type="mark_submission", payload={"submission_id": submission_id}
    )

    assert await reclaim_orphaned_jobs() == 1

    submission = await _get(Submission, submission_id)
    assert submission.status is SubmissionStatus.ai_failed
    assert submission.ai_error == ORPHANED_MESSAGE
