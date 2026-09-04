"""PR 14 — narrative storage, the generation job, and the weekly parent sweep.

The load-bearing properties: a handler that is safe to re-run (BE-6), a schedule
that survives a failure (the sweep, not a chain), a polymorphic row that can only
be read through its accessor (API-20), and a missing AI key that degrades the
surface rather than blocking anything (AI-20, INF-9).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
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
    _aware,
    enqueue_narratives_for_group,
    ensure_narrative_sweep_scheduled,
    generate_narrative,
    latest_narrative,
    sweep_parent_narratives,
)
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults


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
            **await subject_defaults(session),
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


@pytest.mark.parametrize(
    "group_id_set,student_id_set",
    [(True, True), (False, False)],
    ids=["both_targets", "no_target"],
)
async def test_a_row_without_exactly_one_target_is_rejected_by_the_database(
    world, group_id_set, student_id_set
):
    """`target_id` guards the *read*. Without the CHECK constraint the write
    still succeeds, and a row with both FKs — or neither — then raises on every
    subsequent read, far from the code that wrote it. The database rejects it at
    the insert instead."""
    async with async_session() as session:
        group = await session.get(Group, world["group_id"])
        session.add(
            Narrative(
                organization_id=group.organization_id,
                audience=NarrativeAudience.tutor_class,
                group_id=group.id if group_id_set else None,
                student_id=world["student_id"] if student_id_set else None,
                text="x",
                prompt_version="v1",
                model="m",
                generated_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


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


async def test_sweep_caps_how_many_students_one_run_enqueues(
    client, tutor, world, fake_narrative_ai, monkeypatch
):
    """A first run against an established installation must not enqueue one AI
    call per learner at once. The cap bounds a single cycle; the set is
    re-derived every sweep, so the backlog drains over consecutive runs instead
    of arriving as one burst of spend."""
    fake_narrative_ai()
    # A second due learner, so there is more work than the cap allows.
    second = (
        await client.post(
            f"/api/v1/groups/{world['group_id']}/students",
            json={"name": "Omar", "username": "omar01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        session.add(
            Evidence(
                student_id=second["id"],
                topic_id=world["topic_id"],
                source_type=EvidenceSource.homework,
                score_pct=61.0,
                max_marks=20,
                occurred_at=datetime.now(timezone.utc),
                source_ref="submission:2",
            )
        )
        await session.commit()

    monkeypatch.setattr(get_settings(), "narrative_sweep_max_students", 1)
    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert len(payloads) == 1, "one run must not exceed the cap"

    # The one it skipped is still due, so the next run picks it up — capped, not
    # dropped.
    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        students = {
            p["student_id"]
            for p in (
                await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
            ).all()
        }
    assert students == {world["student_id"], second["id"]}


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
    """Both halves of the name. The switch stops *generation*; it must not make
    the paragraphs already written disappear from the surfaces reading them —
    that is the difference between an instant rollback and an outage."""
    fake_narrative_ai()
    from app.config import get_settings

    settings = get_settings()
    # A narrative that already exists before the switch is flipped.
    await _run_class_narrative(world)
    assert await _count_narratives() == 1

    monkeypatch.setattr(settings, "narrative_enabled", False)
    await _run_class_narrative(world)
    assert await _count_narratives() == 1, "the switch must stop new generation"

    async with async_session() as session:
        group = await session.get(Group, world["group_id"])
        stored = await latest_narrative(
            session,
            audience=NarrativeAudience.tutor_class,
            organization_id=group.organization_id,
            group_id=group.id,
        )
    assert stored is not None, "stored narratives must stay readable with the switch off"
    assert stored.text


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


async def test_a_failing_sweep_still_leaves_the_next_one_scheduled(
    world, fake_narrative_ai, monkeypatch
):
    """The reliability property the sweep exists for, at the sweep's own level.

    test_failed_narrative_does_not_break_next_weeks_sweep covers an individual
    narrative failing, which was always safe — each is its own job. This covers
    the *sweep* failing, which was not: the successor used to be enqueued on the
    handler's own session at the end of the body, so a raise anywhere in that
    body rolled the session back and took the schedule with it. After
    MAX_ATTEMPTS the job is failed, nothing watches that, and every parent
    narrative stops until the process restarts. The successor is now committed
    up front in its own transaction, so it survives whatever the body does.
    """
    fake_narrative_ai()

    def explode(*args, **kwargs):
        raise RuntimeError("sweep body failed")

    # Fail inside the per-student work, which runs after the successor is armed.
    # _add_jobs is the right seam because it is reached only by that half:
    # _commit_successor_sweep writes through _enqueue_one, so patching anything
    # shared would stop the schedule being armed at all and the assertion below
    # would pass or fail for a reason the test is not about.
    monkeypatch.setattr("app.services.narrative._add_jobs", explode)

    async with async_session() as session:
        with pytest.raises(RuntimeError):
            await sweep_parent_narratives(session, {})

    # The assertion the test is named for. Without it this only proved that the
    # body raises — which the monkeypatch guarantees — and would have passed
    # just as happily against the old ordering that lost the schedule.
    async with async_session() as session:
        successor = await session.scalar(
            select(Job).where(
                Job.type == "sweep_parent_narratives", Job.status == JobStatus.pending
            )
        )
    assert successor is not None, "a failing sweep must not take the schedule with it"


# --------------------------------------------------------------------------- #
# `_aware` — the naive/aware SQLite-vs-Postgres shim.
# --------------------------------------------------------------------------- #


def test_aware_passes_none_through():
    assert _aware(None) is None


def test_aware_stamps_a_naive_datetime_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    result = _aware(naive)
    assert result.tzinfo is timezone.utc
    assert result.replace(tzinfo=None) == naive


def test_aware_leaves_an_already_aware_datetime_unchanged():
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _aware(aware) is aware


# --------------------------------------------------------------------------- #
# enqueue_narratives_for_group — "Prepare again", D2's correction mechanism.
# --------------------------------------------------------------------------- #


async def test_enqueue_narratives_for_group_forces_the_class_and_every_member(world):
    async with async_session() as session:
        await enqueue_narratives_for_group(session, world["group_id"])
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()

    class_jobs = [p for p in payloads if p.get("audience") == "tutor_class"]
    assert len(class_jobs) == 1
    assert class_jobs[0]["group_id"] == world["group_id"]
    assert class_jobs[0]["force"] is True

    parent_jobs = [p for p in payloads if p.get("audience") == "parent_student"]
    assert len(parent_jobs) == 1
    assert parent_jobs[0]["student_id"] == world["student_id"]
    assert parent_jobs[0]["force"] is True


async def test_enqueue_narratives_for_group_is_a_noop_when_the_kill_switch_is_off(
    world, monkeypatch
):
    monkeypatch.setattr(get_settings(), "narrative_enabled", False)
    async with async_session() as session:
        await enqueue_narratives_for_group(session, world["group_id"])
        await session.commit()

    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Job.id)).where(Job.type == "generate_narrative")
        )
    assert count == 0


async def test_enqueue_narratives_for_group_with_no_members_enqueues_only_the_class_job(
    client, tutor, world
):
    """A class with nobody enrolled yet still gets a class narrative refresh —
    the loop over students degrades to zero parent jobs, not an error."""
    empty_group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Empty class", "subject_id": world["subject_id"]},
            headers=tutor["headers"],
        )
    ).json()

    async with async_session() as session:
        await enqueue_narratives_for_group(session, empty_group["id"])
        await session.commit()

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    assert len(payloads) == 1
    assert payloads[0]["audience"] == "tutor_class"
    assert payloads[0]["group_id"] == empty_group["id"]


# --------------------------------------------------------------------------- #
# Config defaults and the sweep interval setting.
# --------------------------------------------------------------------------- #


def test_narrative_settings_have_the_documented_defaults():
    settings = get_settings()
    assert settings.narrative_enabled is True
    assert settings.narrative_parent_max_age_days == 7
    assert settings.narrative_sweep_interval_hours == 24
    assert settings.ai_narrative_provider == "anthropic"
    assert settings.ai_narrative_model == ""


async def test_sweep_reenqueue_honours_the_configured_interval(monkeypatch):
    """The sweep re-arms itself the configured number of hours out, not a
    hardcoded 24 — narrative_sweep_interval_hours actually drives run_after."""
    monkeypatch.setattr(get_settings(), "narrative_sweep_interval_hours", 5)
    before = datetime.now(timezone.utc)

    async with async_session() as session:
        await sweep_parent_narratives(session, {})
        await session.commit()

    async with async_session() as session:
        sweep = await session.scalar(
            select(Job).where(
                Job.type == "sweep_parent_narratives", Job.status == JobStatus.pending
            )
        )
    assert sweep is not None, "the sweep must re-arm itself"
    run_after = _aware(sweep.run_after)
    delta = run_after - before
    assert timedelta(hours=4, minutes=59) < delta <= timedelta(hours=5, minutes=1)
