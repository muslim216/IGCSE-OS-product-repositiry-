"""Task 6.6 (AV-18): behind-schedule detection and the one-click re-plan.

Behind means accepted-plan slots dated before the tutor's today with no lesson
recorded. Nothing reschedules itself: the re-plan makes a draft and waits.
Jobs are driven with `process_one_job()`, the model is always faked (QA-6..8)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event, select

from app.db import async_session, engine
from app.models import (
    Chapter,
    Group,
    Job,
    Lesson,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.services.plan_drafting import PLAN_DRAFT_JOB, ChapterAdvice, PlanWeightingResult
from app.services.plan_progress import SlotFact, compute_progress
from app.workers.jobs import process_one_job
from tests.factories import make_subject, org_id

TODAY = date(2026, 10, 3)
EXAM = TODAY + timedelta(days=120)
G = PlanSlotProvenance.generated


def _d(n: int) -> date:
    return TODAY + timedelta(days=n)


def _url(group, suffix=""):
    return f"/api/v1/groups/{group['id']}/plan{suffix}"


@pytest.fixture
def frozen(monkeypatch):
    """One fixed day for every place that asks the tutor's clock."""

    def fake(_zone):
        return datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=timezone.utc)

    for mod in ("plan_progress", "today", "plan_drafting"):
        monkeypatch.setattr(f"app.services.{mod}.now_in", fake)
    monkeypatch.setattr("app.api.teaching_plans.now_in", fake)


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


async def _register(client, email):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": email, "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _plan(group_id, tutor_id, org, slots, *, status=TeachingPlanStatus.accepted):
    """`slots`: (chapter_id, day offset, provenance[, lesson?]) tuples. A truthy
    fourth item gives the slot a recorded lesson. Returns (plan id, slot ids)."""
    async with async_session() as s:
        plan = TeachingPlan(
            organization_id=org,
            group_id=group_id,
            status=status,
            exam_date=EXAM,
            lessons_per_week=2,
            lesson_minutes=60,
        )
        if status is TeachingPlanStatus.accepted:
            plan.accepted_at = datetime.now(timezone.utc)
            plan.accepted_by_id = tutor_id
        s.add(plan)
        await s.flush()
        ids = []
        for i, (chapter_id, offset, prov, *lesson) in enumerate(slots, start=1):
            lesson_id = None
            if lesson and lesson[0]:
                row = Lesson(
                    organization_id=org, group_id=group_id, date=_d(offset), duration_min=60
                )
                s.add(row)
                await s.flush()
                lesson_id = row.id
            slot = PlanSlot(
                plan_id=plan.id,
                chapter_id=chapter_id,
                scheduled_date=_d(offset),
                sequence=i,
                provenance=prov,
                lesson_id=lesson_id,
            )
            s.add(slot)
            await s.flush()
            ids.append(slot.id)
        await s.commit()
        return plan.id, ids


async def _ctx(group, tutor):
    async with async_session() as s:
        return await org_id(s), tutor["user"]["id"]


# --- The pure maths -------------------------------------------------------------


def _fact(offset, *, lesson=False, prov=G, seq=1, sid=1, cid=1):
    return SlotFact(_d(offset), seq, sid, cid, f"C{cid}", f"Chapter {cid}", lesson, prov)


def test_compute_progress_counts_only_untaught_slots_before_today():
    p = compute_progress(
        [
            _fact(-5, sid=1, cid=1),  # not recorded
            _fact(-4, sid=2, cid=2, lesson=True),  # recorded
            _fact(-3, sid=3, prov=PlanSlotProvenance.completed),  # marked taught, no lesson row
            _fact(-2, sid=4, cid=3),  # not recorded
            _fact(0, sid=5),  # today: the day is not over
            _fact(4, sid=6),  # future
        ],
        TODAY,
    )
    assert (p.planned_to_date, p.taught_to_date, p.missed) == (4, 2, 2)
    assert p.earliest_missed_date == _d(-5)
    assert p.earliest_missed_chapter == (1, "C1", "Chapter 1")


def test_compute_progress_with_nothing_due_is_zero_and_has_no_earliest():
    p = compute_progress([_fact(0), _fact(3)], TODAY)
    assert (p.planned_to_date, p.taught_to_date, p.missed) == (0, 0, 0)
    assert p.earliest_missed_date is None and p.earliest_missed_chapter is None


