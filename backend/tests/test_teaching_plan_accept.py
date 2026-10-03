"""Task 6.4 (AV-13): the tutor drafts, accepts and edits the teaching plan.

Jobs are driven with `process_one_job()` and the model is always faked
(QA-6, QA-7, QA-8)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import (
    Chapter,
    Job,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.services.plan_drafting import PLAN_DRAFT_JOB, ChapterAdvice, PlanWeightingResult
from app.workers.jobs import process_one_job
from tests.factories import make_subject, org_id

EXAM = date.today() + timedelta(days=120)


def _url(group, suffix=""):
    return f"/api/v1/groups/{group['id']}/plan{suffix}"


@pytest.fixture
async def chapters(subject):
    async with async_session() as s:
        rows = [
            Chapter(subject_id=subject["id"], code=f"C{i}", title=f"Chapter {i}", position=i)
            for i in (1, 2, 3)
        ]
        s.add_all(rows)
        await s.commit()
        return [c.id for c in rows]


@pytest.fixture
async def other_tutor(client, tutor):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-accept@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _save_inputs(client, tutor, group, **over):
    body = {"exam_date": EXAM.isoformat(), "lessons_per_week": 2, "lesson_minutes": 60}
    body.update(over)
    resp = await client.put(_url(group, "/inputs"), json=body, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    return resp.json()["draft"]["id"]


async def _add_slots(plan_id, chapter_ids, *, provenance=PlanSlotProvenance.generated, start=10):
    """Plan slots on consecutive days; returns their ids."""
    async with async_session() as s:
        rows = [
            PlanSlot(
                plan_id=plan_id,
                chapter_id=cid,
                scheduled_date=date.today() + timedelta(days=start + i),
                sequence=i + 1,
                provenance=provenance,
            )
            for i, cid in enumerate(chapter_ids)
        ]
        s.add_all(rows)
        await s.commit()
        return [r.id for r in rows]


async def _mark_drafted(plan_id, status="drafted"):
    async with async_session() as s:
        plan = await s.get(TeachingPlan, plan_id)
        plan.draft_result = {
            "status": status,
            "weight_source": "ai",
            "chapters": [],
            "failure": {"code": "no_chapters", "message": "boom"} if status == "failed" else None,
        }
        await s.commit()


async def _accepted_plan(group, tutor, chapter_ids, **kw):
    async with async_session() as s:
        plan = TeachingPlan(
            organization_id=await org_id(s),
            group_id=group["id"],
            status=TeachingPlanStatus.accepted,
            exam_date=EXAM,
            lessons_per_week=2,
            lesson_minutes=60,
            accepted_at=datetime.now(timezone.utc),
            accepted_by_id=tutor["user"]["id"],
        )
        s.add(plan)
        await s.commit()
        plan_id = plan.id
    return plan_id, await _add_slots(plan_id, chapter_ids, **kw)


# --- Draft trigger -------------------------------------------------------------


async def test_draft_without_saved_inputs_is_409(client, tutor, group):
    resp = await client.post(_url(group, "/draft"), headers=tutor["headers"])
    assert resp.status_code == 409


async def test_draft_enqueues_one_job_and_the_plan_shows_drafting(
    client, tutor, group, chapters, monkeypatch, fake_ai
):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete",
        fake_ai(
            PlanWeightingResult(
                chapters=[
                    ChapterAdvice(chapter_id=c, weight=w, reason=f"why {c}")
                    for c, w in zip(chapters, (1.0, 1.0, 2.0), strict=True)
                ]
            )
        ),
    )
    plan_id = await _save_inputs(client, tutor, group)

    first = await client.post(_url(group, "/draft"), headers=tutor["headers"])
    assert first.status_code == 202, first.text
    assert first.json()["draft"]["drafting"] is True
    # A second click while it is queued adds nothing.
    assert (await client.post(_url(group, "/draft"), headers=tutor["headers"])).status_code == 202
    async with async_session() as s:
        jobs = (await s.scalars(select(Job).where(Job.type == PLAN_DRAFT_JOB))).all()
    assert [j.payload for j in jobs] == [{"plan_id": plan_id}]

    assert await process_one_job() is True
    draft = (await client.get(_url(group), headers=tutor["headers"])).json()["draft"]
    assert draft["drafting"] is False
    assert draft["outcome"]["status"] == "drafted"
    assert draft["outcome"]["weight_source"] == "ai"
    assert [c["reason"] for c in draft["outcome"]["chapters"]] == [f"why {c}" for c in chapters]
    assert draft["outcome"]["chapters"][0]["chapter_title"] == "Chapter 1"
    slots = draft["slots"]
    assert slots
    keys = [(s["scheduled_date"], s["sequence"]) for s in slots]
    assert keys == sorted(keys)
    assert {s["provenance"] for s in slots} == {"generated"}
    assert {s["chapter_title"] for s in slots} == {"Chapter 1", "Chapter 2", "Chapter 3"}


async def test_get_renders_a_failed_draft_outcome(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    async with async_session() as s:
        plan = await s.get(TeachingPlan, plan_id)
        plan.draft_result = {
            "status": "failed",
            "weight_source": None,
            "degraded_reason": None,
            "chapters": [],
            "failure": {"code": "not_enough_lessons", "message": "Only 2 lessons fit"},
        }
        await s.commit()
    draft = (await client.get(_url(group), headers=tutor["headers"])).json()["draft"]
    assert draft["outcome"]["status"] == "failed"
    assert draft["outcome"]["failure_message"] == "Only 2 lessons fit"
    assert draft["slots"] == []


async def test_get_query_count_does_not_grow_with_slots(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    await _mark_drafted(plan_id)

    def count_during_get():
        queries = []

        def before(conn, cursor, statement, *a):
            queries.append(statement)

        return queries, before

    async def measure() -> int:
        queries, before = count_during_get()
        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            resp = await client.get(_url(group), headers=tutor["headers"])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        assert resp.status_code == 200
        return len(queries)

    await _add_slots(plan_id, chapters)
    few = await measure()
    await _add_slots(plan_id, chapters * 10, start=50)
    many = await measure()
    assert many == few


# --- Accept ---------------------------------------------------------------------


async def test_accept_with_no_slots_is_409(client, tutor, group):
    plan_id = await _save_inputs(client, tutor, group)
    await _mark_drafted(plan_id)
    resp = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert resp.status_code == 409
    assert "no lessons" in resp.json()["detail"]


async def test_accept_a_failed_draft_is_409(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    await _add_slots(plan_id, chapters)
    await _mark_drafted(plan_id, status="failed")
    resp = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert resp.status_code == 409
    async with async_session() as s:
        assert (await s.get(TeachingPlan, plan_id)).status is TeachingPlanStatus.draft


async def test_accept_without_a_draft_is_409(client, tutor, group):
    resp = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert resp.status_code == 409


async def test_accept_replaces_the_old_accepted_plan(client, tutor, group, chapters):
    old_id, old_slot_ids = await _accepted_plan(group, tutor, chapters)
    async with async_session() as s:
        s.add(PlanBreak(plan_id=old_id, start_date=EXAM, end_date=EXAM, label="Old break"))
        await s.commit()
    draft_id = await _save_inputs(client, tutor, group)
    await _add_slots(draft_id, chapters[:2])
    await _mark_drafted(draft_id)

    resp = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["draft"] is None
    assert body["accepted"]["id"] == draft_id
    assert len(body["accepted"]["slots"]) == 2
    assert body["accepted"]["accepted_at"] is not None

    async with async_session() as s:
        plans = (
            await s.scalars(select(TeachingPlan).where(TeachingPlan.group_id == group["id"]))
        ).all()
        assert [(p.id, p.status) for p in plans] == [(draft_id, TeachingPlanStatus.accepted)]
        assert plans[0].accepted_by_id == tutor["user"]["id"]
        # Nothing of the old plan survives, even where FKs are not enforced.
        assert not (await s.scalars(select(PlanSlot).where(PlanSlot.id.in_(old_slot_ids)))).all()
        assert not (await s.scalars(select(PlanBreak).where(PlanBreak.plan_id == old_id))).all()


async def test_accept_queues_a_readiness_recompute_for_every_student(
    client, tutor, group, subject, student, chapters
):
    draft_id = await _save_inputs(client, tutor, group)
    await _add_slots(draft_id, chapters)
    await _mark_drafted(draft_id)
    resp = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    async with async_session() as s:
        payloads = (
            await s.scalars(select(Job.payload).where(Job.type == "compute_readiness_v2"))
        ).all()
    assert {"student_id": student["user"]["id"], "subject_id": subject["id"]} in payloads
    assert len(payloads) == 1


# --- Edit a slot ----------------------------------------------------------------


async def _edit(client, tutor, group, slot_id, body):
    return await client.patch(_url(group, f"/slots/{slot_id}"), json=body, headers=tutor["headers"])


async def _slot(slot_id) -> PlanSlot:
    async with async_session() as s:
        return await s.get(PlanSlot, slot_id)


async def test_edit_sets_manually_modified_and_renumbers(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    # Move the first lesson after the others: numbering follows the dates.
    target = date.today() + timedelta(days=40)
    resp = await _edit(client, tutor, group, ids[0], {"scheduled_date": target.isoformat()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["provenance"] == "manually_modified"
    rows = [await _slot(i) for i in ids]
    assert [r.sequence for r in rows] == [3, 1, 2]
    assert rows[0].provenance is PlanSlotProvenance.manually_modified
    assert rows[1].provenance is PlanSlotProvenance.generated
    # Still a draft: an edit never asks for re-acceptance.
    async with async_session() as s:
        assert (await s.get(TeachingPlan, plan_id)).status is TeachingPlanStatus.draft


async def test_edit_changes_chapter_on_the_accepted_plan(client, tutor, group, chapters):
    plan_id, ids = await _accepted_plan(group, tutor, chapters)
    resp = await _edit(client, tutor, group, ids[0], {"chapter_id": chapters[2]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["chapter_id"] == chapters[2]
    async with async_session() as s:
        assert (await s.get(TeachingPlan, plan_id)).status is TeachingPlanStatus.accepted


@pytest.mark.parametrize("kept", [PlanSlotProvenance.confirmed, PlanSlotProvenance.completed])
async def test_edit_keeps_confirmed_and_completed_provenance(client, tutor, group, chapters, kept):
    _, ids = await _accepted_plan(group, tutor, chapters, provenance=kept)
    new = date.today() + timedelta(days=60)
    resp = await _edit(client, tutor, group, ids[0], {"scheduled_date": new.isoformat()})
    assert resp.status_code == 200, resp.text
    row = await _slot(ids[0])
    assert row.provenance is kept
    assert row.scheduled_date == new


async def test_edit_rejects_a_chapter_from_another_subject(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    async with async_session() as s:
        other = await make_subject(s, organization_id=await org_id(s), code="OTHER", name="Other")
        foreign = Chapter(subject_id=other.id, code="F1", title="Foreign", position=1)
        s.add(foreign)
        await s.commit()
        foreign_id = foreign.id
    resp = await _edit(client, tutor, group, ids[0], {"chapter_id": foreign_id})
    assert resp.status_code == 422
    assert (await _slot(ids[0])).chapter_id == chapters[0]


async def test_edit_rejects_a_date_in_a_break(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    day = date.today() + timedelta(days=30)
    async with async_session() as s:
        s.add(
            PlanBreak(
                plan_id=plan_id, start_date=day - timedelta(days=1), end_date=day, label="Easter"
            )
        )
        await s.commit()
    resp = await _edit(client, tutor, group, ids[0], {"scheduled_date": day.isoformat()})
    assert resp.status_code == 422
    assert "Easter" in resp.json()["detail"]
    assert (await _slot(ids[0])).provenance is PlanSlotProvenance.generated


@pytest.mark.parametrize("offset", [0, 5])
async def test_edit_rejects_the_exam_day_and_after(client, tutor, group, chapters, offset):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    day = EXAM + timedelta(days=offset)
    resp = await _edit(client, tutor, group, ids[0], {"scheduled_date": day.isoformat()})
    assert resp.status_code == 422


async def test_edit_with_nothing_to_change_is_422(client, tutor, group, chapters):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    assert (await _edit(client, tutor, group, ids[0], {})).status_code == 422


async def test_another_organizations_slot_is_404(
    client, tutor, other_tutor, group, subject, chapters
):
    plan_id = await _save_inputs(client, tutor, group)
    ids = await _add_slots(plan_id, chapters)
    # The other tutor's own class, but this tutor's slot id.
    async with async_session() as s:
        theirs = await s.scalar(select(User).where(User.email == "other-accept@example.com"))
        their_subject = await make_subject(s, organization_id=theirs.organization_id)
        await s.commit()
    mine = await client.post(
        "/api/v1/groups",
        json={"name": "Theirs", "subject_id": their_subject.id},
        headers=other_tutor,
    )
    assert mine.status_code == 201, mine.text
    target = (date.today() + timedelta(days=40)).isoformat()
    resp = await client.patch(
        _url(mine.json(), f"/slots/{ids[0]}"), json={"scheduled_date": target}, headers=other_tutor
    )
    assert resp.status_code == 404
    # And their own class is no door to ours.
    resp = await client.patch(
        _url(group, f"/slots/{ids[0]}"), json={"scheduled_date": target}, headers=other_tutor
    )
    assert resp.status_code == 404
    row = await _slot(ids[0])
    assert row.provenance is PlanSlotProvenance.generated


async def test_the_new_routes_refuse_other_tutors_classes(client, tutor, other_tutor, group):
    await _save_inputs(client, tutor, group)
    for suffix in ("/draft", "/accept"):
        resp = await client.post(_url(group, suffix), headers=other_tutor)
        assert resp.status_code == 404


# --- Authorization --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("post", "/draft"), ("post", "/accept"), ("patch", "/slots/1")],
)
async def test_a_student_is_forbidden_and_no_token_is_401(client, group, student, method, suffix):
    call = getattr(client, method)
    kwargs = {"json": {"chapter_id": 1}} if method == "patch" else {}
    forbidden = await call(_url(group, suffix), headers=student["headers"], **kwargs)
    assert forbidden.status_code == 403
    assert (await call(_url(group, suffix), **kwargs)).status_code == 401
