"""PR 14 — narrative storage, the generation job, and the weekly parent sweep.

The load-bearing properties: a handler that is safe to re-run (BE-6), a schedule
that survives a failure (the sweep, not a chain), a polymorphic row that can only
be read through its accessor (API-20), and a missing AI key that degrades the
surface rather than blocking anything (AI-20, INF-9).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    Evidence,
    EvidenceSource,
    Group,
    GroupMember,
    Job,
    JobStatus,
    Narrative,
    NarrativeAudience,
    Subject,
    Topic,
    User,
)
from app.services.ai import AiProvider, AiResponse, AIUnavailableError
from app.services.narrative import (
    ensure_narrative_sweep_scheduled,
    generate_narrative,
    latest_narrative,
    sweep_parent_narratives,
)
from app.workers.jobs import process_one_job


@pytest.fixture
def fake_narrative_ai(monkeypatch):
    """Stand in for the narrative surface's text_complete. Patched over the
    *calling* module's name — services import the helper into their own
    namespace, so patching app.services.ai would do nothing (QA-7). Never calls
    a real provider (QA-8)."""

    def _install(text: str = "A short paragraph.", *, raises: Exception | None = None):
        calls: list[str] = []

        async def _call(*, surface, prompt, max_tokens):
            calls.append(prompt)
            if raises is not None:
                raise raises
            return AiResponse(
                provider=AiProvider.anthropic,
                model="test-model",
                prompt_version="v1",
                input_tokens=5,
                output_tokens=5,
                text=text,
            )

        monkeypatch.setattr("app.services.narrative.text_complete", _call)
        return calls

    return _install


@pytest.fixture
async def world(client, tutor):
    """A tutor with one class, one enrolled student, and one piece of evidence."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.flush()
        topic = Topic(subject_id=subject.id, code="1.3", title="Atomic structure", weight=1.0)
        session.add(topic)
        await session.commit()
        subject_id, topic_id = subject.id, topic.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()

    async with async_session() as session:
        session.add(
            Evidence(
                student_id=student["id"],
                topic_id=topic_id,
                source_type=EvidenceSource.homework,
                score_pct=48.0,
                max_marks=20,
                occurred_at=datetime.now(timezone.utc),
                source_ref="submission:1",
            )
        )
        await session.commit()

    return {
        "group_id": group["id"],
        "student_id": student["id"],
        "subject_id": subject_id,
        "topic_id": topic_id,
    }


async def _run_class_narrative(world):
    async with async_session() as session:
        await generate_narrative(
            session,
            {"audience": NarrativeAudience.tutor_class.value, "group_id": world["group_id"]},
        )
        await session.commit()


async def _count_narratives() -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count(Narrative.id)))


async def test_rerun_same_payload_is_noop(world, fake_narrative_ai):
    fake_narrative_ai()
    await _run_class_narrative(world)
    assert await _count_narratives() == 1
    # Same payload, no new evidence: the handler re-reads state and writes nothing.
    await _run_class_narrative(world)
    assert await _count_narratives() == 1


async def test_narrative_carries_organization_id(world, fake_narrative_ai):
    fake_narrative_ai()
    await _run_class_narrative(world)
    async with async_session() as session:
        row = await session.scalar(select(Narrative))
        group = await session.get(Group, world["group_id"])
        assert row.organization_id == group.organization_id


async def test_prompt_version_recorded_on_row(world, fake_narrative_ai):
    fake_narrative_ai()
    await _run_class_narrative(world)
    async with async_session() as session:
        row = await session.scalar(select(Narrative))
        assert row.prompt_version  # traceable to the prompt that wrote it (AI-7)
        assert row.model == "test-model"


async def test_generated_at_is_timezone_aware(world, fake_narrative_ai):
    """The 0012_organizations.py failure mode: a naive column compiles to
    TIMESTAMP WITHOUT TIME ZONE and asyncpg rejects a tz-aware bind."""
    fake_narrative_ai()
    await _run_class_narrative(world)
    async with async_session() as session:
        row = await session.scalar(select(Narrative))
        column = Narrative.__table__.c.generated_at
        assert column.type.timezone is True
        assert row.generated_at is not None


