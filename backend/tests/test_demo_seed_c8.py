"""The demo seed shows mistakes, reports and attendance (coherence C.8) without
ever calling a model, and stays idempotent."""

import pytest
from sqlalchemy import delete, func, select, update

import app.services.ai as ai_module
from app.db import async_session
from app.models import (
    AiUsageEvent,
    AttendanceState,
    Lesson,
    LessonAttendance,
    LessonMode,
    Mistake,
    MistakeSource,
    MistakeTopic,
    PlanSlot,
    QuestionMark,
    ReadinessSnapshot,
    Report,
    ReportStatus,
    Subject,
    Submission,
    User,
)
from app.services.attendance import student_attendance
from app.services.mistake_rollup import roll_up_mistakes
from seed import demo

pytestmark = pytest.mark.usefixtures("no_ai_key")


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def no_model(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("the demo seed must not call a model")

    for name in ("structured_complete", "text_complete"):
        monkeypatch.setattr(ai_module, name, _boom, raising=False)
    import app.services.mistake_tagging as tagging
    import app.services.reports as reports

    monkeypatch.setattr(tagging, "structured_complete", _boom, raising=False)
    monkeypatch.setattr(reports, "text_complete", _boom, raising=False)


async def test_seed_twice_does_not_duplicate_and_calls_no_model(no_model):
    await demo.main()
    async with async_session() as session:
        before = [
            await _count(session, m)
            for m in (Mistake, MistakeTopic, Report, LessonAttendance, Lesson, PlanSlot)
        ]
        assert all(n > 0 for n in before)
    await demo.main()
    async with async_session() as session:
        after = [
            await _count(session, m)
            for m in (Mistake, MistakeTopic, Report, LessonAttendance, Lesson, PlanSlot)
        ]
        assert after == before
        assert await _count(session, AiUsageEvent) == 0


async def test_mistake_rollup_is_non_empty_for_the_demo_student(no_model):
    await demo.main()
    async with async_session() as session:
        tutor = await session.scalar(select(User).where(User.email == "demo-tutor@example.com"))
        chemistry = await session.scalar(select(Subject).where(Subject.name == "Chemistry"))
        students = (await session.scalars(select(User).where(User.created_by_id == tutor.id))).all()
        sara = await session.scalar(select(User).where(User.email == "demo-student@example.com"))
        rollups = [
            await roll_up_mistakes(session, student_id=s.id, subject_id=chemistry.id)
            for s in [sara, *students]
        ]
        # Every settled submission is analysed, so the page shows a count rather
        # than "not enough data".
        assert all(r.analysed_questions > 0 for r in rollups)
        assert sum(r.total.mistakes for r in rollups) > 0
        assert any(r.topics for r in rollups)
        assert len({c.category_name for r in rollups for c in r.total.categories}) >= 2


async def test_each_demo_student_has_a_ready_report_with_content(no_model):
    await demo.main()
    async with async_session() as session:
        students = (await session.scalars(select(User).where(User.role == "student"))).all()
        assert len(students) == 6
        for student in students:
            reports = (
                await session.scalars(select(Report).where(Report.student_id == student.id))
            ).all()
            assert reports, student.name
            for report in reports:
                assert report.status == ReportStatus.ready
                assert report.content and "Overall readiness" in report.content
                assert report.generated_at is not None


async def test_attendance_is_mixed_and_summarised_from_the_timetable(no_model):
    await demo.main()
    async with async_session() as session:
        tutor = await session.scalar(select(User).where(User.email == "demo-tutor@example.com"))
        lessons = (await session.scalars(select(Lesson))).all()
        assert lessons
        assert all(lesson.mode == LessonMode.in_person for lesson in lessons)
        assert all(lesson.start_time is not None for lesson in lessons)
        assert all(lesson.schedule_slot_id is not None for lesson in lessons)

        states = (await session.scalars(select(LessonAttendance.state))).all()
        assert AttendanceState.present in states and AttendanceState.absent in states
        assert states.count(AttendanceState.present) > states.count(AttendanceState.absent)

        totals = [
            await student_attendance(
                session,
                student_id=s.id,
                organization_id=tutor.organization_id,
                tutor_id=tutor.id,
            )
            for s in (await session.scalars(select(User).where(User.role == "student"))).all()
        ]
        assert all(t.lessons > 0 for t in totals)
        assert sum(t.present for t in totals) > 0
        assert sum(t.absent for t in totals) > 0
        assert sum(t.not_taken for t in totals) > 0
        assert all(t.rate is not None for t in totals if t.present + t.absent)

        # Future plan slots are left for the auto-record sweep.
        assert (
            await session.scalar(
                select(func.count()).select_from(PlanSlot).where(PlanSlot.lesson_id.is_not(None))
            )
            == 0
        )


async def test_seeded_mistakes_are_example_data_not_ai(no_model):
    await demo.main()
    async with async_session() as session:
        sources = set((await session.scalars(select(Mistake.source))).all())
        assert sources == {MistakeSource.demo}


async def test_a_real_retag_replaces_the_seeded_mistakes(no_model, fake_ai, monkeypatch):
    from app.services import mistake_tagging
    from app.services.mistake_tagging import MistakeTaggingResult

    await demo.main()
    async with async_session() as session:
        # A submission that carries seeded rows.
        submission_id = await session.scalar(
            select(QuestionMark.submission_id)
            .join(Mistake, Mistake.question_mark_id == QuestionMark.id)
            .limit(1)
        )
        total_before = await _count(session, Mistake)
        monkeypatch.setattr(
            mistake_tagging, "structured_complete", fake_ai(MistakeTaggingResult(mistakes=[]))
        )
        await mistake_tagging.tag_mistakes(session, {"submission_id": submission_id})
        remaining = await session.scalar(
            select(func.count())
            .select_from(Mistake)
            .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
            .where(QuestionMark.submission_id == submission_id)
        )
        assert remaining == 0
        # Other submissions' example rows are untouched.
        assert 0 < await _count(session, Mistake) < total_before


async def test_a_rerun_completes_a_partial_seed(no_model):
    tables = (Mistake, MistakeTopic, Report, LessonAttendance, ReadinessSnapshot)
    await demo.main()
    async with async_session() as session:
        full = [await _count(session, m) for m in tables]
        # Simulate a seed that died after the core rows.
        await session.execute(delete(MistakeTopic))
        await session.execute(delete(Mistake))
        await session.execute(update(Submission).values(mistakes_analysed_at=None))
        await session.execute(delete(Report))
        await session.execute(delete(LessonAttendance))
        await session.execute(delete(ReadinessSnapshot))
        await session.commit()

    await demo.main()
    async with async_session() as session:
        assert [await _count(session, m) for m in tables] == full

    await demo.main()  # and a further run changes nothing
    async with async_session() as session:
        assert [await _count(session, m) for m in tables] == full
