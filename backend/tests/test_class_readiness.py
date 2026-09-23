"""services/class_readiness.py — the one v2 class aggregation shared by the
tutor home strip, the class page, the class cards and Group Analytics
(decisions 13, 15). PERF-1: a fixed number of queries per class, flat in
roster size, whatever the number of classes or learners.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import (
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
    ReadinessFactor,
    Subject,
    Topic,
)
from app.services.class_readiness import class_health, class_readiness
from tests.factories import subject_defaults, write_v2_snapshot


@pytest.fixture
async def subject_id(tutor):  # depends on `tutor` so the organization exists first:
    # without it pytest may build the subject before any account, and
    # `subject_defaults` would fall back to creating a second organization
    # the tutor is not in — every `owned_subject` lookup then 404s.
    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
        )
        session.add(subject)
        await session.flush()
        session.add(Topic(subject_id=subject.id, code="1.3", title="Atoms", weight=1.0))
        await session.commit()
        return subject.id


async def _class_with(client, tutor, subject_id):
    return (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()


async def _student(client, tutor, group_id, name, username):
    return (
        await client.post(
            f"/api/v1/groups/{group_id}/students",
            json={"name": name, "username": username, "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()


async def _snap(student_id: int, subject_id: int, score: float | None, **kwargs) -> None:
    async with async_session() as session:
        await write_v2_snapshot(
            session, student_id=student_id, subject_id=subject_id, score=score, **kwargs
        )
        await session.commit()


async def test_class_score_is_the_mean_of_scored_learners_and_counts_the_rest(
    client, tutor, subject_id
):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    b = await _student(client, tutor, group["id"], "B", "b01")
    c = await _student(client, tutor, group["id"], "C", "c01")
    await _snap(a["id"], subject_id, 80.0)
    await _snap(b["id"], subject_id, 60.0)
    await _snap(c["id"], subject_id, None)  # a no-evidence run: counted, not zeroed
    async with async_session() as session:
        assert (await class_health(session, [group["id"]]))[group["id"]] == (70.0, 2)


async def test_only_the_latest_ready_snapshot_counts(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    now = datetime.now(timezone.utc)
    await _snap(a["id"], subject_id, 30.0, created_at=now - timedelta(days=3))
    await _snap(a["id"], subject_id, 90.0, created_at=now - timedelta(days=1))
    await _snap(a["id"], subject_id, None, status=AiSynthesisStatus.failed, created_at=now)
    async with async_session() as session:
        assert (await class_health(session, [group["id"]]))[group["id"]] == (90.0, 1)


async def test_another_subjects_snapshot_does_not_leak_into_the_class(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    async with async_session() as session:
        other = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add(other)
        await session.commit()
        other_subject_id = other.id
    # Scored, but in a subject this class does not teach.
    await _snap(a["id"], other_subject_id, 95.0)
    async with async_session() as session:
        assert (await class_health(session, [group["id"]]))[group["id"]] == (None, 0)


async def test_class_topic_means_come_from_each_learners_latest_run_only(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    b = await _student(client, tutor, group["id"], "B", "b01")
    c = await _student(client, tutor, group["id"], "C", "c01")
    async with async_session() as session:
        topic_id = await session.scalar(select(Topic.id).where(Topic.subject_id == subject_id))

    now = datetime.now(timezone.utc)
    # Older run says the topic is 10; only A's latest run should count.
    await _snap(
        a["id"],
        subject_id,
        30.0,
        topics={topic_id: (10.0, FactorConfidence.high)},
        created_at=now - timedelta(days=3),
    )
    await _snap(
        a["id"],
        subject_id,
        75.0,
        topics={topic_id: (70.0, FactorConfidence.high)},
        created_at=now - timedelta(days=1),
    )
    await _snap(b["id"], subject_id, 55.0, topics={topic_id: (50.0, FactorConfidence.high)})
    # A low-confidence row in the latest run is excluded.
    await _snap(c["id"], subject_id, 40.0, topics={topic_id: (20.0, FactorConfidence.low)})

    async with async_session() as session:
        detail = await class_readiness(session, group["id"])
    assert len(detail.topic_means) == 1
    mean = detail.topic_means[0]
    assert mean.topic_id == topic_id
    assert mean.avg_score == 60.0  # (70 + 50) / 2
    assert mean.student_count == 2


async def test_homework_completion_is_absent_not_zero_when_the_row_carries_no_counts(
    client, tutor, subject_id
):
    """A homework_performance row can exist with neither count set — the run
    found no assignments to count. That must read as absent, never "0 of 0"
    (PROD-2)."""
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    async with async_session() as session:
        run_id = await write_v2_snapshot(
            session, student_id=a["id"], subject_id=subject_id, score=70.0
        )
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id,
                student_id=a["id"],
                subject_id=subject_id,
                topic_id=None,
                factor=ReadinessFactor.homework_performance,
                score=None,
                confidence=FactorConfidence.no_data,
                evidence_count=0,
                detail={},
            )
        )
        await session.commit()

    async with async_session() as session:
        detail = await class_readiness(session, group["id"])
    assert a["id"] not in detail.homework


async def test_class_readiness_query_count_is_flat_in_roster_size(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    solo = await _student(client, tutor, group["id"], "Solo", "solo01")
    await _snap(solo["id"], subject_id, 70.0)

    def count_queries():
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        return queries, lambda: event.remove(engine.sync_engine, "before_cursor_execute", before)

    queries, stop = count_queries()
    async with async_session() as session:
        await class_readiness(session, group["id"])
    stop()
    baseline = len(queries)

    for i in range(5):
        s = await _student(client, tutor, group["id"], f"S{i}", f"roster{i}")
        await _snap(s["id"], subject_id, 60.0 + i)

    queries, stop = count_queries()
    async with async_session() as session:
        await class_readiness(session, group["id"])
    stop()
    grown = len(queries)

    assert grown == baseline, (
        f"query count grew from {baseline} to {grown} as the roster went 1 -> 6; "
        "class_readiness must not fan out per learner"
    )
