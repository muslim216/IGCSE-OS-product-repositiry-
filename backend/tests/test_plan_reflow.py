"""Automatic plan reflow when a subject's chapters change (task 6.8).

Jobs are driven with `process_one_job()` (QA-6). The reflow is mechanical, so
every test also proves the model is never asked (QA-8)."""

from datetime import date, datetime, timezone
from datetime import time as dtime

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Chapter,
    Group,
    Job,
    JobStatus,
    Organization,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    User,
    UserRole,
)
from app.services.plan_reflow import PLAN_REFLOW_JOB, enqueue_reflow_for_subject
from app.workers.jobs import process_one_job
from tests.factories import make_subject
from tests.test_syllabus_upload import CHAPTERS, draft_of, extraction_returning, upload_pdf

TODAY = datetime(2027, 1, 4, 9, 0, tzinfo=timezone.utc)  # a Monday
EXAM = date(2027, 2, 1)  # Mon/Thu: 7, 11, 14, 18, 21, 25, 28 Jan are free after today = 7
G = PlanSlotProvenance.generated


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.services.plan_reflow.now_in", lambda tz: TODAY)


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    """Reflow is mechanical: if anything reaches a model, the test fails."""

    async def _boom(*a, **k):
        raise AssertionError("reflow must not call the model")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _boom)


DRAFTED = {"status": "drafted"}


async def make_class(session, org_id, tutor_id, subject_id, *, status, name="Year 11"):
    group = Group(organization_id=org_id, tutor_id=tutor_id, subject_id=subject_id, name=name)
    session.add(group)
    await session.flush()
    session.add_all(
        ScheduleSlot(group_id=group.id, weekday=d, start_time=dtime(17, 0)) for d in (0, 3)
    )
    plan = TeachingPlan(
        organization_id=org_id,
        group_id=group.id,
        status=status,
        exam_date=EXAM,
        lessons_per_week=2,
        lesson_minutes=60,
        draft_result=DRAFTED,
    )
    if status is TeachingPlanStatus.accepted:
        plan.accepted_at = TODAY
        plan.accepted_by_id = tutor_id
    session.add(plan)
    await session.flush()
    return group, plan


@pytest.fixture
async def world():
    async with async_session() as session:
        org = Organization(name="Org")
        session.add(org)
        await session.flush()
        tutor = User(
            email="t@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="T",
            organization_id=org.id,
        )
        session.add(tutor)
        subject = await make_subject(session, organization_id=org.id)
        await session.flush()
        chapters = [
            Chapter(subject_id=subject.id, code=f"C{i}", title=f"Chapter {i}", position=i)
            for i in (1, 2, 3)
        ]
        session.add_all(chapters)
        _, plan = await make_class(
            session, org.id, tutor.id, subject.id, status=TeachingPlanStatus.draft
        )
        await session.flush()
        # Weights the drafting run stored, deliberately unlike the chapters' own
        # stored weight (1.0): reflow must use these, not recompute them.
        plan.draft_result = {
            "status": "drafted",
            "chapters": [
                {"chapter_id": cid, "weight": w, "reason": None}
                for cid, w in zip((c.id for c in chapters), (1.0, 3.0, 1.0), strict=True)
            ],
        }
        await session.commit()
        return {
            "org_id": org.id,
            "tutor_id": tutor.id,
            "plan_id": plan.id,
            "subject_id": subject.id,
            "chapter_ids": [c.id for c in chapters],
        }


async def reflow(plan_id: int) -> None:
    async with async_session() as session:
        await enqueue_reflow_for_subject_plan(session, plan_id)
        await session.commit()
    assert await process_one_job() is True


async def enqueue_reflow_for_subject_plan(session, plan_id):
    from app.workers.jobs import enqueue

    await enqueue(session, PLAN_REFLOW_JOB, {"plan_id": plan_id})


async def slots(plan_id: int) -> list[PlanSlot]:
    async with async_session() as session:
        return list(
            (
                await session.scalars(
                    select(PlanSlot)
                    .where(PlanSlot.plan_id == plan_id)
                    .order_by(PlanSlot.scheduled_date, PlanSlot.id)
                )
            ).all()
        )


def shape(rows):
    return [(r.scheduled_date, r.chapter_id, r.provenance, r.sequence) for r in rows]


def chapter_order(rows, chapter_ids):
    """The chapters in the order they are taught, runs collapsed."""
    order: list[int] = []
    for row in rows:
        if not order or order[-1] != row.chapter_id:
            order.append(row.chapter_id)
    assert set(order) <= set(chapter_ids)
    return order


