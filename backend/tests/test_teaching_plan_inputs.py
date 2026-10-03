"""Task 6.2 (AV-15): the teaching-plan inputs on a class."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import PlanBreak, TeachingPlan, TeachingPlanStatus
from app.services.teaching_plan import accepted_plan_for_group
from tests.factories import org_id

EXAM = (date.today() + timedelta(days=120)).isoformat()


def _inputs(**over):
    body = {"exam_date": EXAM, "lessons_per_week": 2, "lesson_minutes": 60}
    body.update(over)
    return body


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest.fixture
async def other_tutor(client, tutor):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-plan@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _slot(client, tutor, group, weekday, minutes):
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/lessons",
        json={"weekday": weekday, "start_time": "17:00", "duration_min": minutes},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text


def _url(group, suffix=""):
    return f"/api/v1/groups/{group['id']}/plan{suffix}"


async def _make_accepted(group, tutor):
    async with async_session() as s:
        plan = TeachingPlan(
            organization_id=await org_id(s),
            group_id=group["id"],
            status=TeachingPlanStatus.accepted,
            exam_date=date.today() + timedelta(days=200),
            lessons_per_week=3,
            lesson_minutes=90,
            accepted_at=datetime.now(timezone.utc),
            accepted_by_id=tutor["user"]["id"],
        )
        plan.breaks = [PlanBreak(start_date=date.today(), end_date=date.today(), label="Half term")]
        s.add(plan)
        await s.commit()
        return plan.id


# --- Pre-fill ----------------------------------------------------------------


async def test_no_timetable_prefills_nothing(client, tutor, group):
    resp = await client.get(_url(group), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == {
        "draft": None,
        "accepted": None,
        "timetable_defaults": {"lessons_per_week": None, "lesson_minutes": None},
    }


async def test_two_slots_prefill_count_and_duration(client, tutor, group):
    await _slot(client, tutor, group, 1, 90)
    await _slot(client, tutor, group, 3, 90)
    defaults = (await client.get(_url(group), headers=tutor["headers"])).json()[
        "timetable_defaults"
    ]
    assert defaults == {"lessons_per_week": 2, "lesson_minutes": 90}


async def test_mixed_durations_use_most_common_then_longest(client, tutor, group):
    for weekday, minutes in [(0, 60), (1, 60), (2, 90)]:
        await _slot(client, tutor, group, weekday, minutes)
    got = (await client.get(_url(group), headers=tutor["headers"])).json()["timetable_defaults"]
    assert got == {"lessons_per_week": 3, "lesson_minutes": 60}

    await _slot(client, tutor, group, 3, 90)  # now 2 x 60, 2 x 90: tie -> longest
    got = (await client.get(_url(group), headers=tutor["headers"])).json()["timetable_defaults"]
    assert got == {"lessons_per_week": 4, "lesson_minutes": 90}


# --- Saving ------------------------------------------------------------------


async def test_save_creates_then_updates_the_one_draft(client, tutor, group):
    first = await client.put(_url(group, "/inputs"), json=_inputs(), headers=tutor["headers"])
    assert first.status_code == 200, first.text
    draft = first.json()["draft"]
    assert draft["lessons_per_week"] == 2 and draft["past_paper_start_date"] is None

    second = await client.put(
        _url(group, "/inputs"),
        json=_inputs(lessons_per_week=4, past_paper_start_date=_day(90)),
        headers=tutor["headers"],
    )
    assert second.json()["draft"]["id"] == draft["id"]
    assert second.json()["draft"]["lessons_per_week"] == 4
    async with async_session() as s:
        rows = (await s.scalars(select(TeachingPlan))).all()
    assert len(rows) == 1
    async with async_session() as s:
        assert rows[0].organization_id == await org_id(s)


async def test_accepted_plan_is_never_modified(client, tutor, group):
    accepted_id = await _make_accepted(group, tutor)
    resp = await client.put(
        _url(group, "/inputs"), json=_inputs(lessons_per_week=5), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"]["id"] == accepted_id
    assert body["accepted"]["lessons_per_week"] == 3
    assert body["accepted"]["lesson_minutes"] == 90
    assert body["draft"]["id"] != accepted_id
    assert body["draft"]["lessons_per_week"] == 5
    # The live plan's holidays carry into the new draft.
    assert [b["label"] for b in body["draft"]["breaks"]] == ["Half term"]


async def test_only_the_accepted_plan_is_returned_by_the_reader(client, tutor, group):
    await client.put(_url(group, "/inputs"), json=_inputs(), headers=tutor["headers"])
    async with async_session() as s:
        assert await accepted_plan_for_group(s, group["id"]) is None
    await _make_accepted(group, tutor)
    async with async_session() as s:
        plan = await accepted_plan_for_group(s, group["id"])
        assert plan is not None and plan.status == TeachingPlanStatus.accepted


@pytest.mark.parametrize(
    "override",
    [
        {"lessons_per_week": 0},
        {"lessons_per_week": 15},
        {"lesson_minutes": 14},
        {"lesson_minutes": 301},
        {"exam_date": date.today().isoformat()},
        {"exam_date": _day(-3)},
        {"past_paper_start_date": _day(121)},
    ],
)
async def test_invalid_inputs_are_422(client, tutor, group, override):
    resp = await client.put(
        _url(group, "/inputs"), json=_inputs(**override), headers=tutor["headers"]
    )
    assert resp.status_code == 422, resp.text
    async with async_session() as s:
        assert (await s.scalars(select(TeachingPlan))).all() == []


# --- Breaks ------------------------------------------------------------------


async def test_break_needs_a_draft(client, tutor, group):
    resp = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(10), "end_date": _day(12), "label": "x"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 409


async def test_add_and_remove_a_break(client, tutor, group):
    await client.put(_url(group, "/inputs"), json=_inputs(), headers=tutor["headers"])
    created = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(10), "end_date": _day(10), "label": "Bank holiday"},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text
    listed = (await client.get(_url(group), headers=tutor["headers"])).json()
    assert [b["label"] for b in listed["draft"]["breaks"]] == ["Bank holiday"]

    gone = await client.delete(
        _url(group, f"/breaks/{created.json()['id']}"), headers=tutor["headers"]
    )
    assert gone.status_code == 204
    again = await client.delete(
        _url(group, f"/breaks/{created.json()['id']}"), headers=tutor["headers"]
    )
    assert again.status_code == 404


async def test_break_validation_and_overlap(client, tutor, group):
    await client.put(_url(group, "/inputs"), json=_inputs(), headers=tutor["headers"])
    ok = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(10), "end_date": _day(20), "label": "Easter"},
        headers=tutor["headers"],
    )
    assert ok.status_code == 201
    backwards = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(30), "end_date": _day(29), "label": "x"},
        headers=tutor["headers"],
    )
    assert backwards.status_code == 422
    overlap = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(20), "end_date": _day(25), "label": "Mock week"},
        headers=tutor["headers"],
    )
    assert overlap.status_code == 422
    assert "Easter" in overlap.json()["detail"]
    adjacent = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(21), "end_date": _day(25), "label": "Mock week"},
        headers=tutor["headers"],
    )
    assert adjacent.status_code == 201


async def test_accepted_plans_breaks_cannot_be_deleted_here(client, tutor, group):
    await _make_accepted(group, tutor)
    async with async_session() as s:
        break_id = (await s.scalars(select(PlanBreak.id))).first()
    resp = await client.delete(_url(group, f"/breaks/{break_id}"), headers=tutor["headers"])
    assert resp.status_code == 404


# --- Authorization (QA-12) -----------------------------------------------------


async def test_student_is_refused_every_route(client, student, group):
    h = student["headers"]
    calls = [
        client.get(_url(group), headers=h),
        client.put(_url(group, "/inputs"), json=_inputs(), headers=h),
        client.post(
            _url(group, "/breaks"),
            json={"start_date": _day(1), "end_date": _day(2), "label": "x"},
            headers=h,
        ),
        client.delete(_url(group, "/breaks/1"), headers=h),
    ]
    for call in calls:
        assert (await call).status_code == 403


async def test_unauthenticated_is_401(client, group):
    assert (await client.get(_url(group))).status_code == 401
    assert (await client.put(_url(group, "/inputs"), json=_inputs())).status_code == 401


async def test_another_organizations_class_is_404(client, tutor, group, other_tutor):
    await client.put(_url(group, "/inputs"), json=_inputs(), headers=tutor["headers"])
    created = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(10), "end_date": _day(11), "label": "x"},
        headers=tutor["headers"],
    )
    break_id = created.json()["id"]

    assert (await client.get(_url(group), headers=other_tutor)).status_code == 404
    put = await client.put(_url(group, "/inputs"), json=_inputs(), headers=other_tutor)
    assert put.status_code == 404
    post = await client.post(
        _url(group, "/breaks"),
        json={"start_date": _day(1), "end_date": _day(2), "label": "x"},
        headers=other_tutor,
    )
    assert post.status_code == 404
    assert (
        await client.delete(_url(group, f"/breaks/{break_id}"), headers=other_tutor)
    ).status_code == 404

    # Untouched by the intruder.
    mine = (await client.get(_url(group), headers=tutor["headers"])).json()
    assert len(mine["draft"]["breaks"]) == 1
