"""Drafting a teaching plan (task 6.3): the AI weights chapters, the scheduler
owns the calendar, and a job writes only the plan's `generated` slots.

Jobs are driven with `process_one_job()` (QA-6) and the model is always faked
(QA-7, QA-8)."""

from datetime import date, datetime, timezone
from datetime import time as dtime

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import (
    AiUsageEvent,
    Chapter,
    Group,
    Job,
    JobStatus,
    Organization,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
    User,
    UserRole,
)
from app.models.ai_usage import AiFeature
from app.services.ai import AIKeyMissingError, AIUnavailableError
from app.services.plan_drafting import (
    PLAN_DRAFT_JOB,
    ChapterAdvice,
    PlanWeightingResult,
    draft_plan_slots,
    enqueue_plan_draft,
)
from app.services.prompts import CHAPTER_LIST_MARKERS, get_prompt
from app.workers.jobs import process_one_job
from tests.factories import make_subject

TODAY = datetime(2027, 1, 4, 9, 0, tzinfo=timezone.utc)  # a Monday
EXAM = date(2027, 2, 1)  # Mon/Thu lessons 4, 7, 11, 14, 18, 21, 25, 28 Jan = 8


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.services.plan_drafting.now_in", lambda tz: TODAY)


@pytest.fixture
async def world():
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
            for i in (1, 2, 3)
        ]
        session.add_all([group, *chapters])
        await session.flush()
        session.add(
            Topic(subject_id=subject.id, chapter_id=chapters[0].id, code="1.1", title="Moles")
        )
        session.add_all(
            ScheduleSlot(
                group_id=group.id, weekday=d, start_time=dtime(17, 0) if d == 0 else dtime(15, 30)
            )
            for d in (0, 3)
        )
        plan = TeachingPlan(
            organization_id=org.id,
            group_id=group.id,
            exam_date=EXAM,
            lessons_per_week=2,
            lesson_minutes=60,
        )
        session.add(plan)
        await session.commit()
        return {
            "org_id": org.id,
            "tutor_id": tutor.id,
            "group_id": group.id,
            "plan_id": plan.id,
            "subject_id": subject.id,
            "chapter_ids": [c.id for c in chapters],
        }


def advice(world, weights, reasons=None):
    return PlanWeightingResult(
        chapters=[
            ChapterAdvice(chapter_id=cid, weight=w, reason=f"reason {cid}")
            for cid, w in zip(world["chapter_ids"], weights, strict=False)
        ]
    )


async def run_job(world) -> Job:
    async with async_session() as session:
        await enqueue_plan_draft(session, world["plan_id"])
        await session.commit()
    assert await process_one_job() is True
    async with async_session() as session:
        return (await session.scalars(select(Job).order_by(Job.id.desc()))).first()


async def slots(world) -> list[PlanSlot]:
    async with async_session() as session:
        return list(
            (
                await session.scalars(
                    select(PlanSlot)
                    .where(PlanSlot.plan_id == world["plan_id"])
                    .order_by(PlanSlot.sequence, PlanSlot.id)
                )
            ).all()
        )


async def draft_result(world):
    async with async_session() as session:
        return (await session.get(TeachingPlan, world["plan_id"])).draft_result


async def set_status(world, status):
    async with async_session() as session:
        plan = await session.get(TeachingPlan, world["plan_id"])
        plan.status = status
        if status is TeachingPlanStatus.accepted:
            plan.accepted_at = TODAY
            plan.accepted_by_id = world["tutor_id"]
        await session.commit()


def test_handler_is_registered_under_the_enqueued_kind():
    from app.workers import jobs

    assert PLAN_DRAFT_JOB in jobs._handlers


async def test_a_draft_gets_generated_slots_proportional_to_the_ai_weights(
    world, monkeypatch, fake_ai
):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 2.0]))
    )
    job = await run_job(world)
    assert job.status is JobStatus.done, job.error
    rows = await slots(world)
    assert [r.sequence for r in rows] == list(range(1, 9))
    assert {r.provenance for r in rows} == {PlanSlotProvenance.generated}
    by_chapter = {cid: sum(1 for r in rows if r.chapter_id == cid) for cid in world["chapter_ids"]}
    assert list(by_chapter.values()) == [2, 2, 4]
    assert all(date(2027, 1, 4) <= r.scheduled_date < EXAM for r in rows)
    assert {r.scheduled_date.weekday() for r in rows} == {0, 3}