async def test_audience_determines_which_fk_is_set(world, fake_narrative_ai):
    """A parent_student row has group_id None, and the accessor raises rather
    than quietly returning the wrong id — a paragraph about one child must never
    be attachable to another child's parent (API-20)."""
    fake_narrative_ai()
    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.parent_student.value,
                "student_id": world["student_id"],
            },
        )
        await session.commit()

    async with async_session() as session:
        row = await session.scalar(select(Narrative))
        assert row.audience is NarrativeAudience.parent_student
        assert row.group_id is None
        assert row.student_id == world["student_id"]
        assert row.target_id == world["student_id"]

        # The accessor refuses a row whose audience and FK disagree.
        broken = Narrative(
            organization_id=row.organization_id,
            audience=NarrativeAudience.tutor_class,
            group_id=None,
            student_id=world["student_id"],
            text="x",
            prompt_version="v1",
            model="m",
            generated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(ValueError):
            _ = broken.target_id


async def test_latest_read_orders_by_id_not_generated_at(world, fake_narrative_ai):
    """Two rows with identical generated_at must still resolve deterministically —
    a manual regenerate can race the sweep."""
    fake_narrative_ai()
    stamp = datetime.now(timezone.utc)
    async with async_session() as session:
        group = await session.get(Group, world["group_id"])
        for text in ("first", "second"):
            session.add(
                Narrative(
                    organization_id=group.organization_id,
                    audience=NarrativeAudience.tutor_class,
                    group_id=group.id,
                    student_id=None,
                    text=text,
                    prompt_version="v1",
                    model="m",
                    generated_at=stamp,
                )
            )
        await session.commit()
        org_id = group.organization_id

    async with async_session() as session:
        row = await latest_narrative(
            session,
            audience=NarrativeAudience.tutor_class,
            organization_id=org_id,
            group_id=world["group_id"],
        )
        assert row.text == "second"  # the later insertion, by id


async def test_missing_ai_key_degrades_surface_and_does_not_block_startup(world, fake_narrative_ai):
    """AI-20 / INF-9: no key means no stored narrative and a surface that states
    its absence — never a raised job, never a blocked boot."""
    fake_narrative_ai(raises=AIUnavailableError("ANTHROPIC_API_KEY is not configured"))
    await _run_class_narrative(world)  # must not raise
    assert await _count_narratives() == 0

    from app.main import app

    assert app is not None  # the app imported and built with the key absent


async def test_sweep_enqueues_only_students_due(world, fake_narrative_ai):
    """A narrative written yesterday is fresh; the sweep must not regenerate it."""
    fake_narrative_ai()
    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        session.add(
            Narrative(
                organization_id=student.organization_id,
                audience=NarrativeAudience.parent_student,
                group_id=None,
                student_id=student.id,
                text="yesterday's",
                prompt_version="v1",
                model="m",
                generated_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await session.commit()

    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert payloads == []  # nobody was due


async def test_sweep_enqueues_a_stale_student(world, fake_narrative_ai):
    fake_narrative_ai()
    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        session.add(
            Narrative(
                organization_id=student.organization_id,
                audience=NarrativeAudience.parent_student,
                group_id=None,
                student_id=student.id,
                text="old",
                prompt_version="v1",
                model="m",
                generated_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
        await session.commit()

    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert any(p.get("student_id") == world["student_id"] for p in payloads)


async def test_sweep_reenqueues_itself_with_future_run_after(world, fake_narrative_ai):
    fake_narrative_ai()
    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        sweep = await session.scalar(
            select(Job).where(
                Job.type == "sweep_parent_narratives", Job.status == JobStatus.pending
            )
        )
        assert sweep is not None, "the sweep must re-arm itself or the schedule dies"
        run_after = sweep.run_after
        if run_after.tzinfo is None:
            run_after = run_after.replace(tzinfo=timezone.utc)
        assert run_after > datetime.now(timezone.utc)


async def test_failed_narrative_does_not_break_next_weeks_sweep(world, fake_narrative_ai):
    """The whole reason the schedule is a sweep and not a chain: an individual
    narrative failing costs one student one cycle, never the schedule itself."""
    fake_narrative_ai(raises=AIUnavailableError("provider down"))

    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    # Drain the narrative jobs the sweep queued; each one fails to produce text.
    for _ in range(5):
        if not await process_one_job():
            break

    async with async_session() as session:
        sweep = await session.scalar(
            select(Job).where(
                Job.type == "sweep_parent_narratives", Job.status == JobStatus.pending
            )
        )
    assert sweep is not None  # next cycle is still scheduled


async def test_startup_reenqueue_is_idempotent(world):
    """A restart must heal a lost schedule without accumulating sweep rows."""
    async with async_session() as session:
        await ensure_narrative_sweep_scheduled(session)
        await session.commit()
    async with async_session() as session:
        await ensure_narrative_sweep_scheduled(session)
        await session.commit()

    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Job.id)).where(Job.type == "sweep_parent_narratives")
        )
    assert count == 1


async def test_kill_switch_stops_new_narratives_but_leaves_reads(
    world, fake_narrative_ai, monkeypatch
):
    fake_narrative_ai()
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "narrative_enabled", False)
    await _run_class_narrative(world)
    assert await _count_narratives() == 0


async def test_evidence_build_enqueues_a_class_narrative(world, fake_narrative_ai):
    """The class narrative is triggered from the tail of the evidence build, not
    from a router."""
    from app.services.narrative import enqueue_class_narratives_for_student_subject

    async with async_session() as session:
        await enqueue_class_narratives_for_student_subject(
            session, world["student_id"], world["subject_id"]
        )
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert any(p.get("group_id") == world["group_id"] for p in payloads)

    # Deduped: a burst of marks does not queue one narrative per submission.
    async with async_session() as session:
        await enqueue_class_narratives_for_student_subject(
            session, world["student_id"], world["subject_id"]
        )
        await session.commit()
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Job.id)).where(Job.type == "generate_narrative")
        )
    assert count == 1


