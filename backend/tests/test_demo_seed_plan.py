"""The demo class ships with an accepted teaching plan (task 6.4, E26)."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import PlanSlot, TeachingPlan, TeachingPlanStatus
from seed import demo

pytestmark = pytest.mark.usefixtures("no_ai_key")


async def test_demo_class_has_one_accepted_plan_with_slots_and_reseeding_adds_none():
    await demo.main()
    await demo.main()  # idempotent: the second run finds the demo and stops

    async with async_session() as session:
        plans = (await session.scalars(select(TeachingPlan))).all()
        assert [p.status for p in plans] == [TeachingPlanStatus.accepted]
        plan = plans[0]
        slots = (
            await session.scalars(
                select(PlanSlot).where(PlanSlot.plan_id == plan.id).order_by(PlanSlot.sequence)
            )
        ).all()
        assert slots
        assert [s.sequence for s in slots] == list(range(1, len(slots) + 1))
        assert all(s.scheduled_date < plan.exam_date for s in slots)
        assert plan.accepted_by_id is not None


async def test_the_demo_plan_reflows_instead_of_being_skipped():
    from app.services.plan_reflow import reflow_plan_slots

    await demo.main()
    async with async_session() as session:
        plan = (await session.scalars(select(TeachingPlan))).one()
        assert plan.draft_result["status"] == "drafted"
        assert plan.draft_result["weight_source"] == "stored_chapter_weights"
        outcome = await reflow_plan_slots(session, plan.id)
        assert outcome is not None
        assert outcome["status"] == "reflowed"
        assert plan.draft_result["reflow"]["status"] == "reflowed"
