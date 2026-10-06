"""Task 8.5: which events and moments queue a message, for whom, and exactly once.

Nothing here sends anything: each test reads the outbox rows `notify()` wrote.
"""

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.db import async_session
from app.models import (
    Assignment,
    Job,
    Notification,
    NotificationKind,
    Organization,
    PlanSlot,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.services.notifications import triggers
from app.services.notifications.triggers import (
    SWEEP_JOB,
    announce_homework_set,
    announce_marked_work,
    due_phrase,
    nudge_review_queue,
    remind_homework_due,
    remind_lessons,
    sweep_message_triggers,
)
from tests.factories import (
    link_parent,
    make_user,
    org_id,
    other_org_subject,
    publish_assignment,
    register_parent,
    submit_work,
)
from tests.plan_world import make_chapters, make_plan

UTC = timezone.utc
NOON = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)  # a Wednesday


async def _notes(kind: NotificationKind | None = None) -> list[Notification]:
    async with async_session() as s:
        stmt = select(Notification).order_by(Notification.id)
        if kind is not None:
            stmt = stmt.where(Notification.kind == kind)
        return list(await s.scalars(stmt))


async def _homework(group, subject, **kwargs):
    async with async_session() as s:
        assignment = await publish_assignment(
            s,
            group_id=group["id"],
            subject_id=subject["id"],
            organization_id=await org_id(s),
            **kwargs,
        )
        await s.commit()
        return assignment


# --------------------------------------------------------------------- wording


def test_a_deadline_reads_in_the_organizations_zone_and_none_is_said_in_words():
    due = datetime(2026, 10, 8, 21, 30, tzinfo=UTC)
    assert due_phrase(due, None) == "on Thu 8 Oct at 21:30"
    # 21:30 UTC is already Friday in Cairo (UTC+3 in October 2026).
    assert due_phrase(due, "Africa/Cairo") == "on Fri 9 Oct at 00:30"
    assert due_phrase(None, None) == "whenever it is ready"


# ---------------------------------------------------------------------- events


async def test_publishing_homework_tells_the_class_and_their_parents(
    client, tutor, group, student, subject
):
    parent = await register_parent(client, tutor, student)
    assignment = await _homework(group, subject, due_at=NOON + timedelta(days=2))
    async with async_session() as s:
        for _ in range(2):  # announcing twice is still one message each
            await announce_homework_set(s, assignment)
        await s.commit()
    notes = await _notes(NotificationKind.homework_set)
    assert {n.recipient_user_id for n in notes} == {student["user"]["id"], parent["user"]["id"]}
    assert len(notes) == 2
    by_reader = {n.recipient_user_id: n for n in notes}
    mine = by_reader[student["user"]["id"]]
    assert mine.params == {
        "student_name": student["user"]["name"],
        "subject_name": "Chemistry",
        "due_date": "on Fri 9 Oct at 12:00",
    }
    assert mine.link_path == f"/student/homework/{assignment.id}"
    # The parent's message is about the child, and opens the parent's own page.
    theirs = by_reader[parent["user"]["id"]]
    assert theirs.params["student_name"] == student["user"]["name"]
    assert theirs.link_path == "/parent"


async def test_homework_that_publishes_itself_after_extraction_is_announced(
    client, student, published_assignment
):
    notes = await _notes(NotificationKind.homework_set)
    assert [n.recipient_user_id for n in notes] == [student["user"]["id"]]


async def test_settled_marks_are_announced_once_however_often_they_settle(
    client, tutor, group, student, subject
):
    parent = await register_parent(client, tutor, student)
    assignment = await _homework(group, subject)
    async with async_session() as s:
        submission = await submit_work(
            s,
            assignment=assignment,
            student_id=student["user"]["id"],
            status=SubmissionStatus.finalized,
            submitted_at=NOON,
            finalized_at=NOON,
        )
        await s.commit()
        submission_id = submission.id
    # Re-read, as every real caller does: the eager `work` load is what tells a
    # submission its kind, and a row built in Python has not had it yet.
    async with async_session() as s:
        submission = await s.get(Submission, submission_id)
        for _ in range(2):  # a tutor re-finalizing after an override
            await announce_marked_work(s, submission, subject["id"])
        await s.commit()
    notes = await _notes(NotificationKind.marked_work_ready)
    assert {n.recipient_user_id for n in notes} == {student["user"]["id"], parent["user"]["id"]}
    assert len(notes) == 2
    assert all(
        n.params == {"student_name": student["user"]["name"], "subject_name": "Chemistry"}
        for n in notes
    )
    by_reader = {n.recipient_user_id: n.link_path for n in notes}
    assert by_reader[student["user"]["id"]] == f"/student/homework/{assignment.id}"
    assert by_reader[parent["user"]["id"]] == "/parent"