# --- GET /plan progress ---------------------------------------------------------


async def test_progress_counts_the_accepted_plan_and_ignores_a_draft(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    c1, c2, c3 = chapters
    await _plan(
        group["id"],
        uid,
        org,
        [
            (c1, -6, G),  # not recorded: earliest
            (c2, -5, G, True),  # recorded lesson
            (c3, -4, PlanSlotProvenance.confirmed),  # taught
            (c2, -3, G),  # not recorded
            (c3, 0, G),  # today: never counted
            (c3, 5, G),
        ],
    )
    # A draft with many past slots must not move the numbers (nothing reads a draft).
    await _plan(
        group["id"],
        uid,
        org,
        [(c1, -9, G), (c1, -8, G), (c1, -7, G)],
        status=TeachingPlanStatus.draft,
    )
    body = (await client.get(_url(group), headers=tutor["headers"])).json()
    assert body["progress"] == {
        "planned_to_date": 4,
        "taught_to_date": 2,
        "missed": 2,
        "earliest_missed_date": _d(-6).isoformat(),
        "earliest_missed_chapter": {"id": c1, "code": "C1", "title": "Chapter 1"},
    }


async def test_no_accepted_plan_has_no_progress_and_a_future_plan_is_zero_not_null(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    assert (await client.get(_url(group), headers=tutor["headers"])).json()["progress"] is None
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)], status=TeachingPlanStatus.draft)
    assert (await client.get(_url(group), headers=tutor["headers"])).json()["progress"] is None
    await _plan(group["id"], uid, org, [(chapters[0], 4, G)])
    progress = (await client.get(_url(group), headers=tutor["headers"])).json()["progress"]
    assert progress["missed"] == 0 and progress["earliest_missed_date"] is None


async def test_today_is_the_tutors_not_the_servers(client, tutor, group, chapters, monkeypatch):
    """A slot on the calendar day it is in Pago Pago is 'today' there and a past
    day in Kiritimati. One fixed instant feeds both the test and the service, so
    no wall-clock read can fall either side of midnight between them."""
    from zoneinfo import ZoneInfo

    instant = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)

    def fixed(zone):
        return instant.astimezone(ZoneInfo(zone))

    monkeypatch.setattr("app.services.plan_progress.now_in", fixed)
    early = fixed("Pacific/Pago_Pago").date()
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], 0, G)])
    async with async_session() as s:
        slot = await s.scalar(select(PlanSlot))
        slot.scheduled_date = early
        await s.commit()
        user = await s.get(User, uid)
        results = {}
        for zone in ("Pacific/Pago_Pago", "Pacific/Kiritimati"):
            user.time_zone = zone
            await s.commit()
            resp = await client.get(_url(group), headers=tutor["headers"])
            results[zone] = resp.json()["progress"]["missed"]
    assert results == {"Pacific/Pago_Pago": 0, "Pacific/Kiritimati": 1}


async def test_an_admin_viewing_a_tutors_class_sees_its_real_progress(
    client, tutor, group, chapters, frozen
):
    """The per-class overview is authorised by the owned-group check; the tutor
    filter belongs to the home list only, or an admin would see a false zero."""
    from app.models import UserRole

    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G), (chapters[0], -2, G)])
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Admin", "email": "admin-progress@example.com", "password": "password123"},
    )
    async with async_session() as s:
        admin = await s.get(User, reg.json()["user"]["id"])
        admin.role = UserRole.admin
        admin.organization_id = org
        await s.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin-progress@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    body = (await client.get(_url(group), headers=headers)).json()
    assert body["progress"]["missed"] == 2
    # The home stays the viewer's own classes.
    home = (await client.get("/api/v1/today", headers=headers)).json()
    assert home["behind_classes"] == []


# --- The tutor home -------------------------------------------------------------