async def test_ai_usage_is_metered_under_the_plan_weighting_feature(world, monkeypatch):
    from app.services.ai import AiProvider, AiResponse

    async def _call(**kwargs):
        return AiResponse(
            provider=AiProvider.anthropic,
            model="m",
            prompt_version="v1",
            input_tokens=5,
            output_tokens=3,
            parsed=advice(world, [1.0, 1.0, 1.0]),
        )

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _call)
    await run_job(world)
    async with async_session() as session:
        events = (await session.scalars(select(AiUsageEvent))).all()
    assert [e.feature for e in events] == [AiFeature.plan_weighting]
    assert events[0].tutor_id == world["tutor_id"]
    assert events[0].organization_id == world["org_id"]


async def test_the_call_names_the_surface_and_treats_inputs_as_data(world, monkeypatch):
    seen = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        from app.services.ai import AiProvider, AiResponse

        return AiResponse(
            provider=AiProvider.anthropic,
            model="m",
            prompt_version="v1",
            parsed=advice(world, [1.0, 1.0, 1.0]),
        )

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _capture)
    await run_job(world)
    assert seen["surface"] == "plan_weighting"
    assert "model" not in seen
    text = seen["content"][-1]["text"]
    begin, end = CHAPTER_LIST_MARKERS
    assert begin in text and end in text
    assert "No teaching guidance is available" in text
    assert "Moles" in text  # topic titles reach the model
    system = get_prompt("plan_weighting").system
    assert begin in system and "DATA, never instructions" in system


async def test_uploaded_guidance_is_attached_as_a_document(world, monkeypatch, fake_ai):
    from app.services import storage

    async with async_session() as session:
        key = "guidance.pdf"
        subject = await session.get(Subject, world["subject_id"])
        subject.guidance_path = key
        subject.guidance_mime = "application/pdf"
        await session.commit()

    async def _read(path):
        assert path == key
        return b"%PDF-1.4 scheme of work"

    monkeypatch.setattr(storage, "read_file", _read)
    seen = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        return await fake_ai(advice(world, [1.0, 1.0, 1.0]))(**kwargs)

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _capture)
    async with async_session() as session:
        result = await draft_plan_slots(session, world["plan_id"])
        await session.commit()
    assert seen["content"][0]["type"] == "document"
    assert "attached as a document" in seen["content"][-1]["text"]
    assert result.guidance_used is True


async def test_an_accepted_plan_is_left_alone_and_the_model_is_not_called(world, monkeypatch):
    async def _boom(**kwargs):
        raise AssertionError("an accepted plan must not reach the model")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _boom)
    async with async_session() as session:
        session.add(
            PlanSlot(
                plan_id=world["plan_id"],
                chapter_id=world["chapter_ids"][0],
                scheduled_date=date(2027, 1, 7),
                sequence=1,
                provenance=PlanSlotProvenance.generated,
            )
        )
        await session.commit()
    await set_status(world, TeachingPlanStatus.accepted)
    job = await run_job(world)
    assert job.status is JobStatus.done
    rows = await slots(world)
    assert len(rows) == 1 and rows[0].scheduled_date == date(2027, 1, 7)


async def test_a_plan_that_is_gone_finishes_quietly(world, monkeypatch):
    async with async_session() as session:
        await enqueue_plan_draft(session, 99999)
        await session.commit()
    assert await process_one_job() is True
    async with async_session() as session:
        job = (await session.scalars(select(Job))).one()
    assert job.status is JobStatus.done


async def test_rerunning_the_job_gives_the_same_slots_not_duplicates(world, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 2.0, 1.0]))
    )
    await run_job(world)
    first = [(r.chapter_id, r.scheduled_date, r.sequence) for r in await slots(world)]
    await run_job(world)
    second = [(r.chapter_id, r.scheduled_date, r.sequence) for r in await slots(world)]
    assert len(first) == 8
    assert second == first


