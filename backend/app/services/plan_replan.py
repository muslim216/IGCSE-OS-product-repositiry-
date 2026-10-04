"""One-click re-plan for a class that is behind (task 6.6, AV-18, E15).

The tutor asks; this builds a *draft* and queues the 6.3 drafting job. The
accepted plan is never touched here: the tutor reviews the draft and accepts it
through `accept_plan` (6.4), and only then does anything change.
"""

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Group,
    JobStatus,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
    TeachingPlanStatus,
)
from app.services.plan_drafting import enqueue_plan_draft, renumber_slots
from app.services.teaching_plan import (
    PlanInputError,
    PlanStateError,
    _latest_draft_jobs,
    lock_group_plans,
    validate_inputs,
)


def keep_in_replan(
    provenance: PlanSlotProvenance, has_lesson: bool, scheduled_date: date, today: date
) -> bool:
    """Which of the accepted plan's slots the re-plan carries into the draft.

    Every non-generated slot (AV-77): taught lessons and the tutor's own edits
    are theirs. The one exception is a hand-edited slot dated before today that
    no lesson was recorded against — that is exactly the gap being re-planned,
    and keeping it would leave the class "behind" by the same slot forever, so
    the re-plan lets that chapter be scheduled again. A lesson the tutor
    recorded is never dropped, whatever its provenance.
    """
    if provenance is PlanSlotProvenance.generated:
        return False
    if provenance is PlanSlotProvenance.manually_modified:
        return has_lesson or scheduled_date >= today
    return True


async def _lock_group_plans(session: AsyncSession, group: Group) -> list[TeachingPlan]:
    return await lock_group_plans(session, group.id)


async def replan(session: AsyncSession, *, group: Group, today: date) -> TeachingPlan:
    """Create (or reuse) the class's draft from the accepted plan and queue drafting.

    One transaction under the plan rows' lock: every check is made after the lock
    is held, so a concurrent accept, save or reflow cannot slip in between a
    check and the writes. (6.2's `save_plan_inputs` commits and releases its
    lock, which is why it is not used here.)

    CODE-12: this is deliberately NOT 6.8's reflow (`plan_reflow`). A syllabus
    edit reflows the plan automatically with no acceptance, because the tutor
    changed the chapters themselves. A behind-schedule re-plan only recalculates
    and then WAITS: it writes a draft beside the live plan and nothing is
    accepted until the tutor accepts it (E15, "nothing reschedules itself").
    """
    rows = await _lock_group_plans(session, group)
    accepted = next((p for p in rows if p.status is TeachingPlanStatus.accepted), None)
    draft = next((p for p in rows if p.status is TeachingPlanStatus.draft), None)
    if accepted is None:
        raise PlanStateError("There is no accepted plan to re-plan.")
    if draft is not None and (await _latest_draft_jobs(session, {draft.id})).get(draft.id) in (
        JobStatus.pending,
        JobStatus.running,
    ):
        raise PlanStateError("A plan is already being drafted. Wait for it to finish.")
    # An exam date that has passed cannot be planned toward.
    try:
        validate_inputs(
            accepted.exam_date,
            accepted.lessons_per_week,
            accepted.lesson_minutes,
            accepted.past_paper_start_date,
            today=today,
        )
    except PlanInputError as exc:
        raise PlanStateError(f"This plan cannot be re-planned: {exc}") from exc

    if draft is None:
        draft = TeachingPlan(
            organization_id=group.organization_id,
            group_id=group.id,
            status=TeachingPlanStatus.draft,
            exam_date=accepted.exam_date,
            lessons_per_week=accepted.lessons_per_week,
            lesson_minutes=accepted.lesson_minutes,
            past_paper_start_date=accepted.past_paper_start_date,
        )
        try:
            # A savepoint: a concurrent save can create the class's draft after
            # our read (the lock held none to wait on), and UNIQUE(group_id,
            # status) then rejects this insert. Lose the race, reuse theirs.
            async with session.begin_nested():
                session.add(draft)
        except IntegrityError:
            draft = await session.scalar(
                select(TeachingPlan)
                .where(
                    TeachingPlan.group_id == group.id,
                    TeachingPlan.status == TeachingPlanStatus.draft,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if draft is None:
                raise PlanStateError("The plan changed while re-planning. Try again.") from None
            if (await _latest_draft_jobs(session, {draft.id})).get(draft.id) in (
                JobStatus.pending,
                JobStatus.running,
            ):
                raise PlanStateError(
                    "A plan is already being drafted. Wait for it to finish."
                ) from None
    draft.exam_date = accepted.exam_date
    draft.lessons_per_week = accepted.lessons_per_week
    draft.lesson_minutes = accepted.lesson_minutes
    draft.past_paper_start_date = accepted.past_paper_start_date
    # A reused draft is reset to the live plan: its breaks and slots are replaced.
    await session.execute(delete(PlanBreak).where(PlanBreak.plan_id == draft.id))
    await session.execute(delete(PlanSlot).where(PlanSlot.plan_id == draft.id))
    breaks = (
        await session.scalars(select(PlanBreak).where(PlanBreak.plan_id == accepted.id))
    ).all()
    session.add_all(
        PlanBreak(plan_id=draft.id, start_date=b.start_date, end_date=b.end_date, label=b.label)
        for b in breaks
    )
    live = (
        await session.scalars(
            select(PlanSlot).where(PlanSlot.plan_id == accepted.id).order_by(PlanSlot.sequence)
        )
    ).all()
    session.add_all(
        PlanSlot(
            plan_id=draft.id,
            chapter_id=s.chapter_id,
            scheduled_date=s.scheduled_date,
            sequence=s.sequence,
            provenance=s.provenance,
            # Always carried: the draft's own default would be the timetable's,
            # losing a time the tutor set per lesson (AV-119).
            start_time=s.start_time,
            # No `lesson_id`: it is unique, and the accepted plan still owns the
            # link until accept moves it across.
        )
        for s in live
        # A cancelled slot is never carried: it is the old plan's record of intent
        # and carried as live it would become a lesson that is not cancelled. The
        # redraft schedules its chapter again from today (a cancelled slot takes
        # no share), which is exactly the catch-up "behind" asks for, so the gap
        # the cancellation left is closed rather than hidden.
        if s.cancelled_at is None
        and keep_in_replan(s.provenance, s.lesson_id is not None, s.scheduled_date, today)
    )
    # The old outcome described slots that are gone.
    draft.draft_result = None
    await session.flush()
    await renumber_slots(session, draft.id)
    await enqueue_plan_draft(session, draft.id)
    await session.commit()
    return draft
