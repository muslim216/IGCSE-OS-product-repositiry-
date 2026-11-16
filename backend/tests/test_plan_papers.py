"""T-076: a plan has 1-6 papers, each with its own date, and a revision start date."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import TeachingPlan, TeachingPlanPaper
from tests.factories import server_today


def _day(offset: int) -> str:
    return (server_today() + timedelta(days=offset)).isoformat()


def _url(group, suffix=""):
    return f"/api/v1/groups/{group['id']}/plan{suffix}"


def _body(**over):
    body = {"lessons_per_week": 2, "lesson_minutes": 60}
    body.update(over)
    return body


def _paper(name, offset):
    return {"name": name, "exam_date": _day(offset)}


@pytest.fixture
async def other_tutor(client, tutor):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-papers@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _put(client, tutor, group, **over):
    return await client.put(_url(group, "/inputs"), json=_body(**over), headers=tutor["headers"])


async def test_papers_and_revision_date_are_saved_and_returned_in_order(client, tutor, group):
    resp = await _put(
        client,
        tutor,
        group,
        papers=[_paper("Paper 2", 130), _paper("Paper 1", 120)],
        revision_start_date=_day(90),
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()["draft"]
    # Ordered by date, whatever order they arrived in.
    assert draft["papers"] == [_paper("Paper 1", 120), _paper("Paper 2", 130)]
    assert draft["revision_start_date"] == _day(90)
    assert draft["exam_date"] == _day(120)


async def test_the_single_exam_date_still_works_and_becomes_one_paper(client, tutor, group):
    resp = await _put(client, tutor, group, exam_date=_day(100))
    assert resp.status_code == 200, resp.text
    draft = resp.json()["draft"]
    assert draft["papers"] == [_paper("Exam", 100)]
    assert draft["revision_start_date"] is None
    assert draft["exam_date"] == _day(100)


async def test_exam_date_follows_the_earliest_paper_when_papers_change(client, tutor, group):
    await _put(client, tutor, group, papers=[_paper("A", 120), _paper("B", 140)])
    resp = await _put(client, tutor, group, papers=[_paper("B", 140), _paper("A", 110)])
    draft = resp.json()["draft"]
    assert draft["exam_date"] == _day(110)
    async with async_session() as s:
        plan = await s.get(TeachingPlan, draft["id"])
        rows = (
            await s.scalars(
                select(TeachingPlanPaper)
                .where(TeachingPlanPaper.plan_id == plan.id)
                .order_by(TeachingPlanPaper.position)
            )
        ).all()
    assert plan.exam_date == server_today() + timedelta(days=110)
    assert [(r.position, r.name) for r in rows] == [(1, "A"), (2, "B")]


async def test_dropping_a_paper_removes_it(client, tutor, group):
    await _put(client, tutor, group, papers=[_paper("A", 120), _paper("B", 140)])
    resp = await _put(client, tutor, group, papers=[_paper("A", 120)])
    assert resp.json()["draft"]["papers"] == [_paper("A", 120)]


async def test_a_seventh_paper_is_refused_and_nothing_is_saved(client, tutor, group):
    resp = await _put(client, tutor, group, papers=[_paper(f"P{i}", 100 + i) for i in range(7)])
    assert resp.status_code == 422
    assert resp.json()["detail"] == "A plan can have between 1 and 6 papers"
    assert (await client.get(_url(group), headers=tutor["headers"])).json()["draft"] is None


async def test_no_papers_and_no_exam_date_is_refused(client, tutor, group):
    resp = await _put(client, tutor, group, papers=[])
    assert resp.status_code == 422
    assert resp.json()["detail"] == "A plan can have between 1 and 6 papers"


async def test_revision_after_the_first_paper_is_refused(client, tutor, group):
    resp = await _put(
        client,
        tutor,
        group,
        papers=[_paper("A", 120), _paper("B", 140)],
        revision_start_date=_day(121),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Revision has to start on or before your first paper"


async def test_revision_on_the_first_paper_day_is_allowed(client, tutor, group):
    resp = await _put(
        client, tutor, group, papers=[_paper("A", 120)], revision_start_date=_day(120)
    )
    assert resp.status_code == 200, resp.text


async def test_a_paper_without_a_name_is_refused(client, tutor, group):
    for name in ("", "   "):
        resp = await _put(client, tutor, group, papers=[{"name": name, "exam_date": _day(120)}])
        assert resp.status_code == 422, name
        assert resp.json()["detail"] == "Every paper needs a name"


async def test_the_past_paper_rule_is_checked_against_the_first_paper(client, tutor, group):
    resp = await _put(
        client,
        tutor,
        group,
        papers=[_paper("A", 120), _paper("B", 140)],
        past_paper_start_date=_day(125),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Past papers cannot start after the exam date"


async def test_the_first_paper_must_be_in_the_future(client, tutor, group):
    resp = await _put(client, tutor, group, papers=[_paper("A", 0)])
    assert resp.status_code == 422
    assert resp.json()["detail"] == "The exam date must be in the future"


async def test_another_organizations_plan_papers_are_not_readable_or_writable(
    client, tutor, group, other_tutor
):
    await _put(client, tutor, group, papers=[_paper("A", 120), _paper("B", 140)])
    assert (await client.get(_url(group), headers=other_tutor)).status_code == 404
    put = await client.put(
        _url(group, "/inputs"),
        json=_body(papers=[_paper("Evil", 111)]),
        headers=other_tutor,
    )
    assert put.status_code == 404
    mine = (await client.get(_url(group), headers=tutor["headers"])).json()["draft"]
    assert mine["papers"] == [_paper("A", 120), _paper("B", 140)]