async def _class(client, tutor, subject, name):
    resp = await client.post(
        "/api/v1/groups",
        json={"name": name, "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_home_lists_behind_classes_most_first_scoped_to_this_tutor(
    client, tutor, group, subject, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    c1 = chapters[0]
    two = await _class(client, tutor, subject, "Two behind")
    clear = await _class(client, tutor, subject, "On track")
    await _plan(group["id"], uid, org, [(c1, -3, G)])  # 1 behind ("Chem Y10")
    await _plan(two["id"], uid, org, [(c1, -4, G), (c1, -2, G)])
    await _plan(clear["id"], uid, org, [(c1, -4, G, True)])
    # A draft's past slots and a class with no plan are never behind.
    await _class(client, tutor, subject, "No plan")
    other_draft = await _class(client, tutor, subject, "Draft only")
    await _plan(other_draft["id"], uid, org, [(c1, -4, G)], status=TeachingPlanStatus.draft)
    # Another tutor's behind class, in another organization.
    headers = await _register(client, "other-home@example.com")
    async with async_session() as s:
        other = await s.scalar(select(User).where(User.email == "other-home@example.com"))
        subj = await make_subject(s, organization_id=other.organization_id, code="OTH1")
        theirs = Group(
            organization_id=other.organization_id,
            tutor_id=other.id,
            subject_id=subj.id,
            name="Theirs",
        )
        ch = Chapter(subject_id=subj.id, code="1", title="Theirs", position=1)
        s.add_all([theirs, ch])
        await s.flush()
        theirs_id, ch_id = theirs.id, ch.id
        await s.commit()
    await _plan(theirs_id, other.id, other.organization_id, [(ch_id, -5, G)])

    mine = (await client.get("/api/v1/today", headers=tutor["headers"])).json()["behind_classes"]
    assert [(b["group_name"], b["missed"]) for b in mine] == [("Two behind", 2), ("Chem Y10", 1)]
    assert mine[0]["earliest_missed_date"] == _d(-4).isoformat()
    assert mine[0]["chapter_code"] == "C1"
    theirs_view = (await client.get("/api/v1/today", headers=headers)).json()["behind_classes"]
    assert [b["group_name"] for b in theirs_view] == ["Theirs"]


async def test_home_query_count_does_not_grow_with_behind_classes(
    client, tutor, group, subject, chapters, frozen
):
    org, uid = await _ctx(group, tutor)

    async def count() -> int:
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            await client.get("/api/v1/today", headers=tutor["headers"])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        return len(queries)

    await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    one = await count()
    for i in range(4):
        g = await _class(client, tutor, subject, f"Behind {i}")
        await _plan(g["id"], uid, org, [(chapters[0], -3, G), (chapters[1], -2, G)])
    # Extra queries per class would show here; the per-class group-summary reads
    # are bounded too, so the total is flat.
    assert await count() == one


# --- Re-plan --------------------------------------------------------------------


async def _breaks(plan_id, *spans):
    async with async_session() as s:
        for a, b in spans:
            s.add(PlanBreak(plan_id=plan_id, start_date=_d(a), end_date=_d(b), label="Half term"))
        await s.commit()


async def _slots(plan_id):
    async with async_session() as s:
        return (
            await s.scalars(
                select(PlanSlot).where(PlanSlot.plan_id == plan_id).order_by(PlanSlot.sequence)
            )
        ).all()


async def test_replan_makes_a_draft_with_the_non_generated_slots_and_one_job(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    c1, c2, c3 = chapters
    plan_id, ids = await _plan(
        group["id"],
        uid,
        org,
        [
            (c1, -8, G),  # generated and not recorded: dropped, it is the gap
            (c1, -7, PlanSlotProvenance.confirmed, True),  # taught: kept
            (
                c2,
                -6,
                PlanSlotProvenance.manually_modified,
            ),  # hand edit, never taught, past: dropped
            (c2, 6, PlanSlotProvenance.manually_modified),  # hand edit, future: kept
            (c3, 9, G),  # generated future: the job will redo it
        ],
    )
    await _breaks(plan_id, (20, 22))
    before = [
        (s.id, s.chapter_id, s.scheduled_date, s.provenance, s.lesson_id)
        for s in await _slots(plan_id)
    ]

    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    body = resp.json()
    draft = body["draft"]
    assert draft["drafting"] is True and draft["outcome"] is None
    assert [(s["scheduled_date"], s["provenance"]) for s in draft["slots"]] == [
        (_d(-7).isoformat(), "confirmed"),
        (_d(6).isoformat(), "manually_modified"),
    ]
    assert [(b["start_date"], b["end_date"]) for b in draft["breaks"]] == [
        (_d(20).isoformat(), _d(22).isoformat())
    ]
    async with async_session() as s:
        copied = (await s.scalars(select(PlanSlot).where(PlanSlot.plan_id == draft["id"]))).all()
        jobs = (await s.scalars(select(Job).where(Job.type == PLAN_DRAFT_JOB))).all()
    assert all(c.lesson_id is None for c in copied)  # lesson_id is unique: accept moves it
    assert [j.payload for j in jobs] == [{"plan_id": draft["id"]}]
    # The live plan is untouched, links included.
    after = [
        (s.id, s.chapter_id, s.scheduled_date, s.provenance, s.lesson_id)
        for s in await _slots(plan_id)
    ]
    assert after == before
    assert body["accepted"]["id"] == plan_id
    # A second click while it is queued is refused rather than queuing again.
    again = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert again.status_code == 409


async def test_replan_without_an_accepted_plan_is_409(client, tutor, group, chapters, frozen):
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)], status=TeachingPlanStatus.draft)
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 409
    async with async_session() as s:
        assert (await s.scalars(select(Job))).all() == []


