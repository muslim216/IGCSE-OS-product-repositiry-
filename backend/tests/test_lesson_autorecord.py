"""Task 7.4 (AV-119): a class with an accepted plan counts as taught.

The sweep is driven with `process_one_job()` (QA-6); time-boundary cases call the
service with an explicit `now` so no test depends on the wall clock.
"""

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Job,
    JobStatus,
    LessonMode,
    LessonOrigin,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlanStatus,
)
from app.services import lesson_autorecord
from app.services.lesson_autorecord import (
    SWEEP_JOB,
    due_slot_ids,
    ensure_lesson_autorecord_scheduled,
    record_planned_lesson,
)
from app.workers.jobs import process_one_job
from tests.plan_world import (
    add_timetable,
    lesson_topic_ids,
    lessons,
    make_chapters,
    make_plan,
    set_org_timezone,
    slot_rows,
)

MON = date(2026, 10, 5)  # a Monday
CAIRO_NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def utc(d: date, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc)


async def _sweep() -> None:
    async with async_session() as s:
        await ensure_lesson_autorecord_scheduled(s)
        await s.commit()
    assert await process_one_job() is True


async def _pending_sweeps() -> list[Job]:
    async with async_session() as s:
        return list(
            (
                await s.scalars(
                    select(Job).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending)
                )
            ).all()
        )


def _past_week():
    today = date.today()
    return [today - timedelta(days=d) for d in (6, 4, 2)]


async def test_sweep_records_ended_lessons_with_a_share_of_the_chapter(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)  # five topics in C1
    d1, d2, d3 = _past_week()
    _, slot_ids = await make_plan(group, tutor, [(ch["c1"], d, time(16, 0)) for d in (d1, d2, d3)])
    await _sweep()

    got = await lessons()
    assert [ls.date for ls in got] == [d1, d2, d3]
    t = ch["t1"]
    assert [await lesson_topic_ids(ls.id) for ls in got] == [sorted(t[:2]), sorted(t[2:4]), [t[4]]]
    for lesson in got:
        assert lesson.origin is LessonOrigin.plan
        assert lesson.mode is LessonMode.in_person
        assert lesson.duration_min == 60
        assert lesson.start_time == time(16, 0)
    rows = await slot_rows(slot_ids and (await _plan_id(slot_ids[0])))
    assert [r.lesson_id for r in rows] == [ls.id for ls in got]
    assert {r.provenance for r in rows} == {PlanSlotProvenance.confirmed}


async def _plan_id(slot_id: int) -> int:
    async with async_session() as s:
        return (await s.get(PlanSlot, slot_id)).plan_id


async def test_rerunning_the_sweep_never_makes_a_second_lesson(client, tutor, group, subject):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))])
    await _sweep()
    first = [ls.id for ls in await lessons()]
    assert len(first) == 2

    # The successor is scheduled in the future, so force another run directly.
    async with async_session() as s:
        await lesson_autorecord.sweep_planned_lessons(s, {})
        await s.commit()
    assert [ls.id for ls in await lessons()] == first

    async with async_session() as s:
        ids = await due_slot_ids(s, datetime.now(timezone.utc))
    assert ids == []


async def test_recording_the_same_slot_twice_creates_one_lesson(client, tutor, group, subject):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    now = datetime.now(timezone.utc)
    async with async_session() as s:
        assert await record_planned_lesson(s, slot_id, now=now) is True
    async with async_session() as s:
        assert await record_planned_lesson(s, slot_id, now=now) is False
    assert len(await lessons()) == 1


