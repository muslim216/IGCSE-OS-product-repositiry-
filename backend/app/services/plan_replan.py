"""One-click re-plan for a class that is behind (task 6.6, AV-18, E15).

The tutor asks; this builds a *draft* and queues the 6.3 drafting job. The
accepted plan is never touched here: the tutor reviews the draft and accepts it
through `accept_plan` (6.4), and only then does anything change.
"""

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Group,
    JobStatus,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
)
from app.services.plan_drafting import enqueue_plan_draft, renumber_slots
from app.services.teaching_plan import (
    PlanInputError,
    PlanStateError,
    _latest_draft_jobs,
    accepted_plan_for_group,
    draft_plan_for_group,
    save_plan_inputs,
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


async def replan(session: AsyncSession, *, group: Group, today: date) -> TeachingPlan:
    """Create (or reuse) the class's draft from the accepted plan and queue drafting.

    CODE-12: this is deliberately NOT 6.8's reflow (`plan_reflow`). A syllabus
    edit reflows the plan automatically with no acceptance, because the tutor
    changed the chapters themselves. A behind-schedule re-plan only recalculates
    and then WAITS: it writes a draft beside the live plan and nothing is
    accepted until the tutor accepts it (E15, "nothing reschedules itself").
    """
    accepted = await accepted_plan_for_group(session, group.id)
    if accepted is None:
        raise PlanStateError("There is no accepted plan to re-plan.")
    existing = await draft_plan_for_group(session, group.id)
    if existing is not None and (await _latest_draft_jobs(session, {existing.id})).get(
        existing.id
    ) in (JobStatus.pending, JobStatus.running):
        raise PlanStateError("A plan is already being drafted. Wait for it to finish.")

    # 6.2's path: validates, creates or reuses the draft, copies the breaks when
    # it creates one. An exam date that has passed cannot be planned toward.
    try:
        draft = await save_plan_inputs(
            session,
            organization_id=group.organization_id,
            group_id=group.id,
            exam_date=accepted.exam_date,
            lessons_per_week=accepted.lessons_per_week,
            lesson_minutes=accepted.lesson_minutes,
            past_paper_start_date=accepted.past_paper_start_date,
            today=today,
        )
    except PlanInputError as exc:
        raise PlanStateError(f"This plan cannot be re-planned: {exc}") from exc

    # A reused draft is reset to the live plan: its breaks and slots are
    # replaced so the re-plan starts from what the tutor accepted.
    await session.execute(delete(PlanBreak).where(PlanBreak.plan_id == draft.id))
    await session.execute(delete(PlanSlot).where(PlanSlot.plan_id == draft.id))
    session.add_all(
        PlanBreak(plan_id=draft.id, start_date=b.start_date, end_date=b.end_date, label=b.label)
        for b in accepted.breaks
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
            # No `lesson_id`: it is unique, and the accepted plan still owns the
            # link until accept moves it across.
        )
        for s in live
        if keep_in_replan(s.provenance, s.lesson_id is not None, s.scheduled_date, today)
    )
    # The old outcome described slots that are gone.
    draft.draft_result = None
    await session.flush()
    await renumber_slots(session, draft.id)
    await enqueue_plan_draft(session, draft.id)
    await session.commit()
    return draft
