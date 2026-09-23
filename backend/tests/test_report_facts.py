"""build_report_facts reads build_summary_v2 (5.3a Task 2), so a report states
exactly the numbers the student's profile shows."""

import uuid
from datetime import datetime, timedelta, timezone

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
    ReadinessFactor,
    ReadinessSnapshot,
    User,
)
from app.services.reports import build_report_facts
from tests.factories import write_v2_snapshot
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_report_facts_read_v2(tutor, world):  # noqa: F811
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        # A distinctive score on a run that is *not* the latest — proves only
        # the latest run's factor rows are read, not every run for the subject.
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=50.0,
            topics={world["topic1"]: (99.0, FactorConfidence.high)},
            created_at=now - timedelta(days=40),
        )
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=72.0,
            predicted_grade="6",
            topics={
                world["topic1"]: (80.0, FactorConfidence.high),
                world["topic2"]: (45.0, FactorConfidence.high),
            },
            homework=(5, 4),
            created_at=now,
        )
        await session.commit()

        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])

    assert "Overall readiness: 72.0%" in facts
    assert "Weakest topics: Ionic bonding (45%)" in facts  # 45 <= WEAK_THRESHOLD
    assert "Atomic structure" not in facts.split("Weakest topics:")[1]
    assert "Trend: improved" in facts
    assert "Homework: submitted 4 of 5 assignments" in facts
    # The earlier run's distinctive topic score must never surface — only the
    # latest snapshot's evaluation_run_id is read.
    assert "(99%)" not in facts


async def test_report_facts_no_snapshot_says_so(tutor, world):  # noqa: F811
    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])

    assert "No readiness data yet for this subject." in facts


async def test_report_facts_show_homework_line_even_with_no_score(tutor, world):  # noqa: F811
    """A ready, score=None run (no factor had evidence) still persists its
    homework_performance row — completion is a fact independent of the
    missing score (PROD-1), so the homework line must still appear beside
    the "no data" line rather than being swallowed by it."""
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=None,
            homework=(3, 2),
        )
        await session.commit()

        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])

    assert "No readiness data yet for this subject." in facts
    assert "Homework: submitted 2 of 3 assignments" in facts


async def test_report_facts_label_a_topic_that_rests_on_the_tutor_estimate(
    tutor,
    world,  # noqa: F811
):
    """decision 14: self-declared data is labelled wherever it is shown
    (PROD-8, UX-20) — including here, not just on the profile."""
    run_id = str(uuid.uuid4())
    async with async_session() as session:
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id,
                student_id=world["student_id"],
                subject_id=world["subject_id"],
                topic_id=world["topic1"],
                factor=ReadinessFactor.topic_mastery,
                score=40.0,
                confidence=FactorConfidence.low,
                evidence_count=1,
                detail={"tutor_estimate": {"pct": 40.0, "share": 1.0}},
            )
        )
        session.add(
            ReadinessSnapshot(
                evaluation_run_id=run_id,
                student_id=world["student_id"],
                subject_id=world["subject_id"],
                status=AiSynthesisStatus.ready,
                score=40.0,
                predicted_grade=None,
                weak_topics=[],
                rationale="fixture",
                recommended_revision=None,
            )
        )
        await session.commit()

        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])

    assert "Atomic structure (40%, includes tutor estimate)" in facts