async def test_hand_edited_and_settled_slots_survive_a_redraft(world, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    await run_job(world)
    kept = {
        PlanSlotProvenance.manually_modified: date(2027, 1, 7),
        PlanSlotProvenance.confirmed: date(2027, 1, 14),
        PlanSlotProvenance.completed: date(2027, 1, 21),
    }
    async with async_session() as session:
        for provenance, day in kept.items():
            row = await session.scalar(
                select(PlanSlot).where(
                    PlanSlot.plan_id == world["plan_id"], PlanSlot.scheduled_date == day
                )
            )
            row.provenance = provenance
            row.chapter_id = world["chapter_ids"][2]
        await session.commit()
    protected = {
        r.id: (r.scheduled_date, r.chapter_id) for r in await slots(world) if r.provenance in kept
    }
    assert len(protected) == 3

    await run_job(world)
    after = await slots(world)
    survivors = {r.id: (r.scheduled_date, r.chapter_id) for r in after if r.id in protected}
    assert survivors == protected
    assert {r.provenance for r in after if r.id in protected} == set(kept)
    # The generator does not double-book a date a tutor's slot occupies.
    generated = [r for r in after if r.provenance is PlanSlotProvenance.generated]
    assert not {r.scheduled_date for r in generated} & set(kept.values())
    assert len({r.scheduled_date for r in generated}) == len(generated)
    # One run of numbers across kept and generated slots, in calendar order.
    assert [r.sequence for r in after] == list(range(1, len(after) + 1))
    assert [r.scheduled_date for r in after] == sorted(r.scheduled_date for r in after)
    assert len(after) == 8
    # The tutor's three slots all sit on chapter 3, which covers its whole share:
    # the generator adds none on top.
    assert [r for r in generated if r.chapter_id == world["chapter_ids"][2]] == []


async def test_breaks_are_honoured(world, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    async with async_session() as session:
        session.add(
            PlanBreak(
                plan_id=world["plan_id"],
                start_date=date(2027, 1, 11),
                end_date=date(2027, 1, 18),
                label="Half term",
            )
        )
        await session.commit()
    await run_job(world)
    dates = {r.scheduled_date for r in await slots(world)}
    assert not {date(2027, 1, 11), date(2027, 1, 14), date(2027, 1, 18)} & dates
    assert len(dates) == 5


async def test_ai_weights_are_clamped_unknown_ids_ignored_and_missing_defaulted(
    world, monkeypatch, fake_ai
):
    c1, c2, c3 = world["chapter_ids"]
    result = PlanWeightingResult(
        chapters=[
            ChapterAdvice(chapter_id=c1, weight=99.0, reason="huge"),
            ChapterAdvice(chapter_id=c2, weight=-4.0, reason="negative"),
            ChapterAdvice(chapter_id=424242, weight=3.0, reason="not a chapter"),
            ChapterAdvice(chapter_id=c1, weight=0.5, reason="repeat, ignored"),
            # c3 omitted
        ]
    )
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", fake_ai(result))
    async with async_session() as session:
        out = await draft_plan_slots(session, world["plan_id"])
        await session.commit()
    assert out.weights == {c1: 3.0, c2: 0.5, c3: 1.0}
    assert out.clamped_chapters == 2
    assert out.defaulted_chapters == 1
    assert 424242 not in out.weights
    assert out.reasons[c1] == "huge"
    assert out.weight_source == "ai"
    assert out.slots_written == 8


async def test_a_nan_weight_counts_as_missing(world, monkeypatch, fake_ai):
    c1 = world["chapter_ids"][0]
    result = PlanWeightingResult(
        chapters=[ChapterAdvice(chapter_id=c1, weight=float("nan"), reason="?")]
    )
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", fake_ai(result))
    async with async_session() as session:
        out = await draft_plan_slots(session, world["plan_id"])
    assert out.weights[c1] == 1.0
    assert out.defaulted_chapters == 3


async def test_a_missing_api_key_falls_back_to_stored_weights_and_says_so(world, monkeypatch):
    # The real structured_complete, with the key blanked: it raises before any
    # network call, which is exactly the degraded path (AI-20, INF-9).
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    async with async_session() as session:
        for cid, weight in zip(world["chapter_ids"], (1.0, 1.0, 2.0), strict=True):
            (await session.get(Chapter, cid)).weight = weight
        await session.commit()
    async with async_session() as session:
        out = await draft_plan_slots(session, world["plan_id"])
        await session.commit()
    assert out.weight_source == "stored_chapter_weights"
    assert "ANTHROPIC_API_KEY" in (out.degraded_reason or "")
    assert out.slots_written == 8
    rows = await slots(world)
    counts = [sum(1 for r in rows if r.chapter_id == cid) for cid in world["chapter_ids"]]
    assert counts == [2, 2, 4]
    async with async_session() as session:
        assert (await session.scalars(select(AiUsageEvent))).all() == []


async def test_a_missing_key_does_not_fail_the_job(world, monkeypatch):
    async def _unavailable(**kwargs):
        raise AIKeyMissingError("AI is not configured: set ANTHROPIC_API_KEY")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _unavailable)
    job = await run_job(world)
    assert job.status is JobStatus.done
    assert len(await slots(world)) == 8
    result = await draft_result(world)
    assert result["status"] == "drafted"
    assert result["weight_source"] == "stored_chapter_weights"
    assert "ANTHROPIC_API_KEY" in result["degraded_reason"]


async def test_a_misrouted_provider_is_not_mistaken_for_a_missing_key(world, monkeypatch):
    """A missing SDK or a bad route is a deployment fault: it must fail loudly, not
    quietly produce an unweighted plan."""

    async def _no_sdk(**kwargs):
        raise AIUnavailableError("The google-genai package is not installed")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _no_sdk)
    job = await run_job(world)
    assert job.status is JobStatus.pending
    assert "google-genai" in (job.error or "")
    assert await slots(world) == []


