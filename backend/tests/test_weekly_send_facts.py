"""Task 8.2, the facts behind the weekly send: the window, the three variants, and
the security criterion that nothing a student wrote can reach them (F9).

The send moment is Sunday 18:00 and the clock is pinned: the window is
Sun 4 Oct 18:00 to Sun 11 Oct 18:00 2026, UTC (the org has no timezone here).
"""

import dataclasses
import json
import typing
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event, select, update

from app.db import async_session, engine
from app.models import (
    Assignment,
    AssignmentQuestion,
    AttendanceSource,
    AttendanceState,
    FactorConfidence,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    LessonObservation,
    Organization,
    PlanSlot,
    QuestionMark,
    SubmissionStatus,
    TeachingPlan,
    User,
    UserRole,
)
from app.services import weekly_send_facts as facts
from app.services.weekly_send_facts import (
    build_parent_facts,
    build_student_facts,
    build_tutor_facts,
    week_window,
)
from tests.factories import (
    link_parent,
    make_user,
    org_id,
    other_org_subject,
    publish_assignment,
    set_boundaries,
    submit_work,
    write_v2_snapshot,
)
from tests.plan_world import LONG_AGO, make_chapters, make_plan

UTC = timezone.utc
SEND_NOW = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
WINDOW = week_window(SEND_NOW, None, 6, 18)
SENTINEL = "ZQXJ-student-words-must-never-travel"


def at(day: int, hour: int = 10, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


# ------------------------------------------------------------------ the window


def test_window_is_seven_days_ending_at_the_latest_send_moment():
    assert week_window(SEND_NOW, None, 6, 18) == (at(4, 18), at(11, 18))
    # Before this Sunday's send: the window that closed last Sunday.
    assert week_window(at(11, 17), None, 6, 18) == (at(27, 18, 9), at(4, 18))
    # A weekday send reads back to the same weekday.
    assert week_window(at(8, 9), None, 0, 8) == (at(28, 8, 9), at(5, 8))


def test_a_moment_exactly_at_the_send_time_closes_that_week():
    start, end = week_window(at(11, 18), None, 6, 18)
    assert end == at(11, 18) and start == at(4, 18)
    # One second earlier it is still last week's.
    assert week_window(at(11, 18) - timedelta(seconds=1), None, 6, 18)[1] == at(4, 18)


def test_null_or_unknown_zone_is_utc_and_a_naive_clock_is_read_as_utc():
    expected = week_window(SEND_NOW, None, 6, 18)
    assert week_window(SEND_NOW, "Not/AZone", 6, 18) == expected
    assert week_window(SEND_NOW.replace(tzinfo=None), None, 6, 18) == expected


def test_the_send_follows_the_tutors_clock_across_a_clock_change():
    # London springs forward at 01:00 UTC on Sun 29 Mar 2026. Sunday 18:00 is
    # 18:00 GMT a week earlier and 17:00 UTC after the change: the window is seven
    # local days, so 167 hours.
    start, end = week_window(datetime(2026, 3, 29, 20, 0, tzinfo=UTC), "Europe/London", 6, 18)
    assert end == datetime(2026, 3, 29, 17, 0, tzinfo=UTC)
    assert start == datetime(2026, 3, 22, 18, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=167)
    # The same instant on a Cairo clock is a different send moment entirely.
    cairo = week_window(datetime(2026, 3, 29, 20, 0, tzinfo=UTC), "Africa/Cairo", 6, 18)
    assert cairo[1] == datetime(2026, 3, 29, 16, 0, tzinfo=UTC)  # UTC+2
    # And the autumn change gives a 169-hour window.
    start, end = week_window(datetime(2026, 10, 25, 20, 0, tzinfo=UTC), "Europe/London", 6, 18)
    assert end - start == timedelta(hours=169)


def test_a_send_hour_that_does_not_exist_lands_on_a_real_instant():
    # 01:30 never happens in London on 29 Mar 2026.
    _start, end = week_window(datetime(2026, 3, 29, 12, 0, tzinfo=UTC), "Europe/London", 6, 1)
    assert end == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)