async def set_positions(positions: dict[int, int]) -> None:
    async with async_session() as session:
        for chapter_id, position in positions.items():
            (await session.get(Chapter, chapter_id)).position = position
        await session.commit()


async def add_slot(plan_id, chapter_id, day, provenance):
    async with async_session() as session:
        slot = PlanSlot(
            plan_id=plan_id,
            chapter_id=chapter_id,
            scheduled_date=day,
            sequence=0,
            provenance=provenance,
        )
        session.add(slot)
        await session.commit()
        return slot.id


async def test_a_drafted_plan_is_laid_out_and_the_outcome_recorded(world):
    await reflow(world["plan_id"])
    rows = await slots(world["plan_id"])
    assert len(rows) == 7
    assert all(r.scheduled_date > TODAY.date() for r in rows)
    assert [r.sequence for r in rows] == list(range(1, 8))
    async with async_session() as session:
        result = (await session.get(TeachingPlan, world["plan_id"])).draft_result
    assert result["status"] == "drafted"  # the 6.3 record is kept
    assert result["reflow"]["status"] == "reflowed"
    assert result["reflow"]["slots_written"] == 7


async def test_reordering_chapters_moves_the_generated_future_slots(world):
    a, b, c = world["chapter_ids"]
    await reflow(world["plan_id"])
    assert chapter_order(await slots(world["plan_id"]), [a, b, c]) == [a, b, c]
    await set_positions({a: 3, b: 2, c: 1})
    await reflow(world["plan_id"])
    assert chapter_order(await slots(world["plan_id"]), [a, b, c]) == [c, b, a]


@pytest.mark.parametrize("status", [TeachingPlanStatus.draft, TeachingPlanStatus.accepted])
async def test_draft_and_accepted_plans_both_reflow_without_changing_status(world, status):
    a, b, c = world["chapter_ids"]
    async with async_session() as session:
        plan = await session.get(TeachingPlan, world["plan_id"])
        plan.status = status
        plan.accepted_at = TODAY if status is TeachingPlanStatus.accepted else None
        plan.accepted_by_id = world["tutor_id"] if status is TeachingPlanStatus.accepted else None
        await session.commit()
    await reflow(world["plan_id"])
    await set_positions({a: 3, b: 2, c: 1})
    await reflow(world["plan_id"])
    assert chapter_order(await slots(world["plan_id"]), [a, b, c]) == [c, b, a]
    async with async_session() as session:
        plan = await session.get(TeachingPlan, world["plan_id"])
    assert plan.status is status  # no acceptance step, nothing changes status


async def test_the_tutors_slots_and_past_and_todays_slots_never_move(world):
    a, b, c = world["chapter_ids"]
    pid = world["plan_id"]
    kept = {
        await add_slot(pid, c, date(2027, 1, 11), PlanSlotProvenance.manually_modified),
        await add_slot(pid, c, date(2027, 1, 14), PlanSlotProvenance.confirmed),
        await add_slot(pid, a, date(2027, 1, 4), PlanSlotProvenance.completed),
        await add_slot(pid, a, date(2027, 1, 1), G),  # past and generated
        await add_slot(pid, b, date(2027, 1, 4), G),  # today and generated
    }
    before = {r.id: (r.scheduled_date, r.chapter_id, r.provenance) for r in await slots(pid)}
    await set_positions({a: 3, b: 2, c: 1})
    await reflow(pid)
    after = await slots(pid)
    by_id = {r.id: (r.scheduled_date, r.chapter_id, r.provenance) for r in after}
    for slot_id in kept:
        assert by_id[slot_id] == before[slot_id]
    # Their dates are taken: no regenerated lesson lands on one.
    new = [r for r in after if r.id not in kept]
    taken = {before[i][0] for i in kept}
    assert all(r.scheduled_date not in taken for r in new)
    assert all(r.scheduled_date > TODAY.date() and r.provenance is G for r in new)
    assert [r.sequence for r in after] == list(range(1, len(after) + 1))


async def test_a_new_chapter_gets_slots_without_a_model_call(world):
    await reflow(world["plan_id"])
    async with async_session() as session:
        extra = Chapter(subject_id=world["subject_id"], code="C4", title="New", position=4)
        session.add(extra)
        await session.commit()
        new_id = extra.id
    await reflow(world["plan_id"])
    assert new_id in {r.chapter_id for r in await slots(world["plan_id"])}


