"""Shared builders for the task 7.4 tests: a class with one chapter of five topics,
an accepted plan, and slots at chosen dates and start times."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Chapter,
    Lesson,
    LessonTopic,
    Organization,
    PlanSlot,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
)
from tests.factories import org_id

EXAM = date.today() + timedelta(days=200)
LONG_AGO = datetime(2020, 1, 1, tzinfo=timezone.utc)  # before any date a test uses


async def make_chapters(subject, *, topics_in_c1: int = 5) -> dict:
    """C1 with `topics_in_c1` topics (ids ascending = teaching order) and C2 with one."""
    async with async_session() as s:
        c1 = Chapter(subject_id=subject["id"], code="C1", title="Atoms", position=1)
        c2 = Chapter(subject_id=subject["id"], code="C2", title="Bonding", position=2)
        s.add_all([c1, c2])
        await s.flush()
        t1 = [
            Topic(subject_id=subject["id"], code=f"9.{i}", title=f"T{i}", chapter_id=c1.id)
            for i in range(1, topics_in_c1 + 1)
        ]
        t2 = Topic(subject_id=subject["id"], code="2.1", title="Covalent", chapter_id=c2.id)
        s.add_all([*t1, t2])
        await s.commit()
        return {"c1": c1.id, "c2": c2.id, "t1": [t.id for t in t1], "t2": t2.id}


async def make_plan(
    group,
    tutor,
    slots: list[tuple[int, date, time | None]],
    *,
    status=TeachingPlanStatus.accepted,
    accepted_at: datetime | None = LONG_AGO,
    exam: date = EXAM,
    minutes: int = 60,
    lessons_per_week: int = 2,
) -> tuple[int, list[int]]:
    """slots: (chapter_id, date, start_time). Returns (plan id, slot ids in order)."""
    async with async_session() as s:
        accepted = status is TeachingPlanStatus.accepted
        plan = TeachingPlan(
            organization_id=await org_id(s),
            group_id=group["id"],
            status=status,
            exam_date=exam,
            lessons_per_week=lessons_per_week,
            lesson_minutes=minutes,
            accepted_at=accepted_at if accepted else None,
            accepted_by_id=tutor["user"]["id"] if accepted else None,
            draft_result={"status": "drafted"} if accepted else None,
        )
        s.add(plan)
        await s.flush()
        rows = [
            PlanSlot(
                plan_id=plan.id,
                chapter_id=cid,
                scheduled_date=day,
                sequence=i + 1,
                start_time=start,
            )
            for i, (cid, day, start) in enumerate(slots)
        ]
        s.add_all(rows)
        await s.commit()
        return plan.id, [r.id for r in rows]


async def set_org_timezone(name: str | None) -> None:
    async with async_session() as s:
        org = await s.scalar(select(Organization))
        org.timezone = name
        await s.commit()


async def add_timetable(group, weekday: int, start: time, minutes: int = 60) -> None:
    async with async_session() as s:
        s.add(
            ScheduleSlot(
                group_id=group["id"], weekday=weekday, start_time=start, duration_min=minutes
            )
        )
        await s.commit()


async def lessons() -> list[Lesson]:
    async with async_session() as s:
        return list((await s.scalars(select(Lesson).order_by(Lesson.date, Lesson.id))).all())


async def lesson_topic_ids(lesson_id: int) -> list[int]:
    async with async_session() as s:
        return sorted(
            (
                await s.scalars(
                    select(LessonTopic.topic_id).where(LessonTopic.lesson_id == lesson_id)
                )
            ).all()
        )


async def slot_rows(plan_id: int) -> list[PlanSlot]:
    async with async_session() as s:
        return list(
            (
                await s.scalars(
                    select(PlanSlot)
                    .where(PlanSlot.plan_id == plan_id)
                    .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
                )
            ).all()
        )