async def test_a_parent_in_another_organization_is_not_told(client, tutor, group, student, subject):
    assignment = await _homework(group, subject)
    async with async_session() as s:
        rival = await other_org_subject(s)
        rival_org = await s.scalar(
            select(Organization.id).where(Organization.id != await org_id(s)).limit(1)
        )
        assert rival is not None and rival_org is not None
        outsider = await make_user(
            s,
            organization_id=rival_org,
            role=UserRole.parent,
            name="Outsider",
            email="outsider@example.com",
        )
        await link_parent(s, outsider.id, student["user"]["id"])
        await announce_homework_set(s, assignment)
        await s.commit()
    assert [n.recipient_user_id for n in await _notes()] == [student["user"]["id"]]


async def test_a_message_that_cannot_be_queued_never_fails_the_work(
    client, group, student, subject, monkeypatch
):
    async def boom(*args, **kwargs):
        raise RuntimeError("outbox is down")

    monkeypatch.setattr(triggers, "notify", boom)
    assignment = await _homework(group, subject)
    async with async_session() as s:
        await announce_homework_set(s, assignment)  # does not raise
        # The caller's transaction is still usable.
        assert await s.get(User, student["user"]["id"]) is not None
        await s.commit()
    assert await _notes() == []


# --------------------------------------------------------------------- moments


async def test_homework_due_tomorrow_reminds_only_who_has_not_handed_in(
    client, tutor, group, student, subject
):
    await register_parent(client, tutor, student)
    soon = await _homework(group, subject, title="Soon", due_at=NOON + timedelta(hours=12))
    await _homework(group, subject, title="Later", due_at=NOON + timedelta(days=3))
    await _homework(group, subject, title="Past", due_at=NOON - timedelta(hours=1))
    await _homework(group, subject, title="Open", due_at=None)
    done = await _homework(group, subject, title="Done", due_at=NOON + timedelta(hours=6))
    async with async_session() as s:
        await submit_work(
            s,
            assignment=done,
            student_id=student["user"]["id"],
            status=SubmissionStatus.submitted,
            submitted_at=NOON,
        )
        for _ in range(2):  # two sweeps, one reminder
            await remind_homework_due(s, NOON)
        await s.commit()
    notes = await _notes(NotificationKind.homework_due)
    # The learner only, and only for the piece due within a day and not handed in.
    assert [(n.recipient_user_id, n.link_path) for n in notes] == [
        (student["user"]["id"], f"/student/homework/{soon.id}")
    ]


async def test_a_lesson_about_to_start_reminds_its_tutor_and_learners(
    client, tutor, group, student, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], NOON.date(), time(12, 10))])
    async with async_session() as s:
        for _ in range(2):
            assert await remind_lessons(s, NOON) == 2
        await s.commit()
    notes = await _notes(NotificationKind.lesson_reminder)
    assert {n.recipient_user_id for n in notes} == {tutor["user"]["id"], student["user"]["id"]}
    assert len(notes) == 2
    assert all(n.params == {"subject_name": "Chemistry", "start_time": "12:10"} for n in notes)


async def test_a_lesson_reminder_names_the_start_in_the_zone_the_slot_was_judged_in(
    client, tutor, group, student, subject
):
    """The tutor's own zone wins over the organization's (`due_reminders`), so
    the time in the message must be read in that zone too."""
    ch = await make_chapters(subject)
    async with async_session() as s:
        await s.execute(
            update(User).where(User.id == tutor["user"]["id"]).values(time_zone="Africa/Cairo")
        )
        await s.execute(update(Organization).values(timezone="UTC"))
        await s.commit()
    # 15:10 in Cairo (UTC+3 in October 2026) is 12:10 UTC, ten minutes after NOON.
    await make_plan(group, tutor, [(ch["c1"], NOON.date(), time(15, 10))])
    async with async_session() as s:
        assert await remind_lessons(s, NOON) == 2
        await s.commit()
    assert {n.params["start_time"] for n in await _notes(NotificationKind.lesson_reminder)} == {
        "15:10"
    }