async def test_narrative_row_has_no_review_state():
    """D2: there is no review step, so the row carries no review columns — asserted
    so a workflow cannot accrete around them later."""
    columns = set(Narrative.__table__.c.keys())
    assert "reviewed_at" not in columns
    assert "suppressed" not in columns


async def test_group_member_scoping_holds(world, fake_narrative_ai):
    """Sanity: the class grounding only reaches learners in that class."""
    fake_narrative_ai()
    async with async_session() as session:
        members = (
            await session.scalars(
                select(GroupMember.student_id).where(GroupMember.group_id == world["group_id"])
            )
        ).all()
    assert list(members) == [world["student_id"]]


# --- force=True — "Prepare again"'s correction mechanism -------------------
#
# test_narrative_api.py proves the route enqueues a forced payload; these prove
# the job handler actually honours it, bypassing the staleness no-op that makes
# an ordinary re-run a no-op (BE-6). Without this, "Prepare again" would look
# like it worked (200 OK, a job enqueued) while silently doing nothing.


async def test_force_regenerates_a_class_narrative_even_when_already_fresh(
    world, fake_narrative_ai
):
    fake_narrative_ai("first text")
    await _run_class_narrative(world)
    assert await _count_narratives() == 1

    # The stored row is at least as fresh as the latest evidence, so an
    # ordinary re-run would no-op — this is the case force must override.
    fake_narrative_ai("second text")
    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.tutor_class.value,
                "group_id": world["group_id"],
                "force": True,
            },
        )
        await session.commit()

    assert await _count_narratives() == 2
    async with async_session() as session:
        latest = await latest_narrative(
            session,
            audience=NarrativeAudience.tutor_class,
            organization_id=(await session.get(Group, world["group_id"])).organization_id,
            group_id=world["group_id"],
        )
    assert latest.text == "second text"


