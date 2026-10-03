"""Task 6.4 review fixes: a draft goes stale when its inputs change, and the
drafting-job lookup does not depend on how busy the queue is."""

from datetime import timedelta

from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, TeachingPlan
from app.services.plan_drafting import PLAN_DRAFT_JOB
from tests.test_teaching_plan_accept import (  # noqa: F401  (fixtures)
    EXAM,
    _add_slots,
    _mark_drafted,
    _save_inputs,
    _url,
    chapters,
)


async def _drafted_draft(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    await _add_slots(plan_id, chapters)
    await _mark_drafted(plan_id)
    return plan_id


async def _status(plan_id):
    async with async_session() as s:
        return (await s.get(TeachingPlan, plan_id)).draft_result["status"]


async def _accept(client, tutor, group):
    return await client.post(_url(group, "/accept"), headers=tutor["headers"])


async def test_changing_an_input_makes_the_draft_stale_and_unacceptable(
    client, tutor, group, chapters
):
    plan_id = await _drafted_draft(client, tutor, group, chapters)
    await _save_inputs(client, tutor, group, lessons_per_week=3)
    assert await _status(plan_id) == "stale"
    resp = await _accept(client, tutor, group)
    assert resp.status_code == 409
    assert "changed since this draft" in resp.json()["detail"]
    draft = (await client.get(_url(group), headers=tutor["headers"])).json()["draft"]
    assert draft["outcome"]["status"] == "stale"


async def test_an_unchanged_save_keeps_the_draft_drafted(client, tutor, group, chapters):
    plan_id = await _drafted_draft(client, tutor, group, chapters)
    await _save_inputs(client, tutor, group)
    assert await _status(plan_id) == "drafted"
    assert (await _accept(client, tutor, group)).status_code == 200


async def test_adding_a_break_makes_the_draft_stale(client, tutor, group, chapters):
    plan_id = await _drafted_draft(client, tutor, group, chapters)
    day = (EXAM - timedelta(days=30)).isoformat()
    resp = await client.post(
        _url(group, "/breaks"),
        json={"start_date": day, "end_date": day, "label": "Trip"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await _status(plan_id) == "stale"
    assert (await _accept(client, tutor, group)).status_code == 409


async def test_removing_a_break_makes_the_draft_stale(client, tutor, group, chapters):
    plan_id = await _drafted_draft(client, tutor, group, chapters)
    day = (EXAM - timedelta(days=30)).isoformat()
    created = await client.post(
        _url(group, "/breaks"),
        json={"start_date": day, "end_date": day, "label": "Trip"},
        headers=tutor["headers"],
    )
    # Back to a clean drafted state, then remove: the removal alone must stale it.
    await _mark_drafted(plan_id)
    resp = await client.delete(
        _url(group, f"/breaks/{created.json()['id']}"), headers=tutor["headers"]
    )
    assert resp.status_code == 204
    assert await _status(plan_id) == "stale"
    assert (await _accept(client, tutor, group)).status_code == 409


async def test_a_pending_draft_job_is_found_among_many_other_jobs(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    async with async_session() as s:
        s.add(Job(type=PLAN_DRAFT_JOB, payload={"plan_id": plan_id}, status=JobStatus.pending))
        await s.flush()
        s.add_all(
            Job(type=PLAN_DRAFT_JOB, payload={"plan_id": plan_id + 1000 + i}, status=JobStatus.done)
            for i in range(250)
        )
        await s.commit()
        assert (await s.scalars(select(Job.id))).first() is not None
    draft = (await client.get(_url(group), headers=tutor["headers"])).json()["draft"]
    assert draft["drafting"] is True