async def test_a_chapter_gone_from_the_subject_loses_its_generated_future_slots(world):
    # No path deletes a chapter today (apply only adds, retitles and reorders, and
    # `plan_slots.chapter_id` is ON DELETE RESTRICT), so "gone" is modelled the way
    # production would have to do it: the chapter's generated slots are removed
    # first, then the row. Reflow must then lay the plan out without it.
    a, b, c = world["chapter_ids"]
    await reflow(world["plan_id"])
    assert c in {r.chapter_id for r in await slots(world["plan_id"])}
    async with async_session() as session:
        await session.execute(PlanSlot.__table__.delete().where(PlanSlot.chapter_id == c))
        await session.delete(await session.get(Chapter, c))
        await session.commit()
    await reflow(world["plan_id"])
    rows = await slots(world["plan_id"])
    assert c not in {r.chapter_id for r in rows}
    assert {r.chapter_id for r in rows} == {a, b}
    assert len(rows) == 7  # the freed lessons went to the remaining chapters


async def test_an_infeasible_reflow_changes_nothing_and_says_why(world):
    await reflow(world["plan_id"])
    before = shape(await slots(world["plan_id"]))
    async with async_session() as session:
        session.add_all(
            Chapter(subject_id=world["subject_id"], code=f"X{i}", title=f"X{i}", position=10 + i)
            for i in range(6)
        )
        await session.commit()
    await reflow(world["plan_id"])  # 9 chapters, 7 lessons
    assert shape(await slots(world["plan_id"])) == before
    async with async_session() as session:
        result = (await session.get(TeachingPlan, world["plan_id"])).draft_result
    assert result["reflow"]["status"] == "failed"
    assert result["reflow"]["failure"]["code"] == "not_enough_lessons"
    assert result["status"] == "drafted"


async def test_rerunning_is_idempotent(world):
    a, b, c = world["chapter_ids"]
    await reflow(world["plan_id"])
    await set_positions({a: 2, b: 3, c: 1})
    await reflow(world["plan_id"])
    first = shape(await slots(world["plan_id"]))
    await reflow(world["plan_id"])
    assert shape(await slots(world["plan_id"])) == first


async def test_a_plan_that_was_never_drafted_is_left_alone(world):
    async with async_session() as session:
        (await session.get(TeachingPlan, world["plan_id"])).draft_result = None
        await session.commit()
    await reflow(world["plan_id"])
    assert await slots(world["plan_id"]) == []


async def test_a_plan_that_is_gone_finishes_quietly(world):
    await reflow(world["plan_id"] + 999)


async def test_enqueue_covers_draft_and_accepted_plans_of_the_subjects_classes_only_and_never_dedupes(
    world,
):
    async with async_session() as session:
        _, accepted = await make_class(
            session,
            world["org_id"],
            world["tutor_id"],
            world["subject_id"],
            status=TeachingPlanStatus.accepted,
            name="Year 10",
        )
        # Same organization, another subject.
        other_subject = await make_subject(
            session, organization_id=world["org_id"], code="OTHER", name="Other"
        )
        await session.flush()
        _, other_plan = await make_class(
            session,
            world["org_id"],
            world["tutor_id"],
            other_subject.id,
            status=TeachingPlanStatus.draft,
            name="Other class",
        )
        # Another organization's class that (wrongly) points at this subject.
        org2 = Organization(name="Org2")
        session.add(org2)
        await session.flush()
        tutor2 = User(
            email="t2@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="T2",
            organization_id=org2.id,
        )
        session.add(tutor2)
        await session.flush()
        _, foreign = await make_class(
            session,
            org2.id,
            tutor2.id,
            world["subject_id"],
            status=TeachingPlanStatus.draft,
            name="Foreign",
        )
        await session.commit()
        accepted_id, other_id, foreign_id = accepted.id, other_plan.id, foreign.id

    async with async_session() as session:
        assert await enqueue_reflow_for_subject(session, world["subject_id"]) == 2
        await session.commit()
    async with async_session() as session:
        jobs = (await session.scalars(select(Job).where(Job.type == PLAN_REFLOW_JOB))).all()
    queued = {j.payload["plan_id"] for j in jobs}
    assert queued == {world["plan_id"], accepted_id}
    assert other_id not in queued and foreign_id not in queued

    # Never deduped: a second call queues again, and running both is harmless.
    async with async_session() as session:
        assert await enqueue_reflow_for_subject(session, world["subject_id"]) == 2
        await session.commit()
    async with async_session() as session:
        jobs = (await session.scalars(select(Job).where(Job.type == PLAN_REFLOW_JOB))).all()
    assert len(jobs) == 4
    for _ in range(4):
        assert await process_one_job() is True
    first = shape(await slots(world["plan_id"]))
    assert await enqueue_reflow_for_subject_plan_run(world["plan_id"]) == first