async def test_a_lesson_the_tutor_recorded_first_is_never_duplicated(client, tutor, group, subject):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    _, (s1, s2) = await make_plan(
        group, tutor, [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))]
    )
    now = datetime.now(timezone.utc)
    async with async_session() as s:
        listed = await due_slot_ids(s, now)  # the sweep's stale list
    assert listed == [s1, s2]

    resp = await client.post(
        "/api/v1/lessons",
        json={
            "group_id": group["id"],
            "date": d1.isoformat(),
            "plan_slot_id": s1,
            "topic_ids": [ch["t1"][0]],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text

    async with async_session() as s:
        assert [await record_planned_lesson(s, i, now=now) for i in listed] == [False, True]
    got = await lessons()
    assert [(ls.date, ls.origin) for ls in got] == [
        (d1, LessonOrigin.tutor),
        (d2, LessonOrigin.plan),
    ]


async def test_the_tutor_cannot_record_over_an_auto_recorded_lesson(client, tutor, group, subject):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    await _sweep()
    resp = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": d1.isoformat(), "plan_slot_id": slot_id},
        headers=tutor["headers"],
    )
    assert resp.status_code == 409
    assert len(await lessons()) == 1


async def test_boundary_follows_the_organizations_zone_not_utc(client, tutor, group, subject):
    await set_org_timezone("Africa/Cairo")  # UTC+3 on 5 Oct 2026
    ch = await make_chapters(subject)
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], MON, time(17, 0))])
    # 17:00 + 60 min local = 18:00 Cairo = 15:00 UTC.
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 14, 59, 59)) == []
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 15, 0, 1)) == [slot_id]
    async with async_session() as s:
        assert await record_planned_lesson(s, slot_id, now=utc(MON, 14, 59)) is False
    assert await lessons() == []


async def test_no_start_time_and_no_timetable_ends_with_the_local_day(
    client, tutor, group, subject
):
    await set_org_timezone("Africa/Cairo")
    ch = await make_chapters(subject)
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], MON, None)])
    # Local day ends at 00:00 on the 6th Cairo = 21:00 UTC on the 5th.
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 20, 59)) == []
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 21, 1)) == [slot_id]


async def test_a_null_start_time_falls_back_to_the_timetable_not_midnight(
    client, tutor, group, subject
):
    await set_org_timezone("Africa/Cairo")
    await add_timetable(group, 0, time(9, 0))  # Mondays 09:00
    ch = await make_chapters(subject)
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], MON, None)])
    # 09:00 + 60 = 10:00 Cairo = 07:00 UTC: due well before the end of the day.
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 6, 59)) == []
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 7, 1)) == [slot_id]
    async with async_session() as s:
        await record_planned_lesson(s, slot_id, now=utc(MON, 8))
    (lesson,) = await lessons()
    assert lesson.start_time == time(9, 0)


async def test_a_class_with_only_a_draft_plan_records_nothing(client, tutor, group, subject):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    await make_plan(
        group,
        tutor,
        [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))],
        status=TeachingPlanStatus.draft,
    )
    await _sweep()
    assert await lessons() == []


async def test_a_cancelled_slot_records_nothing(client, tutor, group, subject):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    _, (s1, s2) = await make_plan(
        group, tutor, [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))]
    )
    async with async_session() as s:
        (await s.get(PlanSlot, s1)).cancelled_at = datetime.now(timezone.utc)
        await s.commit()
    await _sweep()
    got = await lessons()
    assert [ls.date for ls in got] == [d2]
    # The cancelled slot takes no share: the survivor teaches the whole chapter.
    assert await lesson_topic_ids(got[0].id) == sorted(ch["t1"])
    rows = {r.id: r for r in await slot_rows(await _plan_id(s1))}
    assert rows[s1].lesson_id is None


async def test_a_lesson_that_ended_before_the_plan_was_accepted_is_not_recorded(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    accepted = utc(d1, 20)  # after the first lesson ended, before the second
    _, (s1, s2) = await make_plan(
        group,
        tutor,
        [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))],
        accepted_at=accepted,
    )
    async with async_session() as s:
        assert await due_slot_ids(s, datetime.now(timezone.utc)) == [s2]


