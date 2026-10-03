"""An accept that promotes the draft between a save's read and its write must not
have its inputs overwritten (cubic review of 6.4)."""

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db import async_session
from app.models import TeachingPlan, TeachingPlanStatus
from app.services import teaching_plan as service
from tests.test_teaching_plan_accept import _save_inputs, _url


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