@pytest.mark.parametrize("weekday,hour", [(7, 9), (-1, 9), (0, 24), (0, -1)])
def test_an_impossible_send_time_is_refused(weekday, hour):
    with pytest.raises(ValueError):
        week_window(SEND_NOW, None, weekday, hour)


# ------------------------------------------------------------------- the world


async def _world(client, tutor, group, student, subject, *, exam=date(2026, 12, 6)):
    """One class of one learner with the week's evidence: a plan (3 lessons this
    week, 1 recorded; Bonding next), the register, homework in every state, marks,
    readiness a week apart and a review queue entry. Returns the ids."""
    sid, gid = student["user"]["id"], group["id"]
    await set_boundaries(subject["id"])
    ch = await make_chapters(subject)
    await make_plan(
        group,
        tutor,
        [
            (ch["c1"], date(2026, 10, 1), time(9, 0)),  # last week, not recorded
            (ch["c1"], date(2026, 10, 5), time(9, 0)),  # Mon: taught
            (ch["c1"], date(2026, 10, 7), time(9, 0)),  # Wed: not recorded
            (ch["c1"], date(2026, 10, 9), time(9, 0)),  # Fri: not recorded
            (ch["c2"], date(2026, 10, 14), time(9, 0)),  # next week
        ],
        exam=exam,
    )
    async with async_session() as s:
        org = await org_id(s)
        await s.execute(update(GroupMember).values(created_at=LONG_AGO))

        def lesson(day, notes=None):
            row = Lesson(organization_id=org, group_id=gid, date=day, notes=notes)
            s.add(row)
            return row

        mon, tue = lesson(date(2026, 10, 5), notes=SENTINEL), lesson(date(2026, 10, 6))
        lesson(date(2026, 10, 7))  # nobody marked
        lesson(date(2026, 10, 2))  # last week
        await s.flush()
        slot = await s.scalar(select(PlanSlot).where(PlanSlot.scheduled_date == date(2026, 10, 5)))
        slot.lesson_id = mon.id
        for row, state in ((mon, AttendanceState.present), (tue, AttendanceState.absent)):
            s.add(
                LessonAttendance(
                    organization_id=org,
                    lesson_id=row.id,
                    student_id=sid,
                    state=state,
                    source=AttendanceSource.tutor,
                    recorded_at=SEND_NOW,
                )
            )
        s.add(LessonObservation(lesson_id=mon.id, student_id=sid, body=SENTINEL, topic_id=None))

        def hw(title, due, created):
            return publish_assignment(
                s,
                group_id=gid,
                subject_id=subject["id"],
                organization_id=org,
                title=title,
                due_at=due,
                created_at=created,
                topic_ids=(subject["topic1"],),
            )

        a = await hw("A", at(8, 12), at(5))  # set this week, handed in late
        b = await hw("B", at(8, 20), at(1, 9, 9))  # old, handed in on time
        await hw("C", None, at(6))  # set this week, no deadline
        await hw("E", at(3), at(1, 9, 9))  # overdue, nothing handed in
        f = await hw("F", None, at(1, 9, 9))  # waiting for the tutor, old
        done = SubmissionStatus.finalized
        sub_a = await submit_work(
            s, assignment=a, student_id=sid, status=done, submitted_at=at(9), finalized_at=at(10)
        )
        await submit_work(
            s,
            assignment=b,
            student_id=sid,
            status=SubmissionStatus.auto_finalized,
            submitted_at=at(8),
        )
        await submit_work(
            s,
            assignment=f,
            student_id=sid,
            status=SubmissionStatus.needs_review,
            submitted_at=at(2, 10, 9),
            typed_answer=SENTINEL,
            ai_error=SENTINEL,
        )
        q_id = await s.scalar(
            select(AssignmentQuestion.id).where(AssignmentQuestion.assignment_id == a.id)
        )
        s.add(
            QuestionMark(
                submission_id=sub_a.id,
                question_id=q_id,
                ai_feedback=SENTINEL,
                final_feedback=SENTINEL,
                ai_transcription=SENTINEL,
                ai_marks=1,
                final_marks=1,
            )
        )
        await s.commit()
    async with async_session() as s:
        await write_v2_snapshot(
            s,
            student_id=sid,
            subject_id=subject["id"],
            score=40.0,
            predicted_grade="4",
            created_at=at(30, 10, 9),
        )
        await write_v2_snapshot(
            s,
            student_id=sid,
            subject_id=subject["id"],
            score=55.0,
            predicted_grade="5",
            topics={subject["topic1"]: (30.0, FactorConfidence.high)},
            created_at=at(10),
        )
        await s.commit()
    return {"c1": ch["c1"], "c2": ch["c2"], "t2": ch["t2"], "org": org}