async def enqueue_reflow_for_subject_plan_run(plan_id):
    await reflow(plan_id)
    return shape(await slots(plan_id))


async def test_applying_a_syllabus_reflows_the_subjects_plans(client, tutor, monkeypatch):
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=CHAPTERS)),
    )
    first = await upload_pdf(client, tutor)
    applied = await client.post(f"/api/v1/syllabus-uploads/{first}/apply", headers=tutor["headers"])
    assert applied.status_code == 200, applied.text
    subject_id = applied.json()["subject_id"]
    async with async_session() as session:
        org_id = (await session.get(User, tutor["user"]["id"])).organization_id
        _, plan = await make_class(
            session,
            org_id,
            tutor["user"]["id"],
            subject_id,
            status=TeachingPlanStatus.accepted,
        )
        await session.commit()
        plan_id = plan.id
    await reflow(plan_id)  # lay out chapters "1", "2"
    ids = {c.code: c.id for c in await _chapters(subject_id)}
    assert chapter_order(await slots(plan_id), list(ids.values())) == [ids["1"], ids["2"]]

    # The tutor reorders the syllabus and applies it again.
    reordered = [CHAPTERS[1], CHAPTERS[0]]
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=reordered)),
    )
    second = await upload_pdf(client, tutor, title="v2", name="v2.pdf")
    resp = await client.post(f"/api/v1/syllabus-uploads/{second}/apply", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        pending = (
            await session.scalars(
                select(Job).where(Job.type == PLAN_REFLOW_JOB, Job.status == JobStatus.pending)
            )
        ).all()
    assert [j.payload["plan_id"] for j in pending] == [plan_id]  # committed with the chapters
    assert await process_one_job() is True  # the reflow the apply enqueued
    assert chapter_order(await slots(plan_id), list(ids.values())) == [ids["2"], ids["1"]]


async def _chapters(subject_id):
    async with async_session() as session:
        return list(
            (await session.scalars(select(Chapter).where(Chapter.subject_id == subject_id))).all()
        )


async def test_stored_draft_weights_drive_the_allocation(world):
    a, b, c = world["chapter_ids"]
    await reflow(world["plan_id"])
    counts = dict.fromkeys((a, b, c), 0)
    for row in await slots(world["plan_id"]):
        counts[row.chapter_id] += 1
    # 1:3:1 over 7 lessons. An even split (stored Chapter.weight) would be 3/2/2.
    assert counts[b] > counts[a] and counts[b] > counts[c]
    assert counts[b] >= 4


async def test_past_and_kept_slots_are_credited_to_their_chapter(world):
    a, b, c = world["chapter_ids"]
    await reflow(world["plan_id"])
    baseline_b = sum(1 for r in await slots(world["plan_id"]) if r.chapter_id == b)
    async with async_session() as session:
        await session.execute(
            PlanSlot.__table__.delete().where(PlanSlot.plan_id == world["plan_id"])
        )
        await session.commit()
    await add_slot(world["plan_id"], b, date(2027, 1, 1), G)
    await add_slot(world["plan_id"], b, date(2027, 1, 4), G)
    await reflow(world["plan_id"])
    new_b = sum(
        1
        for r in await slots(world["plan_id"])
        if r.chapter_id == b and r.scheduled_date > TODAY.date()
    )
    assert new_b < baseline_b


@pytest.mark.parametrize("draft_status", ["stale", "failed"])
async def test_a_stale_or_failed_draft_is_skipped_and_the_skip_recorded(world, draft_status):
    async with async_session() as session:
        plan = await session.get(TeachingPlan, world["plan_id"])
        plan.draft_result = {**plan.draft_result, "status": draft_status}
        await session.commit()
    await reflow(world["plan_id"])
    assert await slots(world["plan_id"]) == []
    async with async_session() as session:
        result = (await session.get(TeachingPlan, world["plan_id"])).draft_result
    assert result["status"] == draft_status
    assert result["reflow"]["status"] == "skipped"
    assert result["reflow"]["reason"]


async def test_a_failure_keeps_the_previous_success_time(world):
    await reflow(world["plan_id"])
    async with async_session() as session:
        first = (await session.get(TeachingPlan, world["plan_id"])).draft_result["reflow"]["at"]
        session.add_all(
            Chapter(subject_id=world["subject_id"], code=f"X{i}", title=f"X{i}", position=10 + i)
            for i in range(6)
        )
        await session.commit()
    await reflow(world["plan_id"])
    await reflow(world["plan_id"])  # a second failure still remembers the success
    async with async_session() as session:
        reflow_result = (await session.get(TeachingPlan, world["plan_id"])).draft_result["reflow"]
    assert reflow_result["status"] == "failed"
    assert reflow_result["last_success_at"] == first


async def test_tomorrow_is_the_organizations_day_not_utc(world, monkeypatch):
    from zoneinfo import ZoneInfo

    async with async_session() as session:
        (await session.get(Organization, world["org_id"])).timezone = "Africa/Cairo"
        await session.commit()
    # 22:30 UTC on Sunday 3 Jan is already 00:30 Monday 4 Jan in Cairo.
    instant = datetime(2027, 1, 3, 22, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.services.plan_reflow.now_in", lambda tz: instant.astimezone(ZoneInfo(tz or "UTC"))
    )
    await reflow(world["plan_id"])
    dates = {r.scheduled_date for r in await slots(world["plan_id"])}
    # Monday 4 Jan is Cairo's today, so it is not moved onto; a UTC clock would.
    assert date(2027, 1, 4) not in dates
    assert min(dates) == date(2027, 1, 7)


async def test_a_failed_enqueue_rolls_the_whole_apply_back(client, tutor, monkeypatch):
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=CHAPTERS)),
    )
    upload_id = await upload_pdf(client, tutor)

    async def _boom(session, subject_id):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.api.syllabus_uploads.enqueue_reflow_for_subject", _boom)
    # The client re-raises app exceptions; a deployment would answer 500. Either
    # way no success may be reported.
    try:
        resp = await client.post(
            f"/api/v1/syllabus-uploads/{upload_id}/apply", headers=tutor["headers"]
        )
    except RuntimeError:
        pass
    else:
        assert resp.status_code >= 500
    async with async_session() as session:
        assert (await session.scalars(select(Chapter))).all() == []
    detail = await client.get(f"/api/v1/syllabus-uploads/{upload_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "review"


async def test_reapplying_an_unchanged_chapter_list_or_a_topic_only_edit_queues_nothing(
    client, tutor, monkeypatch
):
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=CHAPTERS)),
    )
    first = await upload_pdf(client, tutor)
    applied = await client.post(f"/api/v1/syllabus-uploads/{first}/apply", headers=tutor["headers"])
    subject_id = applied.json()["subject_id"]
    async with async_session() as session:
        org_id = (await session.get(User, tutor["user"]["id"])).organization_id
        await make_class(
            session, org_id, tutor["user"]["id"], subject_id, status=TeachingPlanStatus.draft
        )
        await session.commit()

    async def pending_jobs():
        async with async_session() as session:
            return (await session.scalars(select(Job).where(Job.type == PLAN_REFLOW_JOB))).all()

    assert await pending_jobs() == []  # the plan was created after the first apply

    topic_edit = [
        {**CHAPTERS[0], "topics": [{**CHAPTERS[0]["topics"][0], "title": "Renamed topic"}]},
        CHAPTERS[1],
    ]
    for chapters in (CHAPTERS, topic_edit):
        monkeypatch.setattr(
            "app.services.syllabus_extraction._run_extraction",
            extraction_returning(draft_of(chapters=chapters)),
        )
        again = await upload_pdf(client, tutor, title="again", name="again.pdf")
        resp = await client.post(
            f"/api/v1/syllabus-uploads/{again}/apply", headers=tutor["headers"]
        )
        assert resp.status_code == 200, resp.text
        assert await pending_jobs() == []  # nothing queued

    # A retitle does change what the plan shows, so it does queue.
    retitled = [{**CHAPTERS[0], "title": "Renamed chapter"}, CHAPTERS[1]]
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=retitled)),
    )
    again = await upload_pdf(client, tutor, title="retitle", name="retitle.pdf")
    resp = await client.post(f"/api/v1/syllabus-uploads/{again}/apply", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert len(await pending_jobs()) == 1