async def test_a_provider_failure_fails_the_job_and_writes_nothing(world, monkeypatch):
    async def _down(**kwargs):
        raise RuntimeError("provider returned 529")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _down)
    job = await run_job(world)
    assert job.status is JobStatus.pending  # first attempt: retried
    assert "529" in (job.error or "")
    assert await slots(world) == []


async def test_too_few_lessons_is_recorded_without_a_retry_and_skips_the_model(world, monkeypatch):
    async def _boom(**kwargs):
        raise AssertionError("the model must not be called for a plan that cannot fit")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _boom)
    async with async_session() as session:
        plan = await session.get(TeachingPlan, world["plan_id"])
        plan.exam_date = date(2027, 1, 8)  # Mon 4th and Thu 7th only: 2 lessons, 3 chapters
        await session.commit()
    job = await run_job(world)
    assert job.status is JobStatus.done  # deterministic: a retry cannot help
    assert job.attempts == 1 and job.error is None
    result = await draft_result(world)
    assert result["status"] == "failed"
    assert result["failure"]["code"] == "not_enough_lessons"
    assert (result["failure"]["lessons"], result["failure"]["chapters"]) == (2, 3)
    assert "2 lesson" in result["failure"]["message"]
    assert await slots(world) == []


async def test_too_few_lessons_leaves_existing_generated_slots_in_place(
    world, monkeypatch, fake_ai
):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    await run_job(world)
    before = len(await slots(world))
    async with async_session() as session:
        (await session.get(TeachingPlan, world["plan_id"])).exam_date = date(2027, 1, 5)
        await session.commit()
    job = await run_job(world)
    assert job.status is JobStatus.done
    assert (await draft_result(world))["status"] == "failed"
    assert len(await slots(world)) == before


async def test_a_subject_without_chapters_is_recorded_as_a_failure(world):
    async with async_session() as session:
        for chapter in (await session.scalars(select(Chapter))).all():
            for topic in (
                await session.scalars(select(Topic).where(Topic.chapter_id == chapter.id))
            ).all():
                await session.delete(topic)
            await session.delete(chapter)
        await session.commit()
    job = await run_job(world)
    assert job.status is JobStatus.done
    result = await draft_result(world)
    assert result["status"] == "failed"
    assert result["failure"]["code"] == "no_chapters"
    assert "no chapters" in result["failure"]["message"]


async def test_draft_result_is_null_until_a_plan_is_drafted(world):
    assert await draft_result(world) is None