async def test_replan_after_the_exam_date_is_409_and_changes_nothing(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    plan_id, _ = await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    async with async_session() as s:
        (await s.get(TeachingPlan, plan_id)).exam_date = _d(-1)
        await s.commit()
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 409
    async with async_session() as s:
        plans = (await s.scalars(select(TeachingPlan))).all()
    assert [p.status for p in plans] == [TeachingPlanStatus.accepted]


async def test_replan_reuses_an_idle_draft_and_resets_it_to_the_live_plan(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, PlanSlotProvenance.confirmed, True)])
    draft_id, _ = await _plan(
        group["id"], uid, org, [(chapters[1], 30, G)], status=TeachingPlanStatus.draft
    )
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    assert resp.json()["draft"]["id"] == draft_id
    assert [s["provenance"] for s in resp.json()["draft"]["slots"]] == ["confirmed"]


async def _pending_job(plan_id):
    from app.workers.jobs import enqueue

    async with async_session() as s:
        await enqueue(s, PLAN_DRAFT_JOB, {"plan_id": plan_id})
        await s.commit()


async def test_replan_is_409_while_a_draft_job_is_pending(client, tutor, group, chapters, frozen):
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    draft_id, _ = await _plan(
        group["id"], uid, org, [(chapters[1], 30, G)], status=TeachingPlanStatus.draft
    )
    await _pending_job(draft_id)
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 409
    async with async_session() as s:
        assert len((await s.scalars(select(Job))).all()) == 1  # nothing more queued
        kept = (await s.scalars(select(PlanSlot).where(PlanSlot.plan_id == draft_id))).all()
        assert len(kept) == 1  # the draft was not reset


async def test_a_job_queued_between_read_and_lock_is_seen_under_the_lock(
    client, tutor, group, chapters, frozen, monkeypatch
):
    """The pending-job check is made after the lock is taken, so a drafting job
    queued just before it still refuses the re-plan."""
    from app.services import plan_replan

    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    draft_id, _ = await _plan(
        group["id"], uid, org, [(chapters[1], 30, G)], status=TeachingPlanStatus.draft
    )
    real = plan_replan._lock_group_plans

    async def queue_then_lock(session, grp):
        await _pending_job(draft_id)
        return await real(session, grp)

    monkeypatch.setattr(plan_replan, "_lock_group_plans", queue_then_lock)
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 409


