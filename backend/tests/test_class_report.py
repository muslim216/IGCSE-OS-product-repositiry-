"""The tutor's class report (task 8.6).

The clock is pinned by calling the service with `now`: Wednesday 2026-10-07 12:00
UTC in an organization with no timezone, so "today" is the 7th. The HTTP tests
cover only what the route adds: the gate and the tenancy.
"""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import update

from app.db import async_session
from app.models import (
    AttendanceState,
    FactorConfidence,
    Group,
    LessonTopic,
    MistakeSource,
    PlanSlot,
    ReadinessWeights,
    TeachingPlanStatus,
)
from app.schemas.class_report import ClassReport
from app.services.class_report import (
    attendance_rate,
    build_class_report,
    chapter_state,
    plan_position,
)
from app.services.mistake_rollup import rank_class_categories
from app.services.plan_progress import Progress
from tests.factories import (
    add_mistake,
    make_mistake_category,
    settled_submission,
    write_v2_snapshot,
)
from tests.plan_world import make_chapters, make_plan
from tests.test_attendance import _other_tutor
from tests.test_today_overview import (
    FRI,
    MON,
    NOW,
    TUE,
    WED,
    _joined_long_ago,
    _lesson,
    _mark,
    _org,
)

EXAM = date(2026, 12, 7)


async def _report(group_id, since=None) -> ClassReport:
    async with async_session() as s:
        group = await s.get(Group, group_id)
        return await build_class_report(s, group, now=NOW, since=since)


async def _link(slot_id, lesson_id):
    async with async_session() as s:
        await s.execute(update(PlanSlot).where(PlanSlot.id == slot_id).values(lesson_id=lesson_id))
        await s.commit()


# ------------------------------------------------------------------ pure parts


def test_position_is_absent_before_the_plan_reaches_a_lesson():
    assert plan_position(Progress(0, 0, 0, None, None), 0) is None
    assert plan_position(Progress(0, 0, 0, None, None), 2) is None


def test_behind_wins_over_ahead():
    assert plan_position(Progress(3, 2, 1, None, None), 4) == "behind"
    assert plan_position(Progress(3, 3, 0, None, None), 1) == "ahead"
    assert plan_position(Progress(3, 3, 0, None, None), 0) == "on_track"


def test_chapter_state_and_attendance_rate_never_invent_a_zero():
    assert chapter_state(5, 0) == "not_started"
    assert chapter_state(5, 2) == "in_progress"
    assert chapter_state(5, 5) == "taught"
    assert attendance_rate(0, 0) is None
    assert attendance_rate(3, 1) == pytest.approx(0.75)


def test_category_ranking_counts_each_mistake_once_and_breaks_ties_by_name():
    rows = [
        (1, 2, 10, "Units", 7),
        (1, 2, 10, "Units", 7),  # the query fanned one mistake into two rows
        (2, 1, 10, "Units", 8),
        (3, 3, 11, "Method", 7),
        (4, 1, 12, "Careless", 8),
    ]
    total, students, ranked = rank_class_categories(rows)
    assert (total, students) == (4, 2)
    assert [(c.category_name, c.mistakes) for c in ranked] == [
        ("Units", 2),
        ("Careless", 1),
        ("Method", 1),
    ]
    assert ranked[0].share == pytest.approx(0.5)
    assert (ranked[0].students_affected, ranked[0].severity_total) == (2, 3)


# ------------------------------------------------------------------- the plan


async def test_a_class_with_no_accepted_plan_says_so_and_still_lists_the_syllabus(
    client, tutor, group, subject
):
    await make_chapters(subject)
    report = await _report(group["id"])
    assert report.plan.has_plan is False
    assert report.plan.days_to_exam is None and report.plan.behind_by is None
    assert report.plan.position is None and report.plan.up_next is None
    assert [c.state for c in report.chapters] == ["not_started", "not_started"]
    assert report.chapters[0].lessons_planned is None


async def test_a_draft_plan_is_never_read(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(
        group, tutor, [(ch["c1"], MON, time(9, 0))], status=TeachingPlanStatus.draft, exam=EXAM
    )
    assert (await _report(group["id"])).plan.has_plan is False


async def test_plan_position_behind_countdown_and_up_next(client, tutor, group, subject):
    ch = await make_chapters(subject)
    _plan, slots = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], MON, time(9, 0)),  # taught
            (ch["c1"], TUE, time(9, 0)),  # ended, nothing recorded: behind
            (ch["c1"], FRI, time(9, 0)),  # ahead of us
            (ch["c2"], FRI + timedelta(days=7), time(9, 0)),
        ],
        exam=EXAM,
    )
    await _link(slots[0], await _lesson(group["id"], MON))

    plan = (await _report(group["id"])).plan
    assert plan.has_plan and plan.exam_date == EXAM
    assert plan.days_to_exam == (EXAM - WED).days == 61
    assert (plan.lessons_planned, plan.lessons_taught, plan.lessons_left) == (4, 1, 3)
    assert (plan.lessons_due, plan.behind_by, plan.ahead_by) == (2, 1, 0)
    assert plan.position == "behind"
    assert plan.up_next is not None
    assert plan.up_next.scheduled_date == TUE and plan.up_next.chapter_code == "C1"
    assert plan.up_next.topics  # the lesson's share of the chapter's topics