async def test_draft_result_records_weights_reasons_and_provenance(world, monkeypatch, fake_ai):
    c1, c2, c3 = world["chapter_ids"]
    result = PlanWeightingResult(
        chapters=[
            ChapterAdvice(chapter_id=c1, weight=2.0, reason="dense"),
            ChapterAdvice(chapter_id=c2, weight=99.0, reason="r" * 500),
        ]
    )
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", fake_ai(result))
    await run_job(world)
    stored = await draft_result(world)
    assert stored["status"] == "drafted"
    assert stored["weight_source"] == "ai"
    assert stored["degraded_reason"] is None
    assert stored["guidance_used"] is False
    assert stored["defaulted_chapters"] == 1 and stored["clamped_chapters"] == 1
    assert stored["failure"] is None
    assert stored["drafted_at"]
    by_id = {c["chapter_id"]: c for c in stored["chapters"]}
    assert by_id[c1] == {"chapter_id": c1, "weight": 2.0, "reason": "dense"}
    assert by_id[c2]["weight"] == 3.0 and len(by_id[c2]["reason"]) == 300
    assert by_id[c3] == {"chapter_id": c3, "weight": 1.0, "reason": None}


async def test_a_very_long_reason_still_parses_drafts_and_is_stored_truncated(
    world, monkeypatch, fake_ai
):
    c1 = world["chapter_ids"][0]
    # Validated through the schema, as a real provider reply would be.
    reply = PlanWeightingResult.model_validate(
        {"chapters": [{"chapter_id": c1, "weight": 2.0, "reason": "y" * 2000}]}
    )
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", fake_ai(reply))
    job = await run_job(world)
    assert job.status is JobStatus.done
    stored = await draft_result(world)
    assert stored["status"] == "drafted"
    by_id = {c["chapter_id"]: c for c in stored["chapters"]}
    assert by_id[c1]["reason"] == "y" * 300
    assert len(await slots(world)) == 8


async def test_a_real_chapter_listed_late_is_still_read_but_processing_stops_when_all_answered(
    world, monkeypatch, fake_ai
):
    c1, c2, c3 = world["chapter_ids"]
    entries = [
        ChapterAdvice(chapter_id=c1, weight=1.0, reason="a"),
        ChapterAdvice(chapter_id=c1, weight=1.0, reason="dup"),
        ChapterAdvice(chapter_id=424242, weight=1.0, reason="invented"),
        ChapterAdvice(chapter_id=c2, weight=1.0, reason="b"),
        ChapterAdvice(chapter_id=c3, weight=3.0, reason="late but real"),
        ChapterAdvice(chapter_id=c1, weight=0.5, reason="after everything was answered"),
    ]
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete",
        fake_ai(PlanWeightingResult(chapters=entries)),
    )
    await run_job(world)
    stored = await draft_result(world)
    by_id = {c["chapter_id"]: c for c in stored["chapters"]}
    assert by_id[c3] == {"chapter_id": c3, "weight": 3.0, "reason": "late but real"}
    assert by_id[c1]["reason"] == "a"
    assert stored["defaulted_chapters"] == 0


async def test_the_timetable_is_re_read_after_the_ai_call(world, monkeypatch, fake_ai):
    """A timetable edited while the model is thinking is the one scheduled."""
    good = fake_ai(advice(world, [1.0, 1.0, 1.0]))

    async def _edit_then_answer(**kwargs):
        async with async_session() as other:
            for slot in (await other.scalars(select(ScheduleSlot))).all():
                slot.weekday = 1  # Tuesday only now
            await other.commit()
        return await good(**kwargs)

    async with async_session() as session:
        for slot in (await session.scalars(select(ScheduleSlot))).all():
            if slot.weekday == 3:
                await session.delete(slot)
        (await session.get(TeachingPlan, world["plan_id"])).lessons_per_week = 1
        await session.commit()
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _edit_then_answer)
    await run_job(world)
    assert {r.scheduled_date.weekday() for r in await slots(world)} == {1}