async def test_a_draft_promoted_before_the_lock_never_loses_the_live_plans_slots(
    client, tutor, group, chapters, frozen, monkeypatch
):
    """An accept lands just before the re-plan's lock. The re-plan then reads the
    promoted plan as the accepted one and drafts beside it; it must not delete it."""
    from app.services import plan_replan

    org, uid = await _ctx(group, tutor)
    old_id, _ = await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    draft_id, draft_slots = await _plan(
        group["id"],
        uid,
        org,
        [(chapters[1], 30, G), (chapters[2], 31, G)],
        status=TeachingPlanStatus.draft,
    )
    real = plan_replan._lock_group_plans

    async def accept_then_lock(session, grp):
        async with async_session() as other:
            await other.execute(delete(PlanSlot).where(PlanSlot.plan_id == old_id))
            await other.execute(delete(TeachingPlan).where(TeachingPlan.id == old_id))
            plan = await other.get(TeachingPlan, draft_id)
            plan.status = TeachingPlanStatus.accepted
            plan.accepted_at = datetime.now(timezone.utc)
            plan.accepted_by_id = uid
            await other.commit()
        return await real(session, grp)

    monkeypatch.setattr(plan_replan, "_lock_group_plans", accept_then_lock)
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    async with async_session() as s:
        live = (await s.scalars(select(PlanSlot).where(PlanSlot.plan_id == draft_id))).all()
        plans = {p.status: p.id for p in (await s.scalars(select(TeachingPlan))).all()}
    assert sorted(x.id for x in live) == sorted(draft_slots)  # the promoted plan is intact
    assert plans[TeachingPlanStatus.accepted] == draft_id
    assert plans[TeachingPlanStatus.draft] != draft_id


async def test_a_save_creating_the_draft_during_a_replan_is_not_a_500(
    client, tutor, group, chapters, frozen, monkeypatch
):
    from app.services import plan_replan

    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, PlanSlotProvenance.confirmed, True)])
    real = plan_replan._lock_group_plans

    async def lock_then_concurrent_save(session, grp):
        rows = await real(session, grp)
        # A save creates the draft after our read and before our insert.
        await _plan(group["id"], uid, org, [(chapters[1], 30, G)], status=TeachingPlanStatus.draft)
        return rows

    monkeypatch.setattr(plan_replan, "_lock_group_plans", lock_then_concurrent_save)
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    async with async_session() as s:
        drafts = (
            await s.scalars(
                select(TeachingPlan).where(TeachingPlan.status == TeachingPlanStatus.draft)
            )
        ).all()
        jobs = (await s.scalars(select(Job).where(Job.type == PLAN_DRAFT_JOB))).all()
    assert len(drafts) == 1 and [j.payload for j in jobs] == [{"plan_id": drafts[0].id}]
    assert [s["provenance"] for s in resp.json()["draft"]["slots"]] == ["confirmed"]


async def test_draft_and_replan_together_queue_one_job(
    client, tutor, group, chapters, frozen, monkeypatch
):
    from app.services import teaching_plan as service

    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    draft_id, _ = await _plan(
        group["id"], uid, org, [(chapters[1], 30, G)], status=TeachingPlanStatus.draft
    )
    real = service.lock_group_plans

    async def replan_lands_first(session, group_id):
        # Another request's re-plan queues its job before our draft click's lock.
        if not getattr(replan_lands_first, "done", False):
            replan_lands_first.done = True
            await _pending_job(draft_id)
        return await real(session, group_id)

    monkeypatch.setattr(service, "lock_group_plans", replan_lands_first)
    resp = await client.post(_url(group, "/draft"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    assert getattr(replan_lands_first, "done", False)  # the draft click took the shared lock
    async with async_session() as s:
        assert len((await s.scalars(select(Job).where(Job.type == PLAN_DRAFT_JOB))).all()) == 1


async def test_accept_skips_a_lesson_deleted_while_it_was_carrying_links(
    client, tutor, group, chapters, frozen, monkeypatch, fake_ai
):
    from app.models import Lesson
    from app.services import teaching_plan as service

    org, uid = await _ctx(group, tutor)
    await _plan(
        group["id"],
        uid,
        org,
        [(chapters[0], -9, PlanSlotProvenance.confirmed, True)],
    )
    await _replan_and_draft(client, tutor, group, chapters, monkeypatch, fake_ai)
    real = service._carry_lesson_links

    async def delete_lesson_then_carry(session, draft, linked):
        async with async_session() as other:
            for lesson in (await other.scalars(select(Lesson))).all():
                await other.delete(lesson)
            await other.commit()
        return await real(session, draft, linked)

    monkeypatch.setattr(service, "_carry_lesson_links", delete_lesson_then_carry)
    accepted = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert accepted.status_code == 200, accepted.text
    async with async_session() as s:
        alive = set((await s.scalars(select(Lesson.id))).all())
        links = [x.lesson_id for x in (await s.scalars(select(PlanSlot))).all() if x.lesson_id]
    assert links == [] and alive == set()  # no link to a lesson that no longer exists


async def test_a_moved_taught_copy_takes_the_link_instead_of_leaving_a_duplicate(
    client, tutor, group, chapters, frozen, monkeypatch, fake_ai
):
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -9, PlanSlotProvenance.confirmed, True)])
    await _replan_and_draft(client, tutor, group, chapters, monkeypatch, fake_ai)
    async with async_session() as s:
        copy = await s.scalar(
            select(PlanSlot).where(
                PlanSlot.provenance == PlanSlotProvenance.confirmed, PlanSlot.lesson_id.is_(None)
            )
        )
        copy.scheduled_date = _d(-8)  # the tutor moved the copy in the draft
        await s.commit()
    accepted = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert accepted.status_code == 200, accepted.text
    async with async_session() as s:
        taught = [
            x
            for x in (await s.scalars(select(PlanSlot))).all()
            if x.provenance is PlanSlotProvenance.confirmed
        ]
    assert [(x.scheduled_date, x.lesson_id is not None) for x in taught] == [(_d(-8), True)]
    assert accepted.json()["progress"]["missed"] == 0