async def test_a_lesson_taught_early_is_ahead_not_behind(client, tutor, group, subject):
    ch = await make_chapters(subject)
    _plan, slots = await make_plan(
        group,
        tutor,
        [(ch["c1"], MON, time(9, 0)), (ch["c1"], FRI, time(9, 0))],
        exam=EXAM,
    )
    await _link(slots[0], await _lesson(group["id"], MON))
    await _link(slots[1], await _lesson(group["id"], WED))

    plan = (await _report(group["id"])).plan
    assert (plan.behind_by, plan.ahead_by, plan.position) == (0, 1, "ahead")
    assert plan.lessons_left == 0 and plan.up_next is None


async def test_the_countdown_goes_negative_once_the_exam_has_passed(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, time(9, 0))], exam=date(2026, 10, 1))
    plan = (await _report(group["id"])).plan
    assert plan.days_to_exam == -6


async def test_a_plan_that_has_not_reached_its_first_lesson_has_no_position(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], FRI, time(9, 0))], exam=EXAM)
    plan = (await _report(group["id"])).plan
    assert (plan.behind_by, plan.lessons_due, plan.position) == (None, None, None)
    assert plan.lessons_planned == 1 and plan.lessons_left == 1


# ------------------------------------------------------ chapters, topics, weak


async def test_taught_topics_come_from_recorded_lessons_and_chapters_carry_plan_counts(
    client, tutor, group, subject
):
    ch = await make_chapters(subject, topics_in_c1=3)
    _plan, slots = await make_plan(
        group,
        tutor,
        [(ch["c1"], MON, time(9, 0)), (ch["c1"], FRI, time(9, 0)), (ch["c2"], FRI, time(11, 0))],
        exam=EXAM,
    )
    lesson = await _lesson(group["id"], MON)
    await _link(slots[0], lesson)
    async with async_session() as s:
        s.add_all([LessonTopic(lesson_id=lesson, topic_id=t) for t in ch["t1"][:2]])
        await s.commit()

    c1, c2 = (await _report(group["id"])).chapters
    assert (c1.topics_total, c1.topics_taught, c1.state) == (3, 2, "in_progress")
    assert [t.taught for t in c1.topics] == [True, True, False]
    assert (c1.lessons_planned, c1.lessons_taught) == (2, 1)
    assert (c2.state, c2.lessons_planned, c2.lessons_taught) == ("not_started", 1, 0)


async def test_weak_topics_use_the_subjects_configured_threshold(
    client, tutor, group, subject, student
):
    ch = await make_chapters(subject, topics_in_c1=2)
    low, mid = ch["t1"]
    async with async_session() as s:
        await write_v2_snapshot(
            s,
            student_id=student["user"]["id"],
            subject_id=subject["id"],
            score=60,
            topics={
                low: (40.0, FactorConfidence.high),
                mid: (65.0, FactorConfidence.high),
                ch["t2"]: (None, FactorConfidence.no_data),
            },
        )
        await s.commit()

    report = await _report(group["id"])
    # The default threshold is 60: only the 40 is weak.
    assert report.weak_threshold == 60.0
    assert [t.topic_title for t in report.weak_topics] == ["T1"]
    topics = {t.topic_id: t for c in report.chapters for t in c.topics}
    assert topics[low].weak and topics[low].avg_score == 40.0 and topics[low].student_count == 1
    assert not topics[mid].weak
    # No measurement is absent, never 0.
    assert topics[ch["t2"]].avg_score is None and topics[ch["t2"]].student_count is None

    async with async_session() as s:
        s.add(
            ReadinessWeights(
                organization_id=await _org(group),
                tutor_id=tutor["user"]["id"],
                weak_threshold=70.0,
            )
        )
        await s.commit()
    report = await _report(group["id"])
    assert report.weak_threshold == 70.0
    assert [t.topic_title for t in report.weak_topics] == ["T1", "T2"]


async def test_a_class_with_no_evidence_reports_absence_not_zeros(client, tutor, group, student):
    report = await _report(group["id"])
    assert report.readiness.score is None and report.readiness.students_with_evidence == 0
    assert report.weak_topics == []
    assert report.mistakes.total_mistakes is None and report.mistakes.categories == []
    assert report.attendance.rate is None


# ------------------------------------------------------------------ attendance


