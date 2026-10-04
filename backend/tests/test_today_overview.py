"""The tutor Overview aggregates (coherence B): week at a glance, today's agenda,
class cards, remark requests.

The clock is pinned by calling the service with `now`: Wednesday 2026-10-07
12:00 UTC, so the week is Mon 5 - Sun 11 October and "today" is the 7th. The org
has no timezone in these tests, so the zone is UTC.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event, select, update

from app.db import async_session, engine
from app.models import (
    Assignment,
    AttendanceSource,
    AttendanceState,
    FactorConfidence,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    PlanSlot,
    QuestionMark,
    RemarkRequest,
    Submission,
    SubmissionStatus,
    User,
)
from app.services.today_overview import READINESS_DROP_THRESHOLD, build_overview
from tests.factories import write_v2_snapshot
from tests.plan_world import add_timetable, make_chapters, make_plan
from tests.test_attendance import _other_tutor

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MON, TUE, WED, THU, FRI = (date(2026, 10, d) for d in (5, 6, 7, 8, 9))
LONG_AGO = datetime(2020, 1, 1, tzinfo=timezone.utc)


async def _overview(tutor, now=NOW):
    async with async_session() as s:
        user = await s.get(User, tutor["user"]["id"])
        return await build_overview(s, user, now)


async def _lesson(group_id, day, *, start=None, minutes=60, org_id=None):
    async with async_session() as s:
        org = org_id or await s.scalar(select(Group.organization_id).where(Group.id == group_id))
        lesson = Lesson(
            organization_id=org, group_id=group_id, date=day, start_time=start, duration_min=minutes
        )
        s.add(lesson)
        await s.commit()
        return lesson.id


async def _mark(lesson_id, student_id, state, org_id):
    async with async_session() as s:
        s.add(
            LessonAttendance(
                organization_id=org_id,
                lesson_id=lesson_id,
                student_id=student_id,
                state=state,
                source=AttendanceSource.tutor,
                recorded_at=NOW,
            )
        )
        await s.commit()


async def _joined_long_ago():
    async with async_session() as s:
        await s.execute(update(GroupMember).values(created_at=LONG_AGO))
        await s.commit()


async def _org(group):
    async with async_session() as s:
        return await s.scalar(select(Group.organization_id).where(Group.id == group["id"]))


async def _add_student(client, tutor, group, name, username):
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": name, "username": username, "password": "password123"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- week strip


async def test_a_tutor_with_no_classes_gets_an_honest_empty_overview(client, tutor):
    resp = await client.get("/api/v1/today/overview", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agenda"] == [] and body["classes"] == [] and body["remarks"] == []
    week = body["week"]
    assert week["attendance_rate"] is None
    assert (week["lessons_planned"], week["lessons_taught"]) == (0, 0)


async def test_attendance_rate_excludes_not_taken_and_states_it(client, tutor, group, student):
    await _joined_long_ago()
    sid, org = student["user"]["id"], await _org(group)
    mon = await _lesson(group["id"], MON)
    tue = await _lesson(group["id"], TUE)
    await _lesson(group["id"], WED, start=time(9, 0))  # ended, nobody marked
    await _lesson(group["id"], WED, start=time(15, 0))  # still to come today: not counted
    await _lesson(group["id"], MON - timedelta(days=7))  # last week: not this week's
    await _mark(mon, sid, AttendanceState.present, org)
    await _mark(tue, sid, AttendanceState.absent, org)

    week = (await _overview(tutor)).week
    assert (week.attendance_present, week.attendance_absent) == (1, 1)
    # The ended, unmarked lesson is "not taken" and out of the rate; the one still
    # ahead of us today and last week's are not this week's figure at all.
    assert week.attendance_not_taken == 1
    assert week.attendance_rate == pytest.approx(0.5)


async def test_nothing_marked_this_week_is_null_not_zero_percent(client, tutor, group, student):
    await _joined_long_ago()
    await _lesson(group["id"], TUE)
    week = (await _overview(tutor)).week
    assert week.attendance_rate is None
    assert (week.attendance_present, week.attendance_absent) == (0, 0)
    assert week.attendance_not_taken == 1


async def test_lessons_planned_and_taught_from_slots_and_recorded_lessons(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    _plan, slots = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], MON, time(9, 0)),  # taught
            (ch["c1"], WED, time(9, 0)),  # planned, not taught
            (ch["c1"], THU, time(9, 0)),  # cancelled: not a lesson
            (ch["c1"], FRI, time(9, 0)),  # planned, ahead
            (ch["c1"], MON - timedelta(days=7), time(9, 0)),  # last week
        ],
    )
    mon_lesson = await _lesson(group["id"], MON)
    adhoc = await _lesson(group["id"], TUE)
    assert adhoc
    async with async_session() as s:
        await s.execute(
            update(PlanSlot).where(PlanSlot.id == slots[0]).values(lesson_id=mon_lesson)
        )
        await s.execute(update(PlanSlot).where(PlanSlot.id == slots[2]).values(cancelled_at=NOW))
        await s.commit()

    week = (await _overview(tutor)).week
    # Mon (taught), Wed, Fri from the plan + the ad-hoc Tuesday lesson; the
    # cancelled Thursday and last week's slot are not this week's lessons.
    assert (week.lessons_planned, week.lessons_taught) == (4, 2)


async def test_another_tutors_class_is_excluded_from_every_aggregate(
    client, tutor, group, student, subject
):
    await _joined_long_ago()
    org = await _org(group)
    _headers, other = await _other_tutor(client, "other@example.com")
    async with async_session() as s:
        theirs = Group(
            organization_id=org, tutor_id=other["id"], subject_id=subject["id"], name="Theirs"
        )
        s.add(theirs)
        await s.commit()
        theirs_id = theirs.id
    ch = await make_chapters(subject)
    await make_plan({"id": theirs_id}, tutor, [(ch["c1"], WED, time(9, 0))])
    await _lesson(theirs_id, TUE)

    ov = await _overview(tutor)
    assert [c.group_id for c in ov.classes] == [group["id"]]
    assert ov.agenda == []
    assert (ov.week.lessons_planned, ov.week.lessons_taught) == (0, 0)
    assert ov.week.attendance_not_taken == 0


# ------------------------------------------------------------------- readiness


async def _snap(student_id, subject_id, score, days_ago, topics=None):
    async with async_session() as s:
        await write_v2_snapshot(
            s,
            student_id=student_id,
            subject_id=subject_id,
            score=score,
            created_at=NOW - timedelta(days=days_ago),
            topics=topics,
        )
        await s.commit()


async def test_readiness_drop_needs_history_and_clears_the_threshold(
    client, tutor, group, student, subject
):
    sara = student["user"]["id"]
    omar = (await _add_student(client, tutor, group, "Omar", "omar"))["id"]
    aya = (await _add_student(client, tutor, group, "Aya", "aya"))["id"]
    new = (await _add_student(client, tutor, group, "Newbie", "newbie"))["id"]
    await _snap(sara, subject["id"], 70.0, 10)
    await _snap(sara, subject["id"], 60.0, 1)  # -10: dropped
    await _snap(omar, subject["id"], 70.0, 10)
    await _snap(omar, subject["id"], 70.0 - (READINESS_DROP_THRESHOLD - 1), 1)  # under threshold
    await _snap(aya, subject["id"], 50.0, 10)
    await _snap(aya, subject["id"], 62.0, 1)  # up
    await _snap(new, subject["id"], 40.0, 1)  # no snapshot a week old: not compared

    ov = await _overview(tutor)
    assert ov.week.readiness_drop_count == 1
    assert ov.week.readiness_compared_count == 3  # the newcomer is excluded, not a 0
    card = ov.classes[0]
    assert card.readiness_compared_count == 3
    assert card.attention is not None and card.attention.kind == "readiness_drop"
    assert card.attention.student_names == ["Sara"]


async def test_a_no_evidence_snapshot_a_week_ago_is_not_a_zero_to_drop_from(
    client, tutor, group, student, subject
):
    sid = student["user"]["id"]
    await _snap(sid, subject["id"], None, 10)  # a run that found no evidence
    await _snap(sid, subject["id"], 10.0, 1)
    week = (await _overview(tutor)).week
    assert (week.readiness_drop_count, week.readiness_compared_count) == (0, 0)


async def test_no_snapshot_history_means_no_direction_and_no_count(
    client, tutor, group, student, subject
):
    await _snap(student["user"]["id"], subject["id"], 55.0, 1)
    ov = await _overview(tutor)
    assert ov.week.readiness_drop_count == 0 and ov.week.readiness_compared_count == 0
    assert ov.classes[0].readiness_direction is None
    assert ov.classes[0].attention is None


async def test_class_direction_follows_students_with_both_ends(
    client, tutor, group, student, subject
):
    sid = student["user"]["id"]
    await _snap(sid, subject["id"], 50.0, 10)
    await _snap(sid, subject["id"], 58.0, 1)
    assert (await _overview(tutor)).classes[0].readiness_direction == "up"


async def test_attention_names_the_students_and_the_topic(client, tutor, group, student, subject):
    omar = (await _add_student(client, tutor, group, "Omar", "omar"))["id"]
    fine = (await _add_student(client, tutor, group, "Fine", "fine"))["id"]
    weak = {subject["topic2"]: (30.0, FactorConfidence.high)}
    await _snap(student["user"]["id"], subject["id"], 50.0, 1, topics=weak)
    await _snap(omar, subject["id"], 52.0, 1, topics=weak)
    await _snap(
        fine, subject["id"], 80.0, 1, topics={subject["topic2"]: (80.0, FactorConfidence.high)}
    )

    attention = (await _overview(tutor)).classes[0].attention
    assert attention is not None
    assert attention.kind == "weak_topic"
    assert attention.message == "Omar, Sara below 50% on 1.6 Ionic bonding"
    assert attention.topic_id == subject["topic2"]


async def test_a_low_confidence_topic_score_is_not_named(client, tutor, group, student, subject):
    weak = {subject["topic2"]: (30.0, FactorConfidence.low)}
    await _snap(student["user"]["id"], subject["id"], 50.0, 1, topics=weak)
    assert (await _overview(tutor)).classes[0].attention is None


# ---------------------------------------------------------------- class cards


async def test_plan_position_on_track_behind_and_none(client, tutor, group, subject):
    ch = await make_chapters(subject)
    # No plan at all.
    assert (await _overview(tutor)).classes[0].plan_state == "none"
    await make_plan(
        group,
        tutor,
        [
            (ch["c1"], MON, time(9, 0)),  # before today, nothing recorded -> behind
            (ch["c2"], FRI, time(9, 0)),
        ],
    )
    card = (await _overview(tutor)).classes[0]
    assert (card.plan_state, card.plan_missed) == ("behind", 1)
    assert card.attention is not None and card.attention.kind == "behind_plan"
    assert "1 planned lesson not recorded" in card.attention.message


async def test_on_track_names_the_chapter_of_the_next_lesson(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c2"], FRI, time(9, 0))])
    card = (await _overview(tutor)).classes[0]
    assert (card.plan_state, card.plan_chapter_code, card.plan_chapter_title) == (
        "on_track",
        "C2",
        "Bonding",
    )


async def test_last_lesson_attendance_counts_and_absence_of_one(client, tutor, group, student):
    await _joined_long_ago()
    sid, org = student["user"]["id"], await _org(group)
    assert (await _overview(tutor)).classes[0].last_lesson is None
    older = await _lesson(group["id"], MON - timedelta(days=10))
    latest = await _lesson(group["id"], TUE)
    await _mark(older, sid, AttendanceState.absent, org)
    await _mark(latest, sid, AttendanceState.present, org)
    # An unfinished lesson today with no marks is not "the last lesson".
    await _lesson(group["id"], WED, start=time(15, 0))

    last = (await _overview(tutor)).classes[0].last_lesson
    assert last is not None and last.lesson_id == latest
    assert (last.present, last.absent, last.not_taken) == (1, 0, 0)


async def test_last_lesson_with_nobody_marked_reports_not_taken(client, tutor, group, student):
    await _joined_long_ago()
    await _lesson(group["id"], TUE)
    last = (await _overview(tutor)).classes[0].last_lesson
    assert last is not None
    assert (last.present, last.absent, last.not_taken) == (0, 0, 1)


async def test_homework_out_counts_published_assignments_with_missing_handins(
    client, tutor, group, student, published_assignment
):
    card = (await _overview(tutor)).classes[0]
    assert (card.homework_out, card.homework_missing) == (1, 1)
    async with async_session() as s:
        work_id = await s.scalar(
            select(Assignment.work_id).where(Assignment.id == published_assignment["id"])
        )
        s.add(Submission(work_id=work_id, student_id=student["user"]["id"]))
        await s.commit()
    card = (await _overview(tutor)).classes[0]
    assert (card.homework_out, card.homework_missing) == (0, 0)


async def test_open_remark_requests_are_listed_with_the_students_reason(
    client, tutor, group, student, published_assignment
):
    async with async_session() as s:
        work_id = await s.scalar(
            select(Assignment.work_id).where(Assignment.id == published_assignment["id"])
        )
        sub = Submission(
            work_id=work_id, student_id=student["user"]["id"], status=SubmissionStatus.needs_review
        )
        s.add(sub)
        await s.flush()
        mark = QuestionMark(submission_id=sub.id, question_id=None, final_marks=1)
        s.add(mark)
        await s.flush()
        s.add(
            RemarkRequest(
                question_mark_id=mark.id,
                requested_by_id=student["user"]["id"],
                reason="I showed it",
            )
        )
        await s.commit()
        sub_id = sub.id
    ov = await _overview(tutor)
    assert [(r.submission_id, r.student_name, r.reason, r.group_name) for r in ov.remarks] == [
        (sub_id, "Sara", "I showed it", "Chem Y10")
    ]


# --------------------------------------------------------------------- agenda


async def test_agenda_rows_carry_plan_share_times_and_one_state(client, tutor, group, subject):
    ch = await make_chapters(subject, topics_in_c1=4)
    _plan, slots = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], WED, time(9, 0)),  # first half of C1's topics
            (ch["c1"], WED, time(15, 0)),  # second half
            (ch["c1"], THU, time(9, 0)),  # tomorrow: not on today's agenda
        ],
    )
    agenda = (await _overview(tutor)).agenda
    assert [a.slot_id for a in agenda] == [slots[0], slots[1]]
    first = agenda[0]
    assert (first.source, first.recorded, first.local_date) == ("plan", False, WED)
    assert first.chapter_code == "C1" and first.chapter_title == "Atoms"
    # Four topics over three lessons: [1, 2], [3], [4] — the one shared split.
    assert [t.code for t in first.topics] == ["9.1", "9.2"]
    assert [t.code for t in agenda[1].topics] == ["9.3"]
    assert first.starts_at == datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    assert first.ends_at == datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)


async def test_agenda_excludes_cancelled_and_shows_recorded_with_its_plan(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    _plan, slots = await make_plan(
        group,
        tutor,
        [(ch["c1"], WED, time(9, 0)), (ch["c1"], WED, time(11, 0)), (ch["c2"], WED, time(13, 0))],
    )
    lesson_id = await _lesson(group["id"], WED, start=time(9, 0))
    async with async_session() as s:
        await s.execute(update(PlanSlot).where(PlanSlot.id == slots[0]).values(lesson_id=lesson_id))
        await s.execute(update(PlanSlot).where(PlanSlot.id == slots[1]).values(cancelled_at=NOW))
        await s.commit()

    agenda = (await _overview(tutor)).agenda
    assert [(a.slot_id, a.lesson_id, a.recorded) for a in agenda] == [
        (slots[0], lesson_id, True),
        (slots[2], None, False),
    ]
    assert agenda[0].chapter_code == "C1"  # a recorded lesson still says what the plan covered


async def test_a_timetable_only_class_still_shows_its_lesson_today(client, tutor, group):
    await add_timetable(group, WED.weekday(), time(16, 30), 45)
    agenda = (await _overview(tutor)).agenda
    assert [(a.source, a.start_time, a.duration_min, a.slot_id) for a in agenda] == [
        ("timetable", time(16, 30), 45, None)
    ]
    # Another weekday's timetable slot is not that day's.
    assert (await _overview(tutor, NOW + timedelta(days=1))).agenda == []


async def test_a_plan_slot_with_no_start_time_has_no_invented_one(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], WED, None)])
    item = (await _overview(tutor)).agenda[0]
    assert (item.start_time, item.starts_at, item.ends_at) == (None, None, None)


# ------------------------------------------------------------------ API / cost


async def test_endpoint_is_tutor_gated_and_tutor_scoped(client, tutor, group, student):
    assert (await client.get("/api/v1/today/overview")).status_code == 401
    assert (
        await client.get("/api/v1/today/overview", headers=student["headers"])
    ).status_code == 403
    other_headers, _ = await _other_tutor(client, "other2@example.com")
    body = (await client.get("/api/v1/today/overview", headers=other_headers)).json()
    assert body["classes"] == []


async def test_query_count_is_flat_in_the_number_of_classes(client, tutor, subject):
    ch = await make_chapters(subject)

    def count():
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        return queries, lambda: event.remove(engine.sync_engine, "before_cursor_execute", before)

    async def make_class(name):
        resp = await client.post(
            "/api/v1/groups",
            json={"name": name, "subject_id": subject["id"]},
            headers=tutor["headers"],
        )
        group = resp.json()
        s1 = await _add_student(client, tutor, group, f"{name}-a", f"{name}a".lower())
        await _snap(s1["id"], subject["id"], 60.0, 10)
        await _snap(
            s1["id"],
            subject["id"],
            50.0,
            1,
            topics={subject["topic2"]: (20.0, FactorConfidence.high)},
        )
        await make_plan(group, tutor, [(ch["c1"], WED, time(9, 0)), (ch["c2"], FRI, None)])
        await _lesson(group["id"], TUE)
        await add_timetable(group, WED.weekday(), time(9, 0))
        return group

    await make_class("One")
    queries, stop = count()
    await _overview(tutor)
    stop()
    baseline = len(queries)
    for i in range(4):
        await make_class(f"More{i}")
    queries, stop = count()
    ov = await _overview(tutor)
    stop()
    assert len(ov.classes) == 5
    assert len(queries) == baseline, f"{len(queries)} queries for 5 classes vs {baseline} for 1"