# --- Accepting a re-plan carries the lesson links --------------------------------


def _weights(chapters):
    return PlanWeightingResult(
        chapters=[ChapterAdvice(chapter_id=c, weight=1.0, reason="r") for c in chapters]
    )


async def _replan_and_draft(client, tutor, group, chapters, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(_weights(chapters))
    )
    resp = await client.post(_url(group, "/replan"), headers=tutor["headers"])
    assert resp.status_code == 202, resp.text
    assert await process_one_job() is True


async def test_accept_after_replan_keeps_every_recorded_lesson_linked(
    client, tutor, group, chapters, frozen, monkeypatch, fake_ai
):
    org, uid = await _ctx(group, tutor)
    c1, c2, c3 = chapters
    plan_id, ids = await _plan(
        group["id"],
        uid,
        org,
        [
            (c1, -10, G),  # not recorded
            (c1, -9, PlanSlotProvenance.confirmed, True),
            (c2, -8, PlanSlotProvenance.completed, True),
            (c2, -7, G),  # not recorded
        ],
    )
    async with async_session() as s:
        lessons = {
            r.id: r.lesson_id for r in (await s.scalars(select(PlanSlot))).all() if r.lesson_id
        }
    await _replan_and_draft(client, tutor, group, chapters, monkeypatch, fake_ai)
    accepted = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert accepted.status_code == 200, accepted.text
    live = accepted.json()["accepted"]
    async with async_session() as s:
        slots = (await s.scalars(select(PlanSlot).where(PlanSlot.plan_id == live["id"]))).all()
    assert sorted(x.lesson_id for x in slots if x.lesson_id) == sorted(lessons.values())
    # Every linked slot is still taught, and nothing before today is left behind.
    assert all(
        x.provenance in (PlanSlotProvenance.confirmed, PlanSlotProvenance.completed)
        for x in slots
        if x.lesson_id
    )
    assert accepted.json()["progress"]["missed"] == 0
    # 6.5 never re-suggests a taught slot.
    nxt = (await client.get(_url(group, "/next-lesson"), headers=tutor["headers"])).json()
    taught_ids = {x.id for x in slots if x.lesson_id}
    assert nxt is not None and nxt["slot_id"] not in taught_ids


async def test_accept_keeps_the_link_on_a_new_slot_when_no_copy_matches(
    client, tutor, group, chapters, frozen, monkeypatch, fake_ai
):
    """A plain redraft (no re-plan) never copied the taught slot. Its link must
    survive on a new taught slot rather than be lost with the old plan."""
    org, uid = await _ctx(group, tutor)
    c1 = chapters[0]
    await _plan(group["id"], uid, org, [(c1, -9, PlanSlotProvenance.confirmed, True)])
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(_weights(chapters))
    )
    body = {"exam_date": EXAM.isoformat(), "lessons_per_week": 2, "lesson_minutes": 60}
    assert (
        await client.put(_url(group, "/inputs"), json=body, headers=tutor["headers"])
    ).status_code == 200
    assert (await client.post(_url(group, "/draft"), headers=tutor["headers"])).status_code == 202
    assert await process_one_job() is True
    accepted = await client.post(_url(group, "/accept"), headers=tutor["headers"])
    assert accepted.status_code == 200, accepted.text
    async with async_session() as s:
        linked = (await s.scalars(select(PlanSlot).where(PlanSlot.lesson_id.is_not(None)))).all()
    assert len(linked) == 1
    assert linked[0].plan_id == accepted.json()["accepted"]["id"]
    assert (linked[0].chapter_id, linked[0].scheduled_date) == (c1, _d(-9))
    assert linked[0].provenance is PlanSlotProvenance.confirmed