async def _as(user_id):
    async with async_session() as s:
        return await s.get(User, user_id)


async def _tutor_facts(tutor, window=WINDOW):
    async with async_session() as s:
        return await build_tutor_facts(s, await s.get(User, tutor["user"]["id"]), window)


async def _student_facts(student, window=WINDOW):
    async with async_session() as s:
        return await build_student_facts(s, await s.get(User, student["user"]["id"]), window)


async def _parent(student, email="mum@example.com"):
    async with async_session() as s:
        parent = await make_user(
            s,
            organization_id=await org_id(s),
            role=UserRole.parent,
            name="Mum",
            email=email,
        )
        await link_parent(s, parent.id, student["user"]["id"])
        await s.commit()
        return parent.id


async def _parent_facts(parent_id, window=WINDOW):
    async with async_session() as s:
        return await build_parent_facts(s, await s.get(User, parent_id), window)


# ----------------------------------------------------------------- the tutor


async def test_tutor_facts_lead_with_the_plan_position(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    out = await _tutor_facts(tutor)
    (cls,) = out.classes
    assert (cls.group_name, cls.subject_name) == ("Chem Y10", "Chemistry")
    plan = cls.plan
    assert plan is not None
    assert plan.this_week_chapter == facts.ChapterRef("C1", "Atoms")
    assert plan.next_chapter == facts.ChapterRef("C2", "Bonding")
    assert (plan.lessons_planned_this_week, plan.lessons_taught_this_week) == (3, 1)
    # Last Thursday's, Wednesday's and Friday's lessons have no record against them.
    assert plan.lessons_behind == 3 and plan.lessons_ahead == 0
    assert plan.weeks_to_exam == 8  # 56 days from the window's end
    assert plan.next_chapter_homework_set is False  # the homework is on an unchaptered topic


async def test_the_next_chapter_with_homework_set_is_reported_as_set(
    client, tutor, group, student, subject
):
    world = await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        await publish_assignment(
            s,
            group_id=group["id"],
            subject_id=subject["id"],
            organization_id=world["org"],
            topic_ids=(world["t2"],),
        )
        await s.commit()
    plan = (await _tutor_facts(tutor)).classes[0].plan
    assert plan is not None and plan.next_chapter_homework_set is True


async def test_a_class_with_no_accepted_plan_has_no_plan_facts_not_zeroes(
    client, tutor, group, student, subject
):
    await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        await s.execute(update(TeachingPlan).values(status="draft"))
        await s.commit()
    out = await _tutor_facts(tutor)
    assert out.classes[0].plan is None


async def test_a_plan_with_a_passed_exam_date_has_no_weeks_to_exam(
    client, tutor, group, student, subject
):
    await _world(client, tutor, group, student, subject, exam=date(2026, 10, 1))
    plan = (await _tutor_facts(tutor)).classes[0].plan
    assert plan is not None and plan.weeks_to_exam is None


async def test_tutor_facts_carry_the_weeks_evidence(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    out = await _tutor_facts(tutor)
    cls = out.classes[0]
    assert cls.attendance == facts.AttendanceFacts(
        lessons_held=3, present=1, absent=1, not_taken=1, rate=0.5
    )
    # A set this week and C (no deadline): 2 set. A late, B on time: 2 handed in.
    # E fell due before the window and nobody handed it in: 1 missing. F and C
    # have no deadline and can never be missing.
    assert cls.homework == facts.HomeworkFacts(set_count=2, handed_in_count=2, missing_count=1)
    assert cls.punctuality == facts.Punctuality(on_time=1, late=1)
    assert out.marked == facts.MarkedFacts(marked=2, auto_finalized=1)
    assert out.review_queue == 1
    assert cls.readiness_direction == "up" and cls.readiness_compared_count == 1
    assert cls.weak_topics == (facts.TopicCount("Atomic structure", 1),)
    assert [(v.status, v.learners) for v in cls.verdicts] == [("needs_attention", 1)]


async def test_a_quiet_week_is_absent_not_zero(client, tutor, group, student, subject):
    # A class with a learner and nothing else: no lessons, no homework, no
    # snapshots, no marks.
    out = await _tutor_facts(tutor)
    cls = out.classes[0]
    assert cls.attendance is None and cls.homework is None and cls.punctuality is None
    assert cls.plan is None and cls.readiness_direction is None and cls.weak_topics == ()
    assert [v.status for v in cls.verdicts] == ["not_enough_data"]
    assert out.marked is None


async def test_a_tutor_with_no_classes_gets_an_empty_fact_set(client, tutor):
    out = await _tutor_facts(tutor)
    assert out.classes == () and out.marked is None and out.review_queue == 0


async def test_nothing_outside_the_window_is_counted(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    # The week before: the lesson on the 2nd belongs to it, nothing was set, and
    # E (due the 3rd, never handed in) is already overdue at its close.
    out = await _tutor_facts(tutor, week_window(at(4, 18), None, 6, 18))
    cls = out.classes[0]
    assert cls.attendance == facts.AttendanceFacts(
        lessons_held=1, present=0, absent=0, not_taken=1, rate=None
    )
    assert cls.homework == facts.HomeworkFacts(set_count=0, handed_in_count=0, missing_count=1)
    assert cls.punctuality is None and out.marked is None


async def test_punctuality_is_in_the_tutor_variant_only(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    parent_id = await _parent(student)
    assert _has_field(facts.TutorClassFacts, "punctuality")
    for cls in (
        facts.StudentFacts,
        facts.StudentClassFacts,
        facts.ParentFacts,
        facts.ParentChildFacts,
        facts.ParentClassFacts,
        facts.HomeworkFacts,
    ):
        assert not _has_field(cls, "punctuality") and not _has_field(cls, "late")
    assert "late" not in json.dumps(
        dataclasses.asdict(await _student_facts(student)), default=str
    ).replace('"late_', "")
    assert "punctuality" not in json.dumps(
        dataclasses.asdict(await _parent_facts(parent_id)), default=str
    )


def _has_field(cls, name):
    return name in {f.name for f in dataclasses.fields(cls)}


# --------------------------------------------------------------- the student


async def test_student_facts_are_their_own_week(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    out = await _student_facts(student)
    assert out.student_name == "Sara"
    (cls,) = out.classes
    assert (cls.subject_name, cls.verdict) == ("Chemistry", "needs_attention")
    assert (cls.readiness_score, cls.predicted_grade, cls.readiness_direction) == (55.0, "5", "up")
    assert cls.weak_topics == ("Atomic structure",)
    assert cls.this_week_chapter == facts.ChapterRef("C1", "Atoms")
    assert cls.next_chapter == facts.ChapterRef("C2", "Bonding")
    assert cls.attendance is not None and (cls.attendance.present, cls.attendance.absent) == (1, 1)
    assert cls.homework == facts.HomeworkFacts(set_count=2, handed_in_count=2, missing_count=1)
    assert out.marked == facts.MarkedFacts(marked=2, auto_finalized=1)
    # The exam date is the tutor's alone (AV-19).
    assert not _has_field(facts.StudentClassFacts, "weeks_to_exam")


async def test_a_learner_with_no_snapshot_has_no_grade_not_a_zero(
    client, tutor, group, student, subject
):
    out = await _student_facts(student)
    (cls,) = out.classes
    assert cls.verdict == "not_enough_data"
    assert cls.readiness_score is None and cls.predicted_grade is None
    assert cls.readiness_direction is None and cls.attendance is None and cls.homework is None


async def test_only_the_students_own_marks_and_register_count(
    client, tutor, group, student, subject
):
    world = await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        rival = await make_user(
            s, organization_id=world["org"], role=UserRole.student, name="Rival", email="r@x.io"
        )
        s.add(GroupMember(group_id=group["id"], student_id=rival.id, created_at=LONG_AGO))
        mon = await s.scalar(select(Lesson.id).where(Lesson.date == date(2026, 10, 5)))
        s.add(
            LessonAttendance(
                organization_id=world["org"],
                lesson_id=mon,
                student_id=rival.id,
                state=AttendanceState.absent,
                source=AttendanceSource.tutor,
                recorded_at=SEND_NOW,
            )
        )
        await s.commit()
    own = (await _student_facts(student)).classes[0]
    assert own.attendance is not None and own.attendance.absent == 1  # not 2
    both = (await _tutor_facts(tutor)).classes[0].attendance
    assert both is not None and both.absent == 2


# ---------------------------------------------------------------- the parent


async def test_parent_facts_are_the_report_without_topics_or_mistakes(
    client, tutor, group, student, subject
):
    await _world(client, tutor, group, student, subject)
    parent_id = await _parent(student)
    out = await _parent_facts(parent_id)
    (child,) = out.children
    assert child.child_name == "Sara"
    (cls,) = child.classes
    assert (cls.verdict, cls.predicted_grade, cls.readiness_direction) == (
        "needs_attention",
        "5",
        "up",
    )
    assert cls.chapter == facts.ChapterRef("C1", "Atoms")
    assert cls.attendance is not None and cls.attendance.present == 1
    assert cls.homework == facts.HomeworkFacts(set_count=2, handed_in_count=2, missing_count=1)
    names = {f.name for f in dataclasses.fields(facts.ParentClassFacts)}
    assert not names & {"weak_topics", "topics", "mistakes", "next_chapter", "marked"}
    blob = json.dumps(dataclasses.asdict(out), default=str)
    assert "Atomic structure" not in blob  # the weak topic's title never travels


async def test_a_parent_with_no_linked_child_gets_no_blocks(client, tutor, group, student):
    async with async_session() as s:
        parent = await make_user(
            s,
            organization_id=await org_id(s),
            role=UserRole.parent,
            name="Nobody",
            email="n@x.io",
        )
        await s.commit()
        pid = parent.id
    assert (await _parent_facts(pid)).children == ()


async def test_each_child_gets_their_own_block(client, tutor, group, student, subject):
    await _world(client, tutor, group, student, subject)
    parent_id = await _parent(student)
    async with async_session() as s:
        org = await org_id(s)
        sibling = await make_user(
            s, organization_id=org, role=UserRole.student, name="Adam", email="adam@x.io"
        )
        await link_parent(s, parent_id, sibling.id)
        s.add(GroupMember(group_id=group["id"], student_id=sibling.id, created_at=LONG_AGO))
        await s.commit()
    out = await _parent_facts(parent_id)
    assert [c.child_name for c in out.children] == ["Adam", "Sara"]
    assert out.children[0].classes[0].verdict == "not_enough_data"


# --------------------------------------------------------- tenancy (negative)


async def test_another_organizations_rows_never_reach_any_variant(
    client, tutor, group, student, subject
):
    world = await _world(client, tutor, group, student, subject)
    parent_id = await _parent(student)
    async with async_session() as s:
        rival_subject = await other_org_subject(s, code="9RIV", name="Physics")
        rival_org = rival_subject.organization_id
        rival_tutor = await make_user(
            s, organization_id=rival_org, role=UserRole.tutor, name="Rival", email="rt@x.io"
        )
        rival_kid = await make_user(
            s, organization_id=rival_org, role=UserRole.student, name="Rival Kid", email="rk@x.io"
        )
        rival_group = Group(
            organization_id=rival_org,
            tutor_id=rival_tutor.id,
            subject_id=rival_subject.id,
            name="Rival class",
        )
        s.add(rival_group)
        await s.flush()
        s.add(GroupMember(group_id=rival_group.id, student_id=rival_kid.id, created_at=LONG_AGO))
        s.add(Lesson(organization_id=rival_org, group_id=rival_group.id, date=date(2026, 10, 6)))
        await publish_assignment(
            s,
            group_id=rival_group.id,
            subject_id=rival_subject.id,
            organization_id=rival_org,
            created_at=at(6),
        )
        # The two tenants are bridged by rows that should never be trusted: our
        # student also enrolled in their class, our parent also linked to theirs.
        s.add(GroupMember(group_id=rival_group.id, student_id=student["user"]["id"]))
        await link_parent(s, parent_id, rival_kid.id)
        rival_parent = await make_user(
            s, organization_id=rival_org, role=UserRole.parent, name="RP", email="rp@x.io"
        )
        await link_parent(s, rival_parent.id, student["user"]["id"])
        await s.commit()
        rival = {"tutor": rival_tutor.id, "parent": rival_parent.id, "org": world["org"]}

    ours = await _tutor_facts(tutor)
    assert [c.group_name for c in ours.classes] == ["Chem Y10"]
    assert ours.classes[0].attendance is not None and ours.classes[0].attendance.lessons_held == 3

    student_out = await _student_facts(student)
    assert [c.group_name for c in student_out.classes] == ["Chem Y10"]

    assert [c.child_name for c in (await _parent_facts(parent_id)).children] == ["Sara"]
    # The other tenant's parent is linked to our child, and reads nothing of ours.
    assert (await _parent_facts(rival["parent"])).children == ()
    # And their tutor sees their class only.
    theirs = await _tutor_facts({"user": {"id": rival["tutor"]}})
    assert [c.group_name for c in theirs.classes] == ["Rival class"]
    assert theirs.classes[0].plan is None and theirs.marked is None


async def test_each_builder_refuses_the_wrong_role(client, tutor, group, student):
    parent_id = await _parent(student)
    async with async_session() as s:
        with pytest.raises(ValueError):
            await build_tutor_facts(s, await s.get(User, student["user"]["id"]), WINDOW)
        with pytest.raises(ValueError):
            await build_student_facts(s, await s.get(User, parent_id), WINDOW)
        with pytest.raises(ValueError):
            await build_parent_facts(s, await s.get(User, tutor["user"]["id"]), WINDOW)


# ------------------------------------------------------------------- F9


_ALLOWED_TEXT_FIELDS = {
    # Names someone with authority over the account typed, or syllabus values.
    "group_name",
    "subject_name",
    "student_name",
    "child_name",
    "code",
    "title",
    "weak_topics",
    "predicted_grade",
}


def _carries_str(annotation) -> bool:
    if annotation is str:
        return True
    return any(_carries_str(a) for a in typing.get_args(annotation) if a is not Ellipsis)


def test_f9_the_fact_types_have_no_free_text_field():
    """Structural: every `str`-typed field of every fact type is on the allowlist
    of names and syllabus values. Adding a field that could hold a sentence
    (`feedback`, `notes`, `summary`) fails here, in review, before it fails in a
    parent's inbox."""
    types = [
        v
        for v in vars(facts).values()
        if dataclasses.is_dataclass(v)
        and v.__module__ == facts.__name__
        and not v.__name__.startswith("_")
    ]
    assert len(types) >= 15
    offenders = {
        f"{t.__name__}.{name}"
        for t in types
        for name, hint in typing.get_type_hints(t).items()
        if _carries_str(hint) and name not in _ALLOWED_TEXT_FIELDS
    }
    assert offenders == set()


async def test_f9_nothing_a_student_wrote_reaches_any_variant(
    client, tutor, group, student, subject
):
    """Behavioural: every column a student's words (or the AI's reasoning about
    them) can live in is seeded with a sentinel, and the produced facts, all three
    variants, are searched for it."""
    await _world(client, tutor, group, student, subject)
    parent_id = await _parent(student)
    async with async_session() as s:
        seeded = [
            (QuestionMark.ai_feedback, QuestionMark.final_feedback),
            (LessonObservation.body,),
            (Lesson.notes,),
        ]
        assert len(seeded) == 3  # the world seeds them all; this guards the guard
        assert await s.scalar(select(QuestionMark.ai_feedback)) == SENTINEL
    blobs = [
        json.dumps(dataclasses.asdict(out), default=str)
        for out in (
            await _tutor_facts(tutor),
            await _student_facts(student),
            await _parent_facts(parent_id),
        )
    ]
    for blob in blobs:
        assert "ZQXJ" not in blob and SENTINEL not in blob
    # The facts are not empty: the scan above is not passing on a blank page.
    assert all(len(blob) > 200 for blob in blobs)


# ------------------------------------------------------------ review fixes


def test_consecutive_windows_tile_across_the_spring_clock_change():
    sundays = [datetime(2026, 3, d, 20, 0, tzinfo=UTC) for d in (15, 22, 29)] + [
        datetime(2026, 4, 5, 20, 0, tzinfo=UTC)
    ]
    windows = [week_window(n, "Europe/London", 6, 18) for n in sundays]
    for (_s1, end), (start, _e2) in zip(windows, windows[1:], strict=False):
        assert end == start  # no gap, no overlap


async def test_lessons_behind_is_unknown_when_the_class_has_no_dated_lessons_yet(
    client, tutor, group, student, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], date(2026, 10, 20), time(9, 0))])
    plan = (await _tutor_facts(tutor)).classes[0].plan
    assert plan is not None and plan.lessons_behind is None  # not 0 behind
    assert plan.lessons_planned_this_week == 0


async def test_a_slot_after_the_send_hour_today_belongs_to_next_week(
    client, tutor, group, student, subject
):
    ch = await make_chapters(subject)
    await make_plan(
        group,
        tutor,
        [
            (ch["c1"], date(2026, 10, 11), time(10, 0)),  # before the send: this week
            (ch["c2"], date(2026, 10, 11), time(20, 0)),  # after it: next week's
        ],
    )
    plan = (await _tutor_facts(tutor)).classes[0].plan
    assert plan is not None
    assert plan.this_week_chapter == facts.ChapterRef("C1", "Atoms")
    assert plan.next_chapter == facts.ChapterRef("C2", "Bonding")
    assert plan.lessons_planned_this_week == 1


async def test_a_lesson_still_to_finish_at_the_send_is_not_held(
    client, tutor, group, student, subject
):
    await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        s.add(
            Lesson(
                organization_id=await org_id(s),
                group_id=group["id"],
                date=date(2026, 10, 11),
                start_time=time(17, 30),
                duration_min=60,
            )
        )
        await s.commit()
    att = (await _tutor_facts(tutor)).classes[0].attendance
    assert att is not None and att.lessons_held == 3 and att.not_taken == 1


async def test_what_arrives_after_the_window_is_not_in_it(client, tutor, group, student, subject):
    world = await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        e = await s.scalar(select(Assignment).where(Assignment.title == "E"))
        await submit_work(
            s,
            assignment=e,
            student_id=student["user"]["id"],
            status=SubmissionStatus.submitted,
            submitted_at=at(12),
        )
        await publish_assignment(
            s,
            group_id=group["id"],
            subject_id=subject["id"],
            organization_id=world["org"],
            created_at=at(12),
        )
        await s.commit()
    cls = (await _tutor_facts(tutor)).classes[0]
    # E is still missing at the close, and the later hand-in and assignment are
    # next week's facts.
    assert cls.homework == facts.HomeworkFacts(set_count=2, handed_in_count=2, missing_count=1)
    assert (await _student_facts(student)).classes[0].homework == cls.homework


async def test_marked_counts_when_marks_settled_and_only_the_tutors_classes(
    client, tutor, group, student, subject
):
    world = await _world(client, tutor, group, student, subject)
    async with async_session() as s:
        # Settled after the window closed: next week's.
        late = await publish_assignment(
            s, group_id=group["id"], subject_id=subject["id"], organization_id=world["org"]
        )
        await submit_work(
            s,
            assignment=late,
            student_id=student["user"]["id"],
            status=SubmissionStatus.auto_finalized,
            submitted_at=at(10),
            finalized_at=at(12),
        )
        # Homework set in a colleague's class, same organization.
        colleague = await make_user(
            s, organization_id=world["org"], role=UserRole.tutor, name="Col", email="c@x.io"
        )
        theirs = Group(
            organization_id=world["org"],
            tutor_id=colleague.id,
            subject_id=subject["id"],
            name="Theirs",
        )
        s.add(theirs)
        await s.flush()
        elsewhere = await publish_assignment(
            s, group_id=theirs.id, subject_id=subject["id"], organization_id=world["org"]
        )
        await submit_work(
            s,
            assignment=elsewhere,
            student_id=student["user"]["id"],
            status=SubmissionStatus.finalized,
            submitted_at=at(9),
            finalized_at=at(9),
        )
        await s.commit()
    assert (await _tutor_facts(tutor)).marked == facts.MarkedFacts(marked=2, auto_finalized=1)
    # The learner's own count is theirs whichever class set it.
    assert (await _student_facts(student)).marked == facts.MarkedFacts(3, 1)


async def test_a_class_without_a_verdict_is_skipped_not_fatal(
    client, tutor, group, student, subject, monkeypatch, caplog
):
    async def nobody(session, group, snapshots=None):
        return {}

    monkeypatch.setattr(facts, "class_verdicts", nobody)
    with caplog.at_level("WARNING"):
        out = await _student_facts(student)
    assert out.classes == () and "has no verdict" in caplog.text


async def test_no_boundaries_means_no_grade_even_with_a_snapshot(
    client, tutor, group, student, subject
):
    await set_boundaries(subject["id"], [])
    async with async_session() as s:
        await write_v2_snapshot(
            s,
            student_id=student["user"]["id"],
            subject_id=subject["id"],
            score=55.0,
            predicted_grade="5",
            created_at=at(10),
        )
        await s.commit()
    cls = (await _student_facts(student)).classes[0]
    assert cls.verdict == "not_enough_data"
    assert cls.predicted_grade is None and cls.readiness_score is None


async def test_an_unloadable_zone_is_logged_and_read_as_utc(client, tutor, caplog):
    async with async_session() as s:
        org = await org_id(s)
        (await s.get(Organization, org)).timezone = "Not/AZone"
        await s.commit()
        with caplog.at_level("WARNING"):
            window = await facts.organization_week_window(s, org, SEND_NOW, 6, 18)
            clock = await facts._clock(s, org, window)
    assert window == WINDOW and clock.zone is None
    assert f"organization {org} time zone 'Not/AZone'" in caplog.text
    async with async_session() as s:
        with pytest.raises(ValueError):
            await facts._clock(s, 9999, WINDOW)


async def test_a_link_that_does_not_resolve_is_counted_and_logged(
    client, tutor, group, student, subject, caplog
):
    parent_id = await _parent(student)
    async with async_session() as s:
        rival = (await other_org_subject(s, code="9RIV")).organization_id
        kid = await make_user(
            s, organization_id=rival, role=UserRole.student, name="K", email="k@x.io"
        )
        await link_parent(s, parent_id, kid.id)
        await s.commit()
    with caplog.at_level("WARNING"):
        out = await _parent_facts(parent_id)
    assert out.dropped_links == 1 and len(out.children) == 1
    assert "did not resolve" in caplog.text
    assert (await _parent_facts(await _parent(student, "dad@example.com"))).dropped_links == 0


async def test_the_tutor_path_is_flat_in_learners_and_bounded_per_class(
    client, tutor, group, student, subject
):
    await _world(client, tutor, group, student, subject)

    async def count() -> int:
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            await _tutor_facts(tutor)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        return len(queries)

    one_class = await count()
    async with async_session() as s:
        org = await org_id(s)
        for i in range(5):  # five more learners in the same class
            kid = await make_user(
                s, organization_id=org, role=UserRole.student, name=f"L{i}", email=f"l{i}@x.io"
            )
            s.add(GroupMember(group_id=group["id"], student_id=kid.id))
        await s.commit()
    assert await count() == one_class  # no query per learner
    async with async_session() as s:
        org = await org_id(s)
        for i in range(3):
            g = Group(
                organization_id=org,
                tutor_id=tutor["user"]["id"],
                subject_id=subject["id"],
                name=f"More {i}",
            )
            s.add(g)
            await s.flush()
            s.add(GroupMember(group_id=g.id, student_id=student["user"]["id"]))
            s.add(Lesson(organization_id=org, group_id=g.id, date=date(2026, 10, 6)))
        await s.commit()
    assert await count() - one_class <= 3 * 12  # a constant per class, not per row
