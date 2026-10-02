"""The teaching plan models (task 6.1), exercised through the ORM-built schema."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.models as models
from app.db import async_session
from app.models import (
    Chapter,
    Group,
    Organization,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
    TeachingPlanStatus,
    User,
    UserRole,
)
from tests.factories import make_subject


@pytest.fixture
async def world():
    """An org, a tutor, a class with a subject, and two chapters."""
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
        group = Group(
            organization_id=org.id, tutor_id=tutor.id, subject_id=subject.id, name="Year 11"
        )
        chapters = [
            Chapter(subject_id=subject.id, code=f"C{i}", title=f"Chapter {i}", position=i)
            for i in (1, 2)
        ]
        session.add_all([group, *chapters])
        await session.commit()
        yield {
            "org_id": org.id,
            "tutor_id": tutor.id,
            "group_id": group.id,
            "chapter_ids": [c.id for c in chapters],
        }


def _plan(world, **overrides) -> TeachingPlan:
    values = {
        "organization_id": world["org_id"],
        "group_id": world["group_id"],
        "exam_date": date(2027, 5, 1),
        "lessons_per_week": 2,
        "lesson_minutes": 60,
    }
    values.update(overrides)
    return TeachingPlan(**values)


def test_models_and_enums_are_exported_from_the_barrel():
    for name in (
        "TeachingPlan",
        "PlanSlot",
        "PlanBreak",
        "TeachingPlanStatus",
        "PlanSlotProvenance",
    ):
        assert hasattr(models, name), name
        assert name in models.__all__, name


async def test_plan_defaults_to_draft_and_slot_to_generated(world):
    async with async_session() as session:
        plan = _plan(world)
        session.add(plan)
        await session.flush()
        slot = PlanSlot(
            plan_id=plan.id,
            chapter_id=world["chapter_ids"][0],
            scheduled_date=date(2026, 10, 10),
            sequence=1,
        )
        session.add(slot)
        await session.commit()
        assert plan.status is TeachingPlanStatus.draft
        assert plan.past_paper_start_date is None
        assert slot.provenance is PlanSlotProvenance.generated


async def test_slots_come_back_ordered_by_sequence_whatever_the_insert_order(world):
    async with async_session() as session:
        plan = _plan(world)
        session.add(plan)
        await session.flush()
        for seq in (3, 1, 2):
            session.add(
                PlanSlot(
                    plan_id=plan.id,
                    chapter_id=world["chapter_ids"][0],
                    # Same date for all: two lessons can share a day.
                    scheduled_date=date(2026, 10, 10),
                    sequence=seq,
                )
            )
        await session.commit()
        plan_id = plan.id
    async with async_session() as session:
        loaded = await session.get(TeachingPlan, plan_id)
        await session.refresh(loaded, ["slots"])
        assert [s.sequence for s in loaded.slots] == [1, 2, 3]


async def test_second_draft_for_a_class_is_rejected(world):
    async with async_session() as session:
        session.add(_plan(world))
        await session.commit()
    async with async_session() as session:
        session.add(_plan(world))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_draft_may_sit_beside_the_accepted_plan(world):
    async with async_session() as session:
        session.add(
            _plan(
                world,
                status=TeachingPlanStatus.accepted,
                accepted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                accepted_by_id=world["tutor_id"],
            )
        )
        session.add(_plan(world))
        await session.commit()
        rows = (await session.scalars(select(TeachingPlan))).all()
        assert {p.status for p in rows} == {TeachingPlanStatus.draft, TeachingPlanStatus.accepted}


async def test_accepted_plan_without_acceptor_is_rejected(world):
    async with async_session() as session:
        session.add(_plan(world, status=TeachingPlanStatus.accepted))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"lessons_per_week": 0},
        {"lesson_minutes": 0},
        {"past_paper_start_date": date(2027, 5, 2)},
    ],
    ids=["lessons_per_week_zero", "lesson_minutes_zero", "past_papers_after_exam"],
)
async def test_plan_inputs_out_of_range_are_rejected(world, overrides):
    async with async_session() as session:
        session.add(_plan(world, **overrides))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_past_papers_may_start_on_exam_day(world):
    async with async_session() as session:
        session.add(_plan(world, past_paper_start_date=date(2027, 5, 1)))
        await session.commit()


async def test_break_ending_before_it_starts_is_rejected(world):
    async with async_session() as session:
        plan = _plan(world)
        session.add(plan)
        await session.flush()
        session.add(
            PlanBreak(
                plan_id=plan.id,
                start_date=date(2026, 12, 20),
                end_date=date(2026, 12, 19),
                label="Winter",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_past_papers_may_start_before_the_last_chapter_slot(world):
    """AV-16: the phases overlap by design, so this must be storable."""
    async with async_session() as session:
        plan = _plan(world, past_paper_start_date=date(2027, 1, 10))
        session.add(plan)
        await session.flush()
        session.add(
            PlanSlot(
                plan_id=plan.id,
                chapter_id=world["chapter_ids"][1],
                scheduled_date=date(2027, 2, 1),
                sequence=1,
            )
        )
        await session.commit()
        slot = await session.scalar(select(PlanSlot))
        assert plan.past_paper_start_date < slot.scheduled_date