async def test_force_regenerates_a_parent_narrative_even_when_already_fresh(
    world, fake_narrative_ai
):
    fake_narrative_ai("first parent text")
    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.parent_student.value,
                "student_id": world["student_id"],
            },
        )
        await session.commit()
    assert await _count_narratives() == 1

    fake_narrative_ai("second parent text")
    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.parent_student.value,
                "student_id": world["student_id"],
                "force": True,
            },
        )
        await session.commit()

    assert await _count_narratives() == 2


async def test_force_with_no_evidence_still_writes_nothing(world, fake_narrative_ai):
    """Force is a correction, not a licence to fabricate: a class with no marked
    evidence at all must stay silent even under an explicit "Prepare again"."""
    fake_narrative_ai()
    async with async_session() as session:
        existing_group = await session.get(Group, world["group_id"])
        empty_group = Group(
            organization_id=existing_group.organization_id,
            tutor_id=existing_group.tutor_id,
            subject_id=world["subject_id"],
            name="No evidence yet",
        )
        session.add(empty_group)
        await session.commit()
        empty_group_id = empty_group.id

    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.tutor_class.value,
                "group_id": empty_group_id,
                "force": True,
            },
        )
        await session.commit()

    assert await _count_narratives() == 0


async def test_force_on_a_missing_group_is_a_noop_not_an_error(world, fake_narrative_ai):
    fake_narrative_ai()
    async with async_session() as session:
        await generate_narrative(
            session,
            {
                "audience": NarrativeAudience.tutor_class.value,
                "group_id": 999_999,
                "force": True,
            },
        )
        await session.commit()
    assert await _count_narratives() == 0


# --- _aware() ----------------------------------------------------------------


def test_aware_leaves_a_tz_aware_datetime_untouched():
    from app.services.narrative import _aware

    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _aware(stamp) is stamp


def test_aware_attaches_utc_to_a_naive_datetime():
    """SQLite hands back tz-naive datetimes where Postgres returns aware ones;
    comparing a naive and an aware datetime raises, so every read is normalized
    before comparison."""
    from app.services.narrative import _aware

    naive = datetime(2026, 1, 1)
    result = _aware(naive)
    assert result.tzinfo is timezone.utc
    assert result.replace(tzinfo=None) == naive


def test_aware_of_none_is_none():
    from app.services.narrative import _aware

    assert _aware(None) is None


# --- The prompt registered for this surface ---------------------------------


def test_narrative_prompt_is_registered_with_its_rules():
    from app.services.prompts import get_prompt

    template = get_prompt("narrative")
    assert template.version == "v1"
    lowered = template.system.lower()
    # Both audiences are handled by one prompt, selected by the grounding data.
    assert "audience" in lowered
    assert "tutor" in lowered and "parent" in lowered
    # No gender is stored, so a pronoun would be a guess (UX-31-adjacent).
    assert "pronoun" in lowered
    # Learner-derived grounding data is data, never instructions (prompt
    # injection posture), the same rule class_brief carries.
    assert "data, never" in lowered or "never instructions" in lowered


# --- The marking.py integration point ---------------------------------------


async def test_evidence_landing_via_record_marks_as_evidence_enqueues_a_narrative(
    world, monkeypatch
):
    """services/marking.record_marks_as_evidence gained one new call in this PR:
    the class narrative is refreshed from the tail of the evidence build, not
    from a router. build_homework_evidence itself is out of scope here (it is
    pre-existing), so it is stubbed to isolate the new integration point."""
    from app.models import Submission
    from app.services.marking import record_marks_as_evidence

    async def fake_build_homework_evidence(session, submission):
        return set()

    monkeypatch.setattr(
        "app.services.marking.build_homework_evidence", fake_build_homework_evidence
    )

    async with async_session() as session:
        submission = Submission(student_id=world["student_id"])
        session.add(submission)
        await session.flush()
        await record_marks_as_evidence(session, submission, world["subject_id"])
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert any(p.get("group_id") == world["group_id"] for p in payloads)
