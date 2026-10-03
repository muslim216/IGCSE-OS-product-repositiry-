"""An accept that promotes the draft between a save's read and its write must not
have its inputs overwritten (cubic review of 6.4)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.db import async_session
from app.models import Lesson, PlanSlot, PlanSlotProvenance, TeachingPlan, TeachingPlanStatus
from app.services import teaching_plan as service
from tests.test_teaching_plan_accept import (
    _accepted_plan,
    _edit,
    _save_inputs,
    _slot,
    _url,
    chapters,  # noqa: F401  (pytest fixture)
)


async def test_a_save_racing_an_accept_leaves_the_accepted_plan_untouched(
    client, tutor, group, monkeypatch
):
    plan_id = await _save_inputs(client, tutor, group, lessons_per_week=2)
    real = service.draft_plan_for_group
    raced = {"done": False}

    async def promote_after_read(session, group_id):
        plan = await real(session, group_id)
        if plan is not None and not raced["done"]:
            raced["done"] = True
            # What a concurrent accept does, after we read the draft and before we write.
            await session.execute(
                update(TeachingPlan)
                .where(TeachingPlan.id == plan.id)
                .values(
                    status=TeachingPlanStatus.accepted,
                    accepted_at=datetime.now(timezone.utc),
                    accepted_by_id=tutor["user"]["id"],
                )
                .execution_options(synchronize_session=False)
            )
        return plan

    monkeypatch.setattr(service, "draft_plan_for_group", promote_after_read)
    resp = await client.put(
        _url(group, "/inputs"),
        json={
            "exam_date": (await _exam(plan_id)).isoformat(),
            "lessons_per_week": 5,
            "lesson_minutes": 60,
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as s:
        plans = {
            p.status: p
            for p in (
                await s.scalars(select(TeachingPlan).where(TeachingPlan.group_id == group["id"]))
            )
        }
    assert plans[TeachingPlanStatus.accepted].id == plan_id
    assert plans[TeachingPlanStatus.accepted].lessons_per_week == 2
    assert plans[TeachingPlanStatus.draft].lessons_per_week == 5


async def _exam(plan_id):
    async with async_session() as s:
        return (await s.get(TeachingPlan, plan_id)).exam_date


async def _confirm_after_plan_lock(monkeypatch, slot_id, lesson_id, *, provenance):
    """Land a lesson confirm right after edit_slot takes the plan lock: the point a
    concurrent confirm can reach it on Postgres before the slot is locked."""
    from sqlalchemy.ext.asyncio import AsyncSession

    real = AsyncSession.scalar
    raced = {"done": False}

    async def scalar(self, statement, *args, **kwargs):
        result = await real(self, statement, *args, **kwargs)
        text = str(statement)
        if not raced["done"] and "FOR UPDATE" in text and "teaching_plans" in text:
            raced["done"] = True
            await self.execute(
                update(PlanSlot)
                .where(PlanSlot.id == slot_id)
                .values(lesson_id=lesson_id, provenance=provenance)
                .execution_options(synchronize_session=False)
            )
        return result

    monkeypatch.setattr(AsyncSession, "scalar", scalar)


@pytest.mark.parametrize("provenance", [PlanSlotProvenance.confirmed, PlanSlotProvenance.generated])
async def test_a_slot_confirmed_during_an_edit_keeps_its_lesson_and_is_not_demoted(
    client, tutor, group, chapters, monkeypatch, provenance
):
    plan_id, ids = await _accepted_plan(group, tutor, chapters)
    async with async_session() as s:
        org = (await s.get(TeachingPlan, plan_id)).organization_id
        lesson = Lesson(organization_id=org, group_id=group["id"], date=date.today())
        s.add(lesson)
        await s.commit()
        lesson_id = lesson.id
    await _confirm_after_plan_lock(monkeypatch, ids[0], lesson_id, provenance=provenance)

    new = date.today() + timedelta(days=60)
    resp = await _edit(client, tutor, group, ids[0], {"scheduled_date": new.isoformat()})
    assert resp.status_code == 200, resp.text

    row = await _slot(ids[0])
    assert row.lesson_id == lesson_id
    # The edit must leave whatever the confirm wrote exactly as it was.
    assert row.provenance is provenance
