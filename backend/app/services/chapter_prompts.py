"""The tutor home's "coming up in your plan" prompt (task 6.7, AV-20, AV-22).

A class whose accepted plan has reached a chapter that has no classified yet is
the moment a tutor needs to upload one. This is information with a link, never
a gate: nothing here blocks a lesson, a plan or homework.
"""

from datetime import date, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    Classified,
    Group,
    PlanSlot,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.schemas.today import ChapterPrompt

#: How far ahead a chapter that has not started yet is surfaced. A week is long
#: enough to find, scan and upload a classified before the first lesson, and
#: short enough that the home is not a to-do list of the whole term; a
#: chapter four weeks out is not yet something the tutor can act on.
CHAPTER_LOOKAHEAD_DAYS = 7


async def chapter_prompts(db: AsyncSession, user: User, today: date) -> list[ChapterPrompt]:
    """One prompt per (class, chapter) that has begun or begins within the
    lookahead, whose last planned lesson is not past, and that has no classified
    in the tutor's organization. Soonest first.

    The organization and tutor come from the authenticated user, never from the
    request (PROD-4, SEC-7). One query: slots are aggregated per (plan, chapter)
    in SQL and the classified check is a correlated EXISTS, so cost does not grow
    with the number of classes (PERF-1). `today` is the caller's, in the tutor's
    zone and shared with the lesson list, so one response cannot straddle two days.
    """
    horizon = today + timedelta(days=CHAPTER_LOOKAHEAD_DAYS)

    first = func.min(PlanSlot.scheduled_date)
    last = func.max(PlanSlot.scheduled_date)
    rows = (
        await db.execute(
            select(
                Group.id,
                Group.name,
                Subject.name,
                Chapter.id,
                Chapter.code,
                Chapter.title,
                first,
                last,
            )
            .select_from(PlanSlot)
            .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
            .join(Group, Group.id == TeachingPlan.group_id)
            .join(Subject, Subject.id == Group.subject_id)
            .join(Chapter, Chapter.id == PlanSlot.chapter_id)
            .where(
                TeachingPlan.organization_id == user.organization_id,
                Group.tutor_id == user.id,
                Group.deleted_at.is_(None),
                # Nothing reads a draft plan (task 6.4): only the accepted plan
                # is what the tutor has committed to. 6.2's shared helper is the
                # eventual home of this rule.
                TeachingPlan.status == TeachingPlanStatus.accepted,
                # Classifieds are tutor material scoped by organization, never
                # by subject alone (SEC-8): another tenant's upload for the
                # same chapter must not silence this prompt.
                ~exists().where(
                    Classified.organization_id == user.organization_id,
                    Classified.chapter_id == Chapter.id,
                ),
            )
            .group_by(Group.id, Group.name, Subject.name, Chapter.id, Chapter.code, Chapter.title)
            .having(first <= horizon, last >= today)
        )
    ).all()

    prompts = [
        ChapterPrompt(
            group_id=group_id,
            group_name=group_name,
            subject_name=subject_name,
            chapter_id=chapter_id,
            chapter_code=code,
            chapter_title=title,
            starts_on=starts_on,
            ends_on=ends_on,
            # Entered means the first planned lesson is today or earlier.
            started=starts_on <= today,
        )
        for group_id, group_name, subject_name, chapter_id, code, title, starts_on, ends_on in rows
    ]
    prompts.sort(key=_order)
    return prompts


def _order(p: ChapterPrompt) -> tuple[date, str, int]:
    return (p.starts_on, p.group_name, p.chapter_id)