async def test_a_lesson_moved_after_its_reminder_is_reminded_again(
    client, tutor, group, student, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], NOON.date(), time(12, 10))])
    async with async_session() as s:
        assert await remind_lessons(s, NOON) == 2
        await s.execute(update(PlanSlot).values(start_time=time(12, 14)))
        await s.commit()
    async with async_session() as s:
        await remind_lessons(s, NOON)
        await remind_lessons(s, NOON)  # the same moved lesson is still sent once
        await s.commit()
    notes = await _notes(NotificationKind.lesson_reminder)
    assert sorted(n.params["start_time"] for n in notes) == ["12:10", "12:10", "12:14", "12:14"]
    assert all(len(n.idempotency_key) <= 190 for n in notes)


async def test_homework_whose_deadline_is_extended_is_reminded_again(
    client, tutor, group, student, subject
):
    hw = await _homework(group, subject, title="Soon", due_at=NOON + timedelta(hours=6))
    async with async_session() as s:
        await remind_homework_due(s, NOON)
        await s.execute(
            update(Assignment)
            .where(Assignment.id == hw.id)
            .values(due_at=NOON + timedelta(hours=20))
        )
        await s.commit()
    async with async_session() as s:
        await remind_homework_due(s, NOON)
        await remind_homework_due(s, NOON)
        await s.commit()
    notes = await _notes(NotificationKind.homework_due)
    assert len(notes) == 2
    assert all(len(n.idempotency_key) <= 190 for n in notes)


@pytest.mark.parametrize("start", [time(11, 55), time(13, 0)])
async def test_a_lesson_already_under_way_or_not_yet_near_sends_nothing(
    client, tutor, group, student, subject, start
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], NOON.date(), start)])
    async with async_session() as s:
        assert await remind_lessons(s, NOON) == 0


async def test_work_waiting_for_review_nudges_the_tutor_once_a_day_in_waking_hours(
    client, tutor, group, student, subject
):
    assignment = await _homework(group, subject)
    async with async_session() as s:
        # Nothing waiting: nothing sent.
        assert await nudge_review_queue(s, NOON) == 0
        await submit_work(
            s,
            assignment=assignment,
            student_id=student["user"]["id"],
            status=SubmissionStatus.needs_review,
            submitted_at=NOON,
        )
        await s.flush()
        # 03:00 is not a time to be told about marking.
        assert await nudge_review_queue(s, NOON.replace(hour=3)) == 0
        await nudge_review_queue(s, NOON)
        await nudge_review_queue(s, NOON + timedelta(hours=3))  # same day: same key
        await nudge_review_queue(s, NOON + timedelta(days=1))
        await s.commit()
    notes = await _notes(NotificationKind.review_queue)
    assert [n.recipient_user_id for n in notes] == [tutor["user"]["id"]] * 2
    assert notes[0].params == {"pending_count": "1"}
    assert notes[0].link_path == "/tutor/review"


# ----------------------------------------------------------------------- sweep


async def _sweep() -> list[Job]:
    async with async_session() as s:
        await sweep_message_triggers(s, {})
        await s.commit()
    async with async_session() as s:
        return list(await s.scalars(select(Job).where(Job.type == SWEEP_JOB)))


async def test_the_sweep_re_arms_itself_and_one_failing_kind_does_not_stop_the_rest(
    client, tutor, group, student, subject, monkeypatch
):
    ran: list[str] = []

    async def broken(session, now):
        raise RuntimeError("homework query is broken")

    async def works(session, now):
        ran.append("lessons")
        return 0

    monkeypatch.setattr(triggers, "remind_homework_due", broken)
    monkeypatch.setattr(triggers, "remind_lessons", works)
    jobs = await _sweep()
    assert ran == ["lessons"]
    assert len(jobs) == 1 and jobs[0].run_after is not None
    # A second run does not stack a second successor.
    assert len(await _sweep()) == 1


async def test_switched_off_the_sweep_keeps_its_schedule_and_sends_nothing(
    client, tutor, group, student, subject, monkeypatch
):
    monkeypatch.setattr(get_settings(), "message_triggers_enabled", False)
    await _homework(group, subject, due_at=datetime.now(UTC) + timedelta(hours=2))
    assert len(await _sweep()) == 1
    assert await _notes() == []
