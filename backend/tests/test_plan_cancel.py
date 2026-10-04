"""Task 7.4 (AV-120): cancelling a planned lesson shifts the plan automatically."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlanStatus,
)
from app.services.plan_reflow import reflow_plan_slots
from tests.plan_world import (
    add_timetable,
    lessons,
    make_chapters,
    make_plan,
    slot_rows,
)

MON, THU = 0, 3


def next_weekday(weekday: int, after: date) -> date:
    d = after + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def meeting_dates(n: int) -> list[date]:
    """Mon, Thu, Mon, Thu ... starting after next week, so every date is in the future."""
    first = next_weekday(MON, date.today() + timedelta(days=7))
    out = [first]
    while len(out) < n:
        last = out[-1]
        out.append(next_weekday(THU if last.weekday() == MON else MON, last))
    return out


def _cancel(group, slot_id):
    return f"/api/v1/groups/{group['id']}/plan/slots/{slot_id}/cancel"


async def _world(group, tutor, subject, *, n=5, exam=None, timetable=True):
    if timetable:
        await add_timetable(group, MON, time(17, 0))
        await add_timetable(group, THU, time(15, 0))
    ch = await make_chapters(subject)
    dates = meeting_dates(n)
    pattern = [ch["c1"], ch["c1"], ch["c2"], ch["c1"], ch["c2"]][:n]
    kwargs = {"exam": exam} if exam else {}
    plan_id, ids = await make_plan(
        group, tutor, [(c, d, None) for c, d in zip(pattern, dates, strict=True)], **kwargs
    )
    return ch, dates, plan_id, ids


async def test_cancelling_shifts_the_tail_and_inserts_a_replacement(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    resp = await client.post(_cancel(group, ids[1]), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shifted"] is True and body["message"] is None
    assert body["moved"] == 4  # the three later lessons + the replacement

    rows = await slot_rows(plan_id)
    live = [r for r in rows if r.cancelled_at is None]
    # Same chapters in the same order, the cancelled one's repeated right after it.
    assert [r.chapter_id for r in live] == [
        ch["c1"],  # untouched
        ch["c1"],  # replacement
        ch["c2"],
        ch["c1"],
        ch["c2"],
    ]
    more = meeting_dates(6)
    assert [r.scheduled_date for r in live] == [more[0], *more[2:6]]
    # The tutor's cancelled lesson is kept, dated where it was, with who cancelled it.
    cancelled = next(r for r in rows if r.id == ids[1])
    assert cancelled.cancelled_at is not None
    assert cancelled.cancelled_by_id == tutor["user"]["id"]
    assert cancelled.scheduled_date == dates[1]
    # Each moved lesson takes the timetable time for its new weekday.
    for r in live[1:]:
        assert r.start_time == (time(17, 0) if r.scheduled_date.weekday() == MON else time(15, 0))
    # `sequence` is one run over every row.
    assert [r.sequence for r in rows] == list(range(1, len(rows) + 1))
    assert await lessons() == []  # cancelling never records a lesson


async def test_the_replacement_is_a_generated_slot_of_the_cancelled_chapter(
    client, tutor, group, subject
):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    await client.post(_cancel(group, ids[2]), headers=tutor["headers"])
    rows = await slot_rows(plan_id)
    new = [r for r in rows if r.id not in ids]
    assert len(new) == 1
    assert new[0].chapter_id == ch["c2"] and new[0].provenance is PlanSlotProvenance.generated
    assert new[0].scheduled_date == meeting_dates(4)[3]  # the date the next lesson had


async def test_a_tutor_edited_slot_shifts_date_but_keeps_its_chapter_and_provenance(
    client, tutor, group, subject
):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    async with async_session() as s:
        edited = await s.get(PlanSlot, ids[3])
        edited.provenance = PlanSlotProvenance.manually_modified
        await s.commit()
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 200
    rows = {r.id: r for r in await slot_rows(plan_id)}
    assert rows[ids[3]].chapter_id == ch["c1"]
    assert rows[ids[3]].provenance is PlanSlotProvenance.manually_modified
    assert rows[ids[3]].scheduled_date == meeting_dates(6)[4]  # one place later


async def test_a_taught_lesson_stays_put_and_its_date_is_not_landed_on(
    client, tutor, group, subject
):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    async with async_session() as s:
        taught = await s.get(PlanSlot, ids[3])
        taught.provenance = PlanSlotProvenance.completed
        await s.commit()
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 200
    rows = await slot_rows(plan_id)
    taught_row = next(r for r in rows if r.id == ids[3])
    assert taught_row.scheduled_date == dates[3]
    moved_dates = [r.scheduled_date for r in rows if r.cancelled_at is None and r.id != ids[3]]
    assert dates[3] not in moved_dates
    assert len(set(moved_dates)) == len(moved_dates)


async def test_breaks_are_not_shifted_into(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject, n=3)
    async with async_session() as s:
        s.add(
            PlanBreak(
                plan_id=plan_id,
                start_date=dates[1],
                end_date=dates[1] + timedelta(days=10),
                label="Half term",
            )
        )
        await s.commit()
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 200
    live = [r for r in await slot_rows(plan_id) if r.cancelled_at is None]
    assert all(
        not (dates[1] <= r.scheduled_date <= dates[1] + timedelta(days=10)) for r in live[1:]
    )


async def test_no_room_before_the_exam_keeps_the_lesson_cancelled_and_moves_nothing(
    client, tutor, group, subject
):
    # Exam the day after the last planned lesson: every later date is gone.
    dates = meeting_dates(5)
    ch, dates, plan_id, ids = await _world(
        group, tutor, subject, exam=dates[-1] + timedelta(days=1)
    )
    before = [(r.id, r.scheduled_date, r.chapter_id) for r in await slot_rows(plan_id)]
    resp = await client.post(_cancel(group, ids[1]), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shifted"] is False and body["moved"] == 0
    assert body["message"] == "No room before the exam — re-plan to catch up"

    rows = await slot_rows(plan_id)
    assert [(r.id, r.scheduled_date, r.chapter_id) for r in rows] == before  # nothing moved
    assert next(r for r in rows if r.id == ids[1]).cancelled_at is not None

    # The existing "behind" path reports it, whatever the lesson's date.
    progress = body["plan"]["progress"]
    assert progress["missed"] == 1
    assert progress["earliest_missed_chapter"]["code"] == "C1"


async def test_a_rescheduled_cancellation_is_not_behind(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    resp = await client.post(_cancel(group, ids[1]), headers=tutor["headers"])
    assert resp.json()["plan"]["progress"] is not None
    assert resp.json()["plan"]["progress"]["missed"] == 0


async def test_cancelling_a_lesson_that_has_a_lesson_is_409(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    made = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": date.today().isoformat(), "plan_slot_id": ids[0]},
        headers=tutor["headers"],
    )
    assert made.status_code == 201, made.text
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 409
    rows = await slot_rows(plan_id)
    assert all(r.cancelled_at is None for r in rows)


async def test_cancelling_twice_is_409_and_shifts_only_once(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    assert (await client.post(_cancel(group, ids[1]), headers=tutor["headers"])).status_code == 200
    after_first = [(r.id, r.scheduled_date) for r in await slot_rows(plan_id)]
    assert (await client.post(_cancel(group, ids[1]), headers=tutor["headers"])).status_code == 409
    assert [(r.id, r.scheduled_date) for r in await slot_rows(plan_id)] == after_first


async def test_a_cancelled_slot_cannot_be_recorded_against_or_edited(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    await client.post(_cancel(group, ids[1]), headers=tutor["headers"])
    made = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": dates[1].isoformat(), "plan_slot_id": ids[1]},
        headers=tutor["headers"],
    )
    assert made.status_code == 409
    edit = await client.patch(
        f"/api/v1/groups/{group['id']}/plan/slots/{ids[1]}",
        json={"start_time": "10:00"},
        headers=tutor["headers"],
    )
    assert edit.status_code == 409


async def test_the_suggestion_skips_a_cancelled_slot(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject, n=3)
    async with async_session() as s:
        (await s.get(PlanSlot, ids[0])).cancelled_at = datetime.now(timezone.utc)
        await s.commit()
    body = (
        await client.get(f"/api/v1/groups/{group['id']}/plan/next-lesson", headers=tutor["headers"])
    ).json()
    assert body["slot_id"] == ids[1]


async def test_a_reflow_never_regenerates_a_cancelled_slot_away(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    await client.post(_cancel(group, ids[1]), headers=tutor["headers"])
    async with async_session() as s:
        outcome = await reflow_plan_slots(s, plan_id)
        await s.commit()
    assert outcome is not None and outcome["status"] == "reflowed", outcome
    rows = await slot_rows(plan_id)
    kept = next((r for r in rows if r.id == ids[1]), None)
    assert kept is not None and kept.cancelled_at is not None
    # The slots the reflow wrote default their start time from the timetable (AV-119).
    regenerated = [r for r in rows if r.id not in ids and r.cancelled_at is None]
    assert regenerated and all(r.start_time is not None for r in regenerated)


# --- Authorization (QA-12) -------------------------------------------------------


async def test_another_organizations_tutor_gets_404(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-cancel@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    assert (await client.post(_cancel(group, ids[1]), headers=headers)).status_code == 404
    assert all(r.cancelled_at is None for r in await slot_rows(plan_id))


async def test_a_student_is_refused(client, tutor, group, subject, student):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    resp = await client.post(_cancel(group, ids[1]), headers=student["headers"])
    assert resp.status_code == 403
    assert all(r.cancelled_at is None for r in await slot_rows(plan_id))


async def test_no_token_is_401(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    assert (await client.post(_cancel(group, ids[1]))).status_code == 401


async def test_a_draft_plans_slot_is_404(client, tutor, group, subject):
    ch = await make_chapters(subject)
    plan_id, ids = await make_plan(
        group,
        tutor,
        [(ch["c1"], meeting_dates(1)[0], None)],
        status=TeachingPlanStatus.draft,
    )
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 404


async def test_another_classs_slot_is_404(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject)
    made = await client.post(
        "/api/v1/groups",
        json={"name": "Other class", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    other_group = made.json()
    assert (
        await client.post(_cancel(other_group, ids[1]), headers=tutor["headers"])
    ).status_code == 404
    assert all(r.cancelled_at is None for r in await slot_rows(plan_id))


@pytest.mark.parametrize("missing", [999999])
async def test_an_unknown_slot_is_404(client, tutor, group, subject, missing):
    await _world(group, tutor, subject)
    assert (await client.post(_cancel(group, missing), headers=tutor["headers"])).status_code == 404


async def test_cancelling_writes_nothing_outside_the_plans_own_slots(client, tutor, group, subject):
    ch, dates, plan_id, ids = await _world(group, tutor, subject, n=2)
    await client.post(_cancel(group, ids[0]), headers=tutor["headers"])
    async with async_session() as s:
        plans = {r.plan_id for r in (await s.scalars(select(PlanSlot))).all()}
    assert plans == {plan_id}


async def test_an_explicit_time_survives_a_shift_that_keeps_the_weekday(
    client, tutor, group, subject
):
    await add_timetable(group, MON, time(17, 0))
    ch = await make_chapters(subject)
    mondays = [next_weekday(MON, date.today() + timedelta(days=7))]
    for _ in range(2):
        mondays.append(mondays[-1] + timedelta(days=7))
    plan_id, ids = await make_plan(
        group,
        tutor,
        [(ch["c1"], d, time(18, 30) if i == 2 else None) for i, d in enumerate(mondays)],
        lessons_per_week=1,
    )
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 200
    rows = {r.id: r for r in await slot_rows(plan_id)}
    assert rows[ids[2]].scheduled_date == mondays[2] + timedelta(days=7)
    assert rows[ids[2]].start_time == time(18, 30)  # same weekday: kept


async def test_an_explicit_time_gives_way_to_the_timetable_when_the_weekday_changes(
    client, tutor, group, subject
):
    await add_timetable(group, MON, time(17, 0))
    await add_timetable(group, THU, time(15, 0))
    ch = await make_chapters(subject)
    dates = meeting_dates(3)  # Mon, Thu, Mon
    plan_id, ids = await make_plan(
        group,
        tutor,
        [(ch["c1"], d, time(18, 30) if i == 1 else None) for i, d in enumerate(dates)],
    )
    assert (await client.post(_cancel(group, ids[0]), headers=tutor["headers"])).status_code == 200
    rows = {r.id: r for r in await slot_rows(plan_id)}
    # The Thursday lesson moved to the following Monday: Monday's timetable time.
    assert rows[ids[1]].scheduled_date.weekday() == MON
    assert rows[ids[1]].start_time == time(17, 0)