async def test_attendance_rates_per_learner_and_class(client, tutor, group, student):
    await _joined_long_ago()
    sid, org = student["user"]["id"], await _org(group)
    mon, tue = await _lesson(group["id"], MON), await _lesson(group["id"], TUE)
    await _lesson(group["id"], WED, start=time(9, 0))  # ended, unmarked: not taken
    await _mark(mon, sid, AttendanceState.present, org)
    await _mark(tue, sid, AttendanceState.absent, org)

    att = (await _report(group["id"])).attendance
    assert (att.present, att.absent, att.not_taken) == (1, 1, 1)
    assert att.rate == pytest.approx(0.5)
    (learner,) = att.learners
    assert learner.student_name == "Sara" and learner.rate == pytest.approx(0.5)


async def test_a_learner_nobody_marked_has_no_rate(client, tutor, group, student):
    await _joined_long_ago()
    await _lesson(group["id"], MON)
    (learner,) = (await _report(group["id"])).attendance.learners
    assert (learner.present, learner.absent, learner.not_taken) == (0, 0, 1)
    assert learner.rate is None


# -------------------------------------------------------------------- mistakes


async def test_mistake_patterns_rank_categories_inside_the_window(
    client, tutor, group, subject, student
):
    sid, org = student["user"]["id"], await _org(group)
    since = date(2026, 9, 9)
    async with async_session() as s:
        units = await make_mistake_category(
            s, organization_id=org, subject_id=subject["id"], name="Units"
        )
        method = await make_mistake_category(
            s, organization_id=org, subject_id=subject["id"], name="Method"
        )
        marks = await settled_submission(
            s,
            subject_id=subject["id"],
            organization_id=org,
            student_id=sid,
            analysed=True,
            marks=3,
            analysed_at=NOW - timedelta(days=3),
        )
        for mark, cat, sev in ((marks[0], units, 2), (marks[1], units, 1), (marks[2], method, 3)):
            await add_mistake(
                s,
                student_id=sid,
                mark_id=mark,
                category_id=cat.id,
                severity=sev,
                topic_ids=[],
                source=MistakeSource.ai,
            )
        # Analysed before the window opens: not in the report at all.
        old = await settled_submission(
            s,
            subject_id=subject["id"],
            organization_id=org,
            student_id=sid,
            analysed=True,
            marks=1,
            analysed_at=NOW - timedelta(days=60),
        )
        await add_mistake(
            s,
            student_id=sid,
            mark_id=old[0],
            category_id=method.id,
            severity=1,
            topic_ids=[],
            source=MistakeSource.ai,
        )
        await s.commit()

    m = (await _report(group["id"], since=since)).mistakes
    assert (m.analysed_questions, m.total_mistakes, m.students_affected) == (3, 3, 1)
    assert [(c.category_name, c.mistakes, c.severity_total) for c in m.categories] == [
        ("Units", 2, 3),
        ("Method", 1, 3),
    ]
    assert m.since == since
    # The default window is four weeks back, the same here, and carries its own start.
    assert (await _report(group["id"])).mistakes.since == date(2026, 9, 9)


async def test_work_nobody_analysed_is_not_enough_data_not_a_clean_record(
    client, tutor, group, subject, student
):
    sid, org = student["user"]["id"], await _org(group)
    async with async_session() as s:
        await settled_submission(
            s,
            subject_id=subject["id"],
            organization_id=org,
            student_id=sid,
            analysed=False,
            marks=2,
        )
        await s.commit()
    m = (await _report(group["id"])).mistakes
    assert m.analysed_questions == 0 and m.total_mistakes is None and m.students_affected is None


# ----------------------------------------------------------------- the route


async def test_the_route_returns_the_report_for_the_owning_tutor(client, tutor, group, student):
    resp = await client.get(f"/api/v1/groups/{group['id']}/report", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == group["name"] and body["plan"]["has_plan"] is False
    resp = await client.get(
        f"/api/v1/groups/{group['id']}/report?since=2026-01-01", headers=tutor["headers"]
    )
    assert resp.json()["mistakes"]["since"] == "2026-01-01"


async def test_another_organizations_class_is_404(client, tutor, group, student):
    headers, _ = await _other_tutor(client, "other-report@example.com")
    resp = await client.get(f"/api/v1/groups/{group['id']}/report", headers=headers)
    assert resp.status_code == 404


async def test_a_student_cannot_read_the_tutor_report(client, tutor, group, student):
    resp = await client.get(
        f"/api/v1/groups/{group['id']}/report",
        headers=student["headers"],
    )
    assert resp.status_code == 403
    assert (await client.get(f"/api/v1/groups/{group['id']}/report")).status_code == 401


async def test_a_missing_class_is_404(client, tutor):
    resp = await client.get("/api/v1/groups/9999/report", headers=tutor["headers"])
    assert resp.status_code == 404
