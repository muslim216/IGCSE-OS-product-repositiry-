"""Teaching-plan inputs (task 6.2, AV-15): exam date, pace, past-paper start, breaks.

Everything here mirrors the 6.1 CHECK constraints as explicit validation so a bad
value is a 422 from the API rather than an IntegrityError 500.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import PlanBreak, ScheduleSlot, TeachingPlan, TeachingPlanStatus
from app.schemas.teaching_plan import LESSON_MINUTES_RANGE, LESSONS_PER_WEEK_RANGE


class PlanInputError(ValueError):
    """An input the plan cannot hold. The router turns it into a 422."""


@dataclass(frozen=True)
class TimetableDefaults:
    lessons_per_week: int | None
    lesson_minutes: int | None


async def _plan_with_status(
    session: AsyncSession, group_id: int, status: TeachingPlanStatus
) -> TeachingPlan | None:
    return await session.scalar(
        select(TeachingPlan)
        .where(TeachingPlan.group_id == group_id, TeachingPlan.status == status)
        .options(selectinload(TeachingPlan.breaks))
    )


async def accepted_plan_for_group(session: AsyncSession, group_id: int) -> TeachingPlan | None:
    """The one reader that enforces "nothing reads a draft plan" (task 6.4).

    Anything that consumes a plan (lesson briefs, readiness, the calendar) goes
    through this rather than querying `TeachingPlan` itself.
    """
    return await _plan_with_status(session, group_id, TeachingPlanStatus.accepted)


async def draft_plan_for_group(session: AsyncSession, group_id: int) -> TeachingPlan | None:
    return await _plan_with_status(session, group_id, TeachingPlanStatus.draft)


async def timetable_defaults(session: AsyncSession, group_id: int) -> TimetableDefaults:
    """Pace pre-filled from the class's weekly timetable (owner decision 2026-10-03).

    Lessons per week is the number of slots; length is the most common slot
    duration. When durations differ and tie, the longest wins — better to
    over-allow a lesson than to plan one that cannot cover its chapter. No slots
    means nothing is pre-filled, never 0.
    """
    durations = list(
        await session.scalars(
            select(ScheduleSlot.duration_min).where(ScheduleSlot.group_id == group_id)
        )
    )
    if not durations:
        return TimetableDefaults(None, None)
    counts = Counter(durations)
    top = max(counts.values())
    return TimetableDefaults(len(durations), max(d for d, c in counts.items() if c == top))


def validate_inputs(
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
    *,
    today: date | None = None,
) -> None:
    today = today or date.today()
    lo, hi = LESSONS_PER_WEEK_RANGE
    if not lo <= lessons_per_week <= hi:
        raise PlanInputError(f"Lessons per week must be between {lo} and {hi}")
    lo, hi = LESSON_MINUTES_RANGE
    if not lo <= lesson_minutes <= hi:
        raise PlanInputError(f"Lesson length must be between {lo} and {hi} minutes")
    if exam_date <= today:
        raise PlanInputError("The exam date must be in the future")
    if past_paper_start_date is not None and past_paper_start_date > exam_date:
        raise PlanInputError("Past papers cannot start after the exam date")


async def save_plan_inputs(
    session: AsyncSession,
    *,
    organization_id: int,
    group_id: int,
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
    today: date | None = None,
) -> TeachingPlan:
    """Create or update the class's draft. An accepted plan is never touched here:
    changing a live plan's inputs is a re-plan (task 6.6)."""
    validate_inputs(exam_date, lessons_per_week, lesson_minutes, past_paper_start_date, today=today)
    plan = await draft_plan_for_group(session, group_id)
    if plan is None:
        plan = TeachingPlan(
            organization_id=organization_id,
            group_id=group_id,
            status=TeachingPlanStatus.draft,
            exam_date=exam_date,
            lessons_per_week=lessons_per_week,
            lesson_minutes=lesson_minutes,
            past_paper_start_date=past_paper_start_date,
        )
        # A draft drafted beside a live plan keeps its holidays, otherwise
        # changing the exam date would silently drop them.
        accepted = await accepted_plan_for_group(session, group_id)
        if accepted is not None:
            plan.breaks = [
                PlanBreak(start_date=b.start_date, end_date=b.end_date, label=b.label)
                for b in accepted.breaks
            ]
        try:
            # A savepoint, so losing the race to a concurrent save (UNIQUE on
            # group_id + status) rolls back only this insert.
            async with session.begin_nested():
                session.add(plan)
        except IntegrityError:
            plan = await draft_plan_for_group(session, group_id)
            if plan is None:
                raise
    return await _apply_and_commit(
        session, plan, exam_date, lessons_per_week, lesson_minutes, past_paper_start_date
    )


async def _apply_and_commit(
    session: AsyncSession,
    plan: TeachingPlan,
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
) -> TeachingPlan:
    plan.exam_date = exam_date
    plan.lessons_per_week = lessons_per_week
    plan.lesson_minutes = lesson_minutes
    plan.past_paper_start_date = past_paper_start_date
    await session.commit()
    return await _reload(session, plan)


async def _reload(session: AsyncSession, plan: TeachingPlan) -> TeachingPlan:
    await session.refresh(plan, attribute_names=["breaks"])
    return plan


async def add_break(
    session: AsyncSession, *, plan: TeachingPlan, start_date: date, end_date: date, label: str
) -> PlanBreak:
    if end_date < start_date:
        raise PlanInputError("A break cannot end before it starts")
    for other in plan.breaks:
        if start_date <= other.end_date and other.start_date <= end_date:
            raise PlanInputError(
                f"This overlaps the break '{other.label}' "
                f"({other.start_date.isoformat()} to {other.end_date.isoformat()})"
            )
    plan_break = PlanBreak(plan_id=plan.id, start_date=start_date, end_date=end_date, label=label)
    session.add(plan_break)
    await session.commit()
    return plan_break


async def remove_break(session: AsyncSession, *, plan: TeachingPlan, break_id: int) -> bool:
    """Only a break of this (draft) plan; False when there is none."""
    plan_break = next((b for b in plan.breaks if b.id == break_id), None)
    if plan_break is None:
        return False
    await session.delete(plan_break)
    await session.commit()
    return True
