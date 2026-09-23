"""build_report_facts reads build_summary_v2 (5.3a Task 2), so a report states
exactly the numbers the student's profile shows."""

from datetime import datetime, timedelta, timezone

from app.db import async_session
from app.models import FactorConfidence, User
from app.services.reports import build_report_facts
from tests.factories import write_v2_snapshot
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_report_facts_read_v2(tutor, world):  # noqa: F811
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=50.0,
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


async def test_report_facts_no_snapshot_says_so(tutor, world):  # noqa: F811
    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])

    assert "No readiness data yet for this subject." in facts
