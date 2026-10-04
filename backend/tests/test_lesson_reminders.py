"""Task 7.4 (AV-119, AV-120): the in-app reminder, per-lesson start times, the
topic share on the suggestion, and what "behind" means now."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import PlanSlot, PlanSlotProvenance, TeachingPlanStatus, User
from app.services.lesson_reminders import due_reminders
from app.services.plan_progress import SlotFact, compute_progress
from tests.plan_world import (
    add_timetable,
    make_chapters,
    make_plan,
    set_org_timezone,
    slot_rows,
)

MON = date(2026, 10, 5)


def utc(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)


async def _reminders(now: datetime):
    async with async_session() as s:
        user = (await s.scalars(select(User).order_by(User.id))).first()
        return await due_reminders(s, user, now)


# --- The reminder ----------------------------------------------------------------


async def test_endpoint_returns_a_reminder_with_what_the_plan_covers(client, tutor, group, subject):
    ch = await make_chapters(subject)
    start = datetime.now(timezone.utc) + timedelta(minutes=10)
    day = start.date()
    _, ids = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], day, start.time().replace(second=0, microsecond=0)),
            (ch["c1"], day + timedelta(days=3), time(9, 0)),
        ],
    )
    resp = await client.get("/api/v1/today/reminders", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    (r,) = resp.json()
    assert r["slot_id"] == ids[0]
    assert r["group_name"] == group["name"]
    assert r["chapter"]["code"] == "C1"
    # Two C1 lessons share five topics: the first covers the first three.
    assert [t["id"] for t in r["topics"]] == ch["t1"][:3]


async def test_the_window_opens_fifteen_minutes_before_and_closes_at_the_end(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, time(16, 0))])
    assert await _reminders(utc(MON, 15, 44)) == []
    assert len(await _reminders(utc(MON, 15, 45))) == 1
    assert len(await _reminders(utc(MON, 16, 30))) == 1  # under way
    assert await _reminders(utc(MON, 17, 0)) == []  # ended: the auto-record owns it


async def test_the_window_follows_the_organizations_zone(client, tutor, group, subject):
    await set_org_timezone("Africa/Cairo")  # UTC+3: 17:00 local is 14:00 UTC
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, time(17, 0))])
    assert await _reminders(utc(MON, 13, 44)) == []
    assert len(await _reminders(utc(MON, 13, 46))) == 1
    assert await _reminders(utc(MON, 17, 0)) == []  # still "17:00 UTC" would have fired


async def test_no_start_time_and_no_timetable_means_no_reminder(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, None)])
    for hour in (0, 6, 12, 18, 23):
        assert await _reminders(utc(MON, hour)) == []


async def test_a_null_start_time_uses_the_timetable(client, tutor, group, subject):
    await add_timetable(group, 0, time(9, 0))
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, None)])
    assert len(await _reminders(utc(MON, 8, 50))) == 1


async def test_a_recorded_cancelled_or_draft_lesson_has_no_reminder(client, tutor, group, subject):
    ch = await make_chapters(subject)
    _, ids = await make_plan(
        group,
        tutor,
        [(ch["c1"], MON, time(16, 0)), (ch["c1"], MON, time(16, 0)), (ch["c1"], MON, time(16, 0))],
    )
    async with async_session() as s:
        (await s.get(PlanSlot, ids[0])).provenance = PlanSlotProvenance.completed
        (await s.get(PlanSlot, ids[1])).cancelled_at = utc(MON, 1)
        await s.commit()
    assert [r.slot_id for r in await _reminders(utc(MON, 15, 50))] == [ids[2]]


async def test_a_draft_plan_has_no_reminder(client, tutor, group, subject):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, time(16, 0))], status=TeachingPlanStatus.draft)
    assert await _reminders(utc(MON, 15, 50)) == []


async def test_another_tutor_never_sees_the_reminder(client, tutor, group, subject):
    ch = await make_chapters(subject)
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    await make_plan(group, tutor, [(ch["c1"], start.date(), start.time().replace(microsecond=0))])
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-rem@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.get("/api/v1/today/reminders", headers=headers)
    assert resp.status_code == 200 and resp.json() == []


async def test_a_student_and_an_anonymous_caller_are_refused(client, tutor, group, student):
    assert (
        await client.get("/api/v1/today/reminders", headers=student["headers"])
    ).status_code == 403
    assert (await client.get("/api/v1/today/reminders")).status_code == 401


# --- Per-lesson start time -----------------------------------------------------------


def _slot_url(group, slot_id):
    return f"/api/v1/groups/{group['id']}/plan/slots/{slot_id}"


async def test_the_plan_reports_the_timetable_time_for_a_slot_with_none_stored(
    client, tutor, group, subject
):
    await add_timetable(group, 0, time(9, 30))
    ch = await make_chapters(subject)
    await make_plan(
        group, tutor, [(ch["c1"], MON, None), (ch["c1"], MON + timedelta(days=1), None)]
    )
    plan = (await client.get(f"/api/v1/groups/{group['id']}/plan", headers=tutor["headers"])).json()
    got = [s["start_time"] for s in plan["accepted"]["slots"]]
    assert got == ["09:30:00", None]  # Tuesday has no timetable: unknown, never midnight


async def test_a_start_time_is_editable_per_lesson(client, tutor, group, subject):
    ch = await make_chapters(subject)
    plan_id, ids = await make_plan(group, tutor, [(ch["c1"], MON, time(16, 0))])
    resp = await client.patch(
        _slot_url(group, ids[0]), json={"start_time": "18:15"}, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["start_time"] == "18:15:00"
    (row,) = await slot_rows(plan_id)
    assert row.start_time == time(18, 15)
    assert row.provenance is PlanSlotProvenance.manually_modified


async def test_moving_a_lesson_to_another_weekday_takes_that_days_timetable_time(
    client, tutor, group, subject
):
    await add_timetable(group, 0, time(17, 0))
    await add_timetable(group, 3, time(15, 0))
    ch = await make_chapters(subject)
    plan_id, ids = await make_plan(group, tutor, [(ch["c1"], MON, time(18, 0))])
    thu = MON + timedelta(days=3)
    resp = await client.patch(
        _slot_url(group, ids[0]), json={"scheduled_date": thu.isoformat()}, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["start_time"] == "15:00:00"


async def test_an_empty_patch_is_still_rejected(client, tutor, group, subject):
    ch = await make_chapters(subject)
    _, ids = await make_plan(group, tutor, [(ch["c1"], MON, time(16, 0))])
    resp = await client.patch(_slot_url(group, ids[0]), json={}, headers=tutor["headers"])
    assert resp.status_code == 422


# --- Pre-fill: the suggestion is the same share the auto-record writes ----------------


async def test_the_suggestion_is_the_slots_share_of_its_chapter(client, tutor, group, subject):
    ch = await make_chapters(subject)
    d = [MON + timedelta(days=i) for i in (0, 3, 7)]
    _, ids = await make_plan(group, tutor, [(ch["c1"], x, None) for x in d])
    url = f"/api/v1/groups/{group['id']}/plan/next-lesson"
    first = (await client.get(url, headers=tutor["headers"])).json()
    assert first["slot_id"] == ids[0]
    assert [t["id"] for t in first["topics"]] == ch["t1"][:2]
    # Recording it moves the suggestion to the next share, not the whole chapter.
    made = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": d[0].isoformat(), "plan_slot_id": ids[0]},
        headers=tutor["headers"],
    )
    assert made.status_code == 201
    second = (await client.get(url, headers=tutor["headers"])).json()
    assert [t["id"] for t in second["topics"]] == ch["t1"][2:4]


async def test_the_suggestion_can_be_asked_for_one_slot_and_only_one_of_this_plan(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    d = [MON + timedelta(days=i) for i in (0, 3, 7)]
    _, ids = await make_plan(group, tutor, [(ch["c1"], x, None) for x in d])
    url = f"/api/v1/groups/{group['id']}/plan/next-lesson"
    got = (await client.get(f"{url}?slot_id={ids[1]}", headers=tutor["headers"])).json()
    assert got["slot_id"] == ids[1]
    assert [t["id"] for t in got["topics"]] == ch["t1"][2:4]
    assert (await client.get(f"{url}?slot_id=999999", headers=tutor["headers"])).json() is None


# --- "Behind" ----------------------------------------------------------------------


def _fact(day, *, has_lesson=False, ends_at=None, cancelled=False, unrescheduled=False, sid=1):
    return SlotFact(
        day,
        sid,
        sid,
        1,
        "C1",
        "Atoms",
        has_lesson,
        PlanSlotProvenance.generated,
        ends_at=ends_at,
        cancelled=cancelled,
        unrescheduled=unrescheduled,
    )


def test_a_rescheduled_cancellation_is_not_behind_but_an_unrescheduled_one_is():
    today = date(2026, 10, 10)
    p = compute_progress(
        [
            _fact(date(2026, 10, 12), cancelled=True, unrescheduled=False, sid=1),
            _fact(date(2026, 10, 14), cancelled=True, unrescheduled=True, sid=2),
        ],
        today,
    )
    assert p.missed == 1 and p.earliest_missed_date == date(2026, 10, 14)


def test_a_lesson_inside_the_sweeps_lag_is_not_behind_but_an_older_one_is():
    now = utc(date(2026, 10, 10), 0, 5)
    grace = timedelta(minutes=15)
    today = date(2026, 10, 10)
    just_ended = _fact(date(2026, 10, 9), ends_at=utc(date(2026, 10, 10), 0, 0), sid=1)
    old = _fact(date(2026, 10, 8), ends_at=utc(date(2026, 10, 8), 18), sid=2)
    assert compute_progress([just_ended], today, now, grace).missed == 0
    assert compute_progress([old], today, now, grace).missed == 1
    both = compute_progress([just_ended, old], today, now, grace)
    assert both.missed == 1 and both.planned_to_date == 1
    # Without a clock the old behaviour holds: every unrecorded past lesson counts.
    assert compute_progress([just_ended, old], today).missed == 2


def test_a_recorded_past_lesson_is_taught_and_a_future_one_is_not_considered():
    today = date(2026, 10, 10)
    p = compute_progress(
        [_fact(date(2026, 10, 8), has_lesson=True, sid=1), _fact(date(2026, 10, 12), sid=2)], today
    )
    assert (p.planned_to_date, p.taught_to_date, p.missed) == (1, 1, 0)


async def test_editing_the_date_to_the_same_weekday_keeps_a_custom_time(
    client, tutor, group, subject
):
    await add_timetable(group, 0, time(17, 0))
    ch = await make_chapters(subject)
    _, ids = await make_plan(group, tutor, [(ch["c1"], MON, time(18, 0))])
    resp = await client.patch(
        _slot_url(group, ids[0]),
        json={"scheduled_date": (MON + timedelta(days=7)).isoformat()},
        headers=tutor["headers"],
    )
    assert resp.json()["start_time"] == "18:00:00"


async def test_an_offset_aware_start_time_is_422(client, tutor, group, subject):
    ch = await make_chapters(subject)
    _, ids = await make_plan(group, tutor, [(ch["c1"], MON, time(18, 0))])
    resp = await client.patch(
        _slot_url(group, ids[0]), json={"start_time": "17:00:00+02:00"}, headers=tutor["headers"]
    )
    assert resp.status_code == 422


async def test_progress_uses_each_classs_tutor_zone_not_the_viewers(
    client, tutor, group, subject, monkeypatch
):
    from app.models import Organization, UserRole
    from app.services import plan_progress

    await set_org_timezone("Africa/Cairo")
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], MON, time(9, 0))])
    async with async_session() as s:
        org = await s.scalar(select(Organization))
        admin = User(
            email="admin-zone@example.com",
            password_hash="x",
            role=UserRole.admin,
            name="Admin",
            organization_id=org.id,
            time_zone="Pacific/Kiritimati",
        )
        s.add(admin)
        await s.commit()
        seen: list[str | None] = []
        real = plan_progress.slot_end_utc

        def spy(day, start, minutes, zone):
            seen.append(zone)
            return real(day, start, minutes, zone)

        monkeypatch.setattr(plan_progress, "slot_end_utc", spy)
        await plan_progress.class_progress(s, admin, date(2026, 10, 20), own_classes_only=False)
    assert seen == ["Africa/Cairo"]
