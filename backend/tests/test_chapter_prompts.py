"""Task 6.7 — the chapter-start classified prompt on the tutor's home (AV-20, AV-22)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Chapter,
    Classified,
    Group,
    PlanSlot,
    TeachingPlan,
    TeachingPlanStatus,
    User,
    UserRole,
)
from app.services.chapter_prompts import CHAPTER_LOOKAHEAD_DAYS
from tests.factories import make_subject

# A fixed day, injected where the tutor home asks for the time, so a run that
# straddles midnight (or a tutor zone) cannot move "today" under an assertion.
TODAY = date(2026, 10, 3)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(
        "app.services.today.now_in",
        lambda _zone: datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=timezone.utc),
    )


def _days(n: int) -> date:
    return TODAY + timedelta(days=n)


async def _register(client, email: str):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": email, "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _class_for(email: str, *, name: str = "Year 11 Chemistry", code: str = "4CH1"):
    """A class, its subject and one chapter, owned by the tutor with this email."""
    async with async_session() as session:
        tutor = await session.scalar(select(User).where(User.email == email))
        subject = await make_subject(session, organization_id=tutor.organization_id, code=code)
        group = Group(
            organization_id=tutor.organization_id,
            tutor_id=tutor.id,
            subject_id=subject.id,
            name=name,
        )
        chapter = Chapter(subject_id=subject.id, code="4", title="Organic chemistry", position=4)
        session.add_all([group, chapter])
        await session.commit()
        return {
            "org_id": tutor.organization_id,
            "tutor_id": tutor.id,
            "subject_id": subject.id,
            "group_id": group.id,
            "chapter_id": chapter.id,
        }


async def _plan(world, dates, *, status=TeachingPlanStatus.accepted, chapter_id=None):
    async with async_session() as session:
        plan = TeachingPlan(
            organization_id=world["org_id"],
            group_id=world["group_id"],
            status=status,
            exam_date=_days(200),
            lessons_per_week=2,
            lesson_minutes=60,
        )
        if status == TeachingPlanStatus.accepted:
            plan.accepted_at = datetime.now(timezone.utc)
            plan.accepted_by_id = world["tutor_id"]
        session.add(plan)
        await session.flush()
        for i, d in enumerate(dates):
            session.add(
                PlanSlot(
                    plan_id=plan.id,
                    chapter_id=chapter_id or world["chapter_id"],
                    scheduled_date=d,
                    sequence=i,
                )
            )
        await session.commit()


async def _classified(world, *, organization_id=None):
    async with async_session() as session:
        session.add(
            Classified(
                organization_id=organization_id or world["org_id"],
                tutor_id=world["tutor_id"],
                subject_id=world["subject_id"],
                title="Organic",
                file_path="x",
                file_name="x.pdf",
                file_mime="application/pdf",
                chapter_id=world["chapter_id"],
            )
        )
        await session.commit()


async def _prompts(client, headers):
    resp = await client.get("/api/v1/today", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["chapter_prompts"]


@pytest.fixture
async def setup(client, tutor):
    return tutor["headers"], await _class_for("tutor@example.com")


async def test_an_accepted_plan_entering_a_chapter_without_a_classified_prompts(client, setup):
    headers, world = setup
    await _plan(world, [_days(-2), _days(3), _days(10)])
    [p] = await _prompts(client, headers)
    assert p["group_id"] == world["group_id"]
    assert p["group_name"] == "Year 11 Chemistry"
    assert p["chapter_title"] == "Organic chemistry"
    assert p["chapter_code"] == "4"
    assert p["started"] is True
    assert p["starts_on"] == _days(-2).isoformat()
    assert p["ends_on"] == _days(10).isoformat()


async def test_a_classified_for_the_chapter_removes_the_prompt(client, setup):
    headers, world = setup
    await _plan(world, [_days(-2), _days(3)])
    assert len(await _prompts(client, headers)) == 1
    await _classified(world)
    assert await _prompts(client, headers) == []


async def test_a_draft_plan_never_prompts(client, setup):
    headers, world = setup
    await _plan(world, [_days(-2), _days(3)], status=TeachingPlanStatus.draft)
    assert await _prompts(client, headers) == []


async def test_another_organizations_plan_does_not_prompt_me(client, setup):
    headers, _mine = setup
    await _register(client, "other@example.com")
    theirs = await _class_for("other@example.com", name="Their class", code="9XX9")
    await _plan(theirs, [_days(-2), _days(3)])
    assert await _prompts(client, headers) == []


async def test_another_organizations_classified_does_not_suppress_mine(client, setup):
    headers, world = setup
    await _plan(world, [_days(-2), _days(3)])
    await _register(client, "other@example.com")
    theirs = await _class_for("other@example.com", name="Their class", code="9XX9")
    # Filed under *my* chapter id, owned by their organization: the check must
    # be scoped by organization (SEC-8), not by chapter alone.
    await _classified({**world, "org_id": theirs["org_id"], "tutor_id": theirs["tutor_id"]})
    assert len(await _prompts(client, headers)) == 1


async def test_a_colleagues_class_in_my_organization_is_not_mine(client, setup):
    headers, world = setup
    async with async_session() as session:
        colleague = User(
            email="colleague@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="C",
            organization_id=world["org_id"],
        )
        session.add(colleague)
        await session.flush()
        group = await session.get(Group, world["group_id"])
        group.tutor_id = colleague.id
        await session.commit()
    await _plan(world, [_days(-2), _days(3)])
    assert await _prompts(client, headers) == []


async def test_lookahead_window_includes_the_boundary_and_excludes_beyond(client, setup):
    headers, world = setup
    await _plan(world, [_days(CHAPTER_LOOKAHEAD_DAYS), _days(CHAPTER_LOOKAHEAD_DAYS + 5)])
    [p] = await _prompts(client, headers)
    assert p["started"] is False


async def test_a_chapter_starting_beyond_the_window_does_not_prompt(client, setup):
    headers, world = setup
    await _plan(world, [_days(CHAPTER_LOOKAHEAD_DAYS + 1), _days(CHAPTER_LOOKAHEAD_DAYS + 5)])
    assert await _prompts(client, headers) == []


async def test_a_chapter_whose_slots_are_all_past_does_not_prompt(client, setup):
    headers, world = setup
    await _plan(world, [_days(-20), _days(-1)])
    assert await _prompts(client, headers) == []


async def test_a_chapter_ending_today_still_prompts(client, setup):
    headers, world = setup
    await _plan(world, [_days(-5), _days(0)])
    assert len(await _prompts(client, headers)) == 1


async def test_one_prompt_per_class_and_chapter_soonest_first(client, setup):
    headers, world = setup
    async with async_session() as session:
        second = Group(
            organization_id=world["org_id"],
            tutor_id=world["tutor_id"],
            subject_id=world["subject_id"],
            name="Year 10 Chemistry",
        )
        extra = Chapter(subject_id=world["subject_id"], code="5", title="Rates", position=5)
        session.add_all([second, extra])
        await session.commit()
        second_id, extra_id = second.id, extra.id
    # Class one: chapter 4 has several slots (still one prompt), chapter 5 is next week.
    await _plan(world, [_days(-1), _days(1), _days(2)])
    await _plan(world, [], status=TeachingPlanStatus.draft)  # a draft alongside is ignored
    async with async_session() as session:
        plan = await session.scalar(
            select(TeachingPlan).where(TeachingPlan.status == TeachingPlanStatus.accepted)
        )
        session.add(
            PlanSlot(plan_id=plan.id, chapter_id=extra_id, scheduled_date=_days(4), sequence=9)
        )
        await session.commit()
    # Class two on the same subject, same chapter, starting later.
    await _plan({**world, "group_id": second_id}, [_days(2)])
    prompts = await _prompts(client, headers)
    assert [(p["group_name"], p["chapter_code"]) for p in prompts] == [
        ("Year 11 Chemistry", "4"),
        ("Year 10 Chemistry", "4"),
        ("Year 11 Chemistry", "5"),
    ]