async def test_an_answer_naming_no_real_chapter_is_recorded_as_unusable_not_ai(
    world, monkeypatch, fake_ai
):
    result = PlanWeightingResult(
        chapters=[ChapterAdvice(chapter_id=424242, weight=3.0, reason="invented")]
    )
    monkeypatch.setattr("app.services.plan_drafting.structured_complete", fake_ai(result))
    job = await run_job(world)
    assert job.status is JobStatus.done
    stored = await draft_result(world)
    assert stored["weight_source"] == "ai_unusable"
    assert "none of this subject's chapters" in stored["degraded_reason"]
    assert stored["defaulted_chapters"] == 3
    assert {c["reason"] for c in stored["chapters"]} == {None}
    assert len(await slots(world)) == 8


async def test_an_unreadable_guidance_file_is_recorded_and_not_used(world, monkeypatch, fake_ai):
    from app.services import storage

    async with async_session() as session:
        subject = await session.get(Subject, world["subject_id"])
        subject.guidance_path = "gone.pdf"
        subject.guidance_mime = "application/pdf"
        await session.commit()

    async def _missing(path):
        raise storage.ObjectNotFoundError(path)

    monkeypatch.setattr(storage, "read_file", _missing)
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    await run_job(world)
    stored = await draft_result(world)
    assert stored["guidance_used"] is False
    assert "could not be read" in stored["guidance_note"]
    assert stored["status"] == "drafted"


async def test_usage_survives_a_failure_after_the_ai_call(world, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )

    def _explode(spec):
        raise RuntimeError("scheduler blew up")

    monkeypatch.setattr("app.services.plan_drafting.schedule", _explode)
    job = await run_job(world)
    assert "scheduler blew up" in (job.error or "")
    assert await slots(world) == []
    async with async_session() as session:
        events = (await session.scalars(select(AiUsageEvent))).all()
    assert [e.feature for e in events] == [AiFeature.plan_weighting]


@pytest.mark.parametrize(
    ("per_week", "expected"),
    [(2, {0, 3}), (1, {0}), (3, {0, 2, 3})],
)
async def test_the_tutors_lessons_per_week_wins_over_the_timetable(
    world, monkeypatch, fake_ai, per_week, expected
):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    async with async_session() as session:
        (await session.get(TeachingPlan, world["plan_id"])).lessons_per_week = per_week
        await session.commit()
    job = await run_job(world)
    assert job.status is JobStatus.done
    assert {r.scheduled_date.weekday() for r in await slots(world)} == expected


async def test_an_empty_timetable_uses_lessons_per_week(world, monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    async with async_session() as session:
        for slot in (await session.scalars(select(ScheduleSlot))).all():
            await session.delete(slot)
        (await session.get(TeachingPlan, world["plan_id"])).lessons_per_week = 3
        await session.commit()
    await run_job(world)
    assert {r.scheduled_date.weekday() for r in await slots(world)} == {0, 2, 4}


async def test_the_plan_accepted_during_the_ai_call_is_not_rewritten(world, monkeypatch, fake_ai):
    """The tutor accepts while the model is thinking: the run discards itself."""
    good = fake_ai(advice(world, [1.0, 1.0, 1.0]))

    async def _accept_then_answer(**kwargs):
        async with async_session() as other:
            plan = await other.get(TeachingPlan, world["plan_id"])
            plan.status = TeachingPlanStatus.accepted
            plan.accepted_at = TODAY
            plan.accepted_by_id = world["tutor_id"]
            await other.commit()
        return await good(**kwargs)

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", _accept_then_answer)
    async with async_session() as session:
        out = await draft_plan_slots(session, world["plan_id"])
        await session.commit()
    assert out.skipped
    assert await slots(world) == []


async def test_generated_slots_take_their_start_time_from_the_weekly_timetable(
    world, monkeypatch, fake_ai
):
    """AV-119: each planned lesson stores its own start time, defaulted from the
    timetable for its weekday (here Mon and Thu at 17:00)."""
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    job = await run_job(world)
    assert job.status is JobStatus.done, job.error
    rows = await slots(world)
    assert rows
    for r in rows:  # Monday 17:00, Thursday 15:30: per row, not one value for all
        assert r.start_time == (dtime(17, 0) if r.scheduled_date.weekday() == 0 else dtime(15, 30))
