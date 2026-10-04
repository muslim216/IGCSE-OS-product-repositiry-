"""Task 7.4 follow-ups: a re-plan never carries a cancelled lesson as live and
always carries start times; accepting carries a lesson's start time."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    Lesson,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlanStatus,
    User,
)
from app.services.plan_replan import replan
from app.services.teaching_plan import accept_plan
from tests.plan_world import make_chapters, make_plan, slot_rows

FUTURE = date.today() + timedelta(days=14)


async def _draft_of(group_id: int) -> list[PlanSlot]:
    from app.models import TeachingPlan

    async with async_session() as s:
        draft_id = await s.scalar(
            select(TeachingPlan.id).where(
                TeachingPlan.group_id == group_id, TeachingPlan.status == TeachingPlanStatus.draft
            )
        )
    return await slot_rows(draft_id)


async def test_replan_does_not_carry_a_cancelled_slot_and_copies_start_times(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    plan_id, ids = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], FUTURE, time(18, 30)),
            (ch["c1"], FUTURE + timedelta(days=3), time(16, 0)),
        ],
    )
    async with async_session() as s:
        for sid in ids:
            (await s.get(PlanSlot, sid)).provenance = PlanSlotProvenance.manually_modified
        cancelled = await s.get(PlanSlot, ids[1])
        cancelled.cancelled_at = datetime.now(timezone.utc)
        await s.commit()

    async with async_session() as s:
        g = await s.get(Group, group["id"])
        await replan(s, group=g, today=date.today())

    carried = await _draft_of(group["id"])
    assert [(r.scheduled_date, r.start_time) for r in carried] == [(FUTURE, time(18, 30))]
    assert all(r.cancelled_at is None for r in carried)


async def test_accepting_carries_a_lessons_start_time_onto_a_new_slot(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    plan_id, ids = await make_plan(group, tutor, [(ch["c1"], FUTURE, time(16, 0))])
    made = await client.post(
        "/api/v1/lessons",
        json={
            "group_id": group["id"],
            "date": FUTURE.isoformat(),
            "plan_slot_id": ids[0],
            "start_time": "19:15",
        },
        headers=tutor["headers"],
    )
    assert made.status_code == 201, made.text
    # A draft that has no copy of that lesson: the carry must make a new slot.
    await make_plan(
        group,
        tutor,
        [(ch["c2"], FUTURE + timedelta(days=5), None)],
        status=TeachingPlanStatus.draft,
    )
    async with async_session() as s:
        from app.models import TeachingPlan

        draft = await s.scalar(
            select(TeachingPlan).where(TeachingPlan.status == TeachingPlanStatus.draft)
        )
        draft.draft_result = {"status": "drafted"}
        await s.commit()
        user = await s.get(User, tutor["user"]["id"])
        g = await s.get(Group, group["id"])
        await accept_plan(s, group=g, user=user)
    async with async_session() as s:
        lesson = await s.scalar(select(Lesson))
        new_slot = await s.scalar(select(PlanSlot).where(PlanSlot.lesson_id == lesson.id))
    assert new_slot is not None and new_slot.start_time == time(19, 15)