async def test_a_lesson_still_in_progress_or_in_the_future_is_not_recorded(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    _, ids = await make_plan(
        group,
        tutor,
        [(ch["c1"], MON, time(16, 0)), (ch["c1"], MON + timedelta(days=3), time(16, 0))],
    )
    async with async_session() as s:
        assert await due_slot_ids(s, utc(MON, 16, 30)) == []


async def test_a_slot_the_tutor_marked_completed_is_left_alone(client, tutor, group, subject):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    async with async_session() as s:
        (await s.get(PlanSlot, slot_id)).provenance = PlanSlotProvenance.completed
        await s.commit()
    await _sweep()
    assert await lessons() == []


async def test_deleting_an_auto_recorded_lesson_is_not_undone_by_the_next_sweep(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    plan_id, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    await _sweep()
    (lesson,) = await lessons()
    resp = await client.delete(f"/api/v1/lessons/{lesson.id}", headers=tutor["headers"])
    assert resp.status_code == 204

    async with async_session() as s:
        await lesson_autorecord.sweep_planned_lessons(s, {})
        await s.commit()
    assert await lessons() == []
    (row,) = await slot_rows(plan_id)
    assert row.cancelled_at is not None and row.lesson_id is None


async def test_a_tutor_recorded_lesson_deleted_frees_its_slot_as_before(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    plan_id, (slot_id,) = await make_plan(
        group, tutor, [(ch["c1"], date.today() + timedelta(days=3), time(16, 0))]
    )
    resp = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": date.today().isoformat(), "plan_slot_id": slot_id},
        headers=tutor["headers"],
    )
    lesson_id = resp.json()["id"]
    assert (
        await client.delete(f"/api/v1/lessons/{lesson_id}", headers=tutor["headers"])
    ).status_code == 204
    (row,) = await slot_rows(plan_id)
    assert row.cancelled_at is None and row.lesson_id is None


# --- Reliability: the schedule survives ----------------------------------------


async def test_the_sweep_rearms_itself_one_interval_out(client, tutor, group, subject):
    await _sweep()
    (nxt,) = await _pending_sweeps()
    run_after = nxt.run_after
    if run_after.tzinfo is None:
        run_after = run_after.replace(tzinfo=timezone.utc)
    delta = run_after - datetime.now(timezone.utc)
    assert timedelta(minutes=14) < delta <= timedelta(minutes=15)


async def test_the_successor_is_committed_even_when_the_work_fails(
    client, tutor, group, subject, monkeypatch
):
    async def boom(session, now):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(lesson_autorecord, "due_slot_ids", boom)
    async with async_session() as s:
        await ensure_lesson_autorecord_scheduled(s)
        await s.commit()
    await process_one_job()  # the job fails; its own transaction rolled back
    assert len(await _pending_sweeps()) >= 1  # the successor survived


async def test_ensure_scheduled_is_idempotent(client, tutor, group, subject):
    for _ in range(3):
        async with async_session() as s:
            await ensure_lesson_autorecord_scheduled(s)
            await s.commit()
    assert len(await _pending_sweeps()) == 1


async def test_kill_switch_records_nothing_but_keeps_the_schedule(
    client, tutor, group, subject, monkeypatch
):
    monkeypatch.setattr(
        lesson_autorecord,
        "get_settings",
        lambda: SimpleNamespace(
            lesson_autorecord_enabled=False, lesson_autorecord_interval_minutes=15
        ),
    )
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    await _sweep()
    assert await lessons() == []
    assert len(await _pending_sweeps()) == 1


@pytest.mark.parametrize("bad_zone", ["Not/AZone", ""])
async def test_an_unloadable_zone_degrades_to_utc_and_does_not_break_the_sweep(
    client, tutor, group, subject, bad_zone
):
    await set_org_timezone(bad_zone)
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    await _sweep()
    assert len(await lessons()) == 1


# --- Review follow-ups ---------------------------------------------------------------


async def test_deleting_a_tutor_recorded_lesson_on_a_past_slot_is_not_re_recorded(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    plan_id, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    made = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": d1.isoformat(), "plan_slot_id": slot_id},
        headers=tutor["headers"],
    )
    assert made.status_code == 201, made.text
    assert made.json()["origin"] == "tutor"
    resp = await client.delete(f"/api/v1/lessons/{made.json()['id']}", headers=tutor["headers"])
    assert resp.status_code == 204

    async with async_session() as s:
        await lesson_autorecord.sweep_planned_lessons(s, {})
        await s.commit()
    assert await lessons() == []
    (row,) = await slot_rows(plan_id)
    assert row.cancelled_at is not None and row.lesson_id is None
    # "Behind" still shows the gap.
    plan = (await client.get(f"/api/v1/groups/{group['id']}/plan", headers=tutor["headers"])).json()
    assert plan["progress"]["missed"] == 1


async def test_a_slot_moved_since_the_listing_is_not_recorded(client, tutor, group, subject):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    plan_id, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    now = datetime.now(timezone.utc)
    async with async_session() as s:
        assert await due_slot_ids(s, now) == [slot_id]
    moved = date.today() + timedelta(days=5)
    edit = await client.patch(
        f"/api/v1/groups/{group['id']}/plan/slots/{slot_id}",
        json={"scheduled_date": moved.isoformat()},
        headers=tutor["headers"],
    )
    assert edit.status_code == 200, edit.text
    async with async_session() as s:
        assert await record_planned_lesson(s, slot_id, now=now) is False
        assert not s.in_transaction()  # locks released on the skip path
    assert await lessons() == []


@pytest.mark.parametrize("changed", ["date", "chapter", "start_time"])
async def test_the_claim_refuses_a_slot_changed_since_the_decision(
    client, tutor, group, subject, changed
):
    """The guard holds the values the auto-record decided on (and chose topics
    from); the claim UPDATE requires the slot to still carry them."""
    from app.models import Group
    from app.services import plan_lessons
    from app.services.teaching_plan import PlanStateError

    ch = await make_chapters(subject)
    (d1, d2, _) = _past_week()
    _, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    guard = {
        "date": plan_lessons.ClaimGuard(d2, ch["c1"], time(16, 0)),
        "chapter": plan_lessons.ClaimGuard(d1, ch["c2"], time(16, 0)),
        "start_time": plan_lessons.ClaimGuard(d1, ch["c1"], time(9, 0)),
    }[changed]
    async with async_session() as s:
        g = await s.get(Group, group["id"])
        with pytest.raises(PlanStateError):
            await plan_lessons.create_lesson(
                s,
                group=g,
                lesson_date=d1,
                duration_min=60,
                notes=None,
                schedule_slot_id=None,
                topic_ids=[],
                plan_slot_id=slot_id,
                claim_guard=guard,
            )
    assert await lessons() == []
    # And the matching guard claims it.
    async with async_session() as s:
        g = await s.get(Group, group["id"])
        await plan_lessons.create_lesson(
            s,
            group=g,
            lesson_date=d1,
            duration_min=60,
            notes=None,
            schedule_slot_id=None,
            topic_ids=[],
            plan_slot_id=slot_id,
            claim_guard=plan_lessons.ClaimGuard(d1, ch["c1"], time(16, 0)),
        )
    assert len(await lessons()) == 1


async def test_pre_acceptance_gaps_do_not_crowd_the_batch(
    client, tutor, group, subject, monkeypatch
):
    monkeypatch.setattr(lesson_autorecord, "MAX_PER_SWEEP", 2)  # SQL limit is 8
    ch = await make_chapters(subject)
    today = date.today()
    old = [(ch["c1"], today - timedelta(days=60 + i), time(9, 0)) for i in range(10)]
    recent = (ch["c1"], today - timedelta(days=1), time(9, 0))
    _, ids = await make_plan(
        group, tutor, [*old, recent], accepted_at=utc(today - timedelta(days=20), 12)
    )
    async with async_session() as s:
        assert await due_slot_ids(s, datetime.now(timezone.utc)) == [ids[-1]]


async def test_a_permanently_failing_slot_is_skipped_not_retried_every_sweep(
    client, tutor, group, subject, monkeypatch
):
    ch = await make_chapters(subject)
    d1, d2, _ = _past_week()
    _, (bad, good) = await make_plan(
        group, tutor, [(ch["c1"], d1, time(16, 0)), (ch["c1"], d2, time(16, 0))]
    )
    calls: list[int] = []
    real = lesson_autorecord.record_planned_lesson

    async def flaky(session, slot_id, *, now):
        calls.append(slot_id)
        if slot_id == bad:
            raise RuntimeError("boom")
        return await real(session, slot_id, now=now)

    monkeypatch.setattr(lesson_autorecord, "record_planned_lesson", flaky)
    monkeypatch.setattr(lesson_autorecord, "_failed_at", {})
    for _ in range(3):
        async with async_session() as s:
            await lesson_autorecord.sweep_planned_lessons(s, {})
            await s.commit()
    assert calls.count(bad) == 1  # backed off after the first failure
    assert [ls.date for ls in await lessons()] == [d2]


async def test_a_missing_or_unloadable_zone_warns_and_keeps_the_utc_fallback(
    client, tutor, group, subject, caplog
):
    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    for zone, needle in ((None, "no timezone"), ("Not/AZone", "cannot be loaded")):
        await set_org_timezone(zone)
        caplog.clear()
        async with async_session() as s:
            ids = await due_slot_ids(s, datetime.now(timezone.utc))
        assert len(ids) == 1  # UTC fallback still decides
        assert any(needle in r.message and r.levelname == "WARNING" for r in caplog.records)


async def test_release_cancels_the_slot_that_holds_the_link_after_an_accept_moved_it(
    client, tutor, group, subject, monkeypatch
):
    """The plan id read before the lock can be the old plan's. The slot is
    re-read under the lock and the cancel lands on the plan that holds it now."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services import plan_lessons

    ch = await make_chapters(subject)
    (d1, *_) = _past_week()
    plan_id, (slot_id,) = await make_plan(group, tutor, [(ch["c1"], d1, time(16, 0))])
    await _sweep()
    (lesson,) = await lessons()

    real = AsyncSession.scalar
    state = {"first": True}

    async def stale_first(self, statement, *a, **k):
        if state["first"]:
            state["first"] = False
            return 999_999  # a plan id that no longer exists: the old plan's
        return await real(self, statement, *a, **k)

    async with async_session() as s:
        monkeypatch.setattr(AsyncSession, "scalar", stale_first)
        await plan_lessons.release_slot_for_lesson(s, lesson.id)
        monkeypatch.setattr(AsyncSession, "scalar", real)
        await s.commit()
    (row,) = await slot_rows(plan_id)
    assert row.lesson_id is None and row.cancelled_at is not None


async def test_paging_reaches_due_slots_behind_backed_off_ones(
    client, tutor, group, subject, monkeypatch
):
    monkeypatch.setattr(lesson_autorecord, "PAGE_SIZE", 2)
    ch = await make_chapters(subject)
    today = date.today()
    _, ids = await make_plan(
        group, tutor, [(ch["c1"], today - timedelta(days=9 - i), time(9, 0)) for i in range(4)]
    )
    monkeypatch.setattr(
        lesson_autorecord,
        "_failed_at",
        dict.fromkeys(ids[:3], lesson_autorecord._sweep_counter),
    )
    async with async_session() as s:
        assert await due_slot_ids(s, datetime.now(timezone.utc)) == [ids[3]]


def test_the_zone_warning_is_once_per_class_until_the_sweep_resets_it(caplog):
    from app.services.plan_start_times import reset_zone_warnings, resolve_zone

    reset_zone_warnings()
    caplog.clear()
    for _ in range(5):
        resolve_zone(None, None, 41)
    assert len([r for r in caplog.records if "no timezone" in r.message]) == 1
    reset_zone_warnings()
    resolve_zone(None, None, 41)
    assert len([r for r in caplog.records if "no timezone" in r.message]) == 2