# --- Reflow outcome -------------------------------------------------------------


async def test_reflow_outcome_is_rendered_for_the_accepted_plan_and_the_draft(
    client, tutor, group, chapters, frozen
):
    org, uid = await _ctx(group, tutor)
    live_id, _ = await _plan(group["id"], uid, org, [(chapters[0], 4, G)])
    draft_id, _ = await _plan(
        group["id"], uid, org, [(chapters[0], 5, G)], status=TeachingPlanStatus.draft
    )
    async with async_session() as s:
        live = await s.get(TeachingPlan, live_id)
        live.draft_result = {
            "status": "drafted",
            "chapters": [],
            "reflow": {
                "at": "2026-10-01T09:00:00+00:00",
                "status": "failed",
                "failure": {"code": "not_enough_lessons", "message": "Too few lessons"},
                "last_success_at": "2026-09-20T09:00:00+00:00",
            },
        }
        draft = await s.get(TeachingPlan, draft_id)
        draft.draft_result = {
            "status": "drafted",
            "chapters": [],
            "reflow": {"at": "2026-10-02T09:00:00+00:00", "status": "skipped", "reason": "gone"},
        }
        await s.commit()
    body = (await client.get(_url(group), headers=tutor["headers"])).json()
    assert body["accepted"]["outcome"]["reflow"] == {
        "status": "failed",
        "at": "2026-10-01T09:00:00+00:00",
        "reason": None,
        "failure_message": "Too few lessons",
        "last_success_at": "2026-09-20T09:00:00+00:00",
    }
    assert body["draft"]["outcome"]["reflow"]["status"] == "skipped"
    assert body["draft"]["outcome"]["reflow"]["reason"] == "gone"


async def test_a_plan_with_no_reflow_has_none(client, tutor, group, chapters, frozen):
    org, uid = await _ctx(group, tutor)
    plan_id, _ = await _plan(group["id"], uid, org, [(chapters[0], 4, G)])
    async with async_session() as s:
        (await s.get(TeachingPlan, plan_id)).draft_result = {"status": "drafted", "chapters": []}
        await s.commit()
    body = (await client.get(_url(group), headers=tutor["headers"])).json()
    assert body["accepted"]["outcome"]["reflow"] is None


# --- Authorization (QA-12) ------------------------------------------------------


async def test_replan_refuses_a_student_a_stranger_and_no_token(
    client, tutor, group, chapters, student, frozen
):
    org, uid = await _ctx(group, tutor)
    await _plan(group["id"], uid, org, [(chapters[0], -3, G)])
    assert (
        await client.post(_url(group, "/replan"), headers=student["headers"])
    ).status_code == 403
    assert (await client.post(_url(group, "/replan"))).status_code == 401
    other = await _register(client, "stranger-replan@example.com")
    assert (await client.post(_url(group, "/replan"), headers=other)).status_code == 404
    # The stranger also learns nothing of the progress, and nothing was drafted.
    assert (await client.get(_url(group), headers=other)).status_code == 404
    async with async_session() as s:
        assert (await s.scalars(select(Job))).all() == []
        drafts = (
            await s.scalars(
                select(TeachingPlan).where(TeachingPlan.status == TeachingPlanStatus.draft)
            )
        ).all()
    assert drafts == []


async def test_progress_and_home_are_not_visible_to_a_student(
    client, tutor, group, chapters, student, frozen
):
    assert (await client.get(_url(group), headers=student["headers"])).status_code == 403
    assert (await client.get("/api/v1/today", headers=student["headers"])).status_code in (403, 404)
