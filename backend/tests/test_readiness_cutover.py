"""WS5: Readiness v2 is what the live readiness API serves — with a v1
fallback, an honest "updating" state, and tutor-editable factor weights."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
    Job,
    JobStatus,
    ReadinessFactor,
    ReadinessSnapshot,
    ReadinessWeights,
)
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def _write_snapshot(
    world,  # noqa: F811
    *,
    score: float = 72.0,
    status: AiSynthesisStatus = AiSynthesisStatus.ready,
    topic_score: float | None = 55.0,
    created_at: datetime | None = None,
) -> str:
    """A completed v2 evaluation run: the deterministic factor rows plus the
    AI synthesis that was built from them, sharing one evaluation_run_id."""
    run_id = str(uuid.uuid4())
    async with async_session() as session:
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id,
                student_id=world["student_id"],
                subject_id=world["subject_id"],
                topic_id=world["topic1"],
                factor=ReadinessFactor.topic_mastery,
                score=topic_score,
                confidence=(
                    FactorConfidence.no_data if topic_score is None else FactorConfidence.high
                ),
                evidence_count=0 if topic_score is None else 4,
                detail={},
            )
        )
        session.add(
            ReadinessSnapshot(
                evaluation_run_id=run_id,
                student_id=world["student_id"],
                subject_id=world["subject_id"],
                status=status,
                score=score,
                predicted_grade="6",
                weak_topics=[{"topic_id": world["topic1"], "reason": "Weak on bonding"}],
                rationale="Homework performance is carrying the score.",
                recommended_revision="Two past paper questions on bonding.",
                **({"created_at": created_at} if created_at else {}),
            )
        )
        await session.commit()
    return run_id


async def test_readiness_is_served_from_the_v2_snapshot(client, tutor, world):  # noqa: F811
    await _write_snapshot(world)
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    subject = resp.json()["subjects"][0]
    assert subject["engine"] == "v2"
    assert subject["score"] == 72.0
    assert subject["predicted_grade"] == "6"
    assert subject["rationale"].startswith("Homework performance")
    assert subject["recommended_revision"]
    # The per-topic bars come from the same run as the headline score.
    assert subject["topics"][0]["topic_id"] == world["topic1"]
    assert subject["topics"][0]["score"] == 55.0
    assert subject["weak_topics"][0]["topic_id"] == world["topic1"]


async def test_the_newest_ready_snapshot_wins(client, tutor, world):  # noqa: F811
    now = datetime.now(timezone.utc)
    await _write_snapshot(world, score=40.0, created_at=now - timedelta(days=2))
    await _write_snapshot(world, score=80.0, created_at=now)
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["score"] == 80.0


async def test_a_failed_synthesis_is_not_served_as_a_score(client, tutor, world):  # noqa: F811
    """A failed run must not present itself as a result — the app falls back to
    v1 rather than showing a blank or a fabricated number."""
    await _write_snapshot(world, score=None, status=AiSynthesisStatus.failed)
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["engine"] == "v1"


async def test_falls_back_to_v1_when_v2_has_never_run(client, tutor, world):  # noqa: F811
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    subject = resp.json()["subjects"][0]
    assert subject["engine"] == "v1"
    assert subject["rationale"] is None


async def test_a_no_data_topic_is_omitted_rather_than_scored_zero(client, tutor, world):  # noqa: F811
    await _write_snapshot(world, topic_score=None)
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["topics"] == []


async def test_a_queued_recompute_marks_the_score_as_updating(client, tutor, world):  # noqa: F811
    """Rather than serving a stale score as if it were current."""
    await _write_snapshot(world)
    async with async_session() as session:
        session.add(
            Job(
                type="compute_readiness_v2",
                payload={
                    "student_id": world["student_id"],
                    "subject_id": world["subject_id"],
                },
                status=JobStatus.pending,
                run_after=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    subject = resp.json()["subjects"][0]
    assert subject["is_updating"] is True
    assert subject["score"] == 72.0, "the last known score is still shown"


async def test_a_whole_student_recompute_marks_every_subject_updating(
    client, tutor, world  # noqa: F811
):
    await _write_snapshot(world)
    async with async_session() as session:
        session.add(
            Job(
                type="compute_readiness_v2",
                payload={"student_id": world["student_id"], "subject_id": None},
                status=JobStatus.pending,
            )
        )
        await session.commit()
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["is_updating"] is True


async def test_a_finished_recompute_does_not_mark_the_score_updating(
    client, tutor, world  # noqa: F811
):
    await _write_snapshot(world)
    async with async_session() as session:
        session.add(
            Job(
                type="compute_readiness_v2",
                payload={
                    "student_id": world["student_id"],
                    "subject_id": world["subject_id"],
                },
                status=JobStatus.done,
            )
        )
        await session.commit()
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["is_updating"] is False


async def test_another_students_recompute_does_not_leak(client, tutor, world):  # noqa: F811
    await _write_snapshot(world)
    async with async_session() as session:
        session.add(
            Job(
                type="compute_readiness_v2",
                payload={"student_id": 99999, "subject_id": world["subject_id"]},
                status=JobStatus.pending,
            )
        )
        await session.commit()
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["is_updating"] is False


async def test_the_trend_reads_v2_snapshots(client, tutor, world):  # noqa: F811
    now = datetime.now(timezone.utc)
    await _write_snapshot(world, score=50.0, created_at=now - timedelta(days=7))
    await _write_snapshot(world, score=65.0, created_at=now)
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/trend", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    points = resp.json()[0]["points"]
    assert [p["score"] for p in points] == [50.0, 65.0]


# ---- Factor weights ----


async def test_weights_default_to_the_model_defaults(client, tutor):
    resp = await client.get("/api/v1/readiness/weights", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_topic_mastery"] == 1.0
    assert body["weight_consistency"] == 1.0
    assert body["half_life_days"] == 45.0


async def test_saving_weights_persists_them(client, tutor):
    payload = {
        "weight_topic_mastery": 2.0,
        "weight_past_paper_performance": 2.5,
        "weight_homework_performance": 1.0,
        "weight_assessment_performance": 1.5,
        "weight_syllabus_coverage": 0.5,
        "weight_mistake_analysis": 1.0,
        "weight_consistency": 0.0,
        "half_life_days": 30.0,
    }
    resp = await client.put(
        "/api/v1/readiness/weights", json=payload, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["weight_past_paper_performance"] == 2.5

    again = await client.get("/api/v1/readiness/weights", headers=tutor["headers"])
    assert again.json()["weight_consistency"] == 0.0
    async with async_session() as session:
        rows = (await session.scalars(select(ReadinessWeights))).all()
        assert len(rows) == 1, "the org's weights are upserted, not duplicated"


async def test_saving_weights_recomputes_the_tutors_students(client, tutor, world):  # noqa: F811
    """Otherwise the sliders would look like they did nothing until the next
    piece of evidence arrived."""
    payload = {
        "weight_topic_mastery": 2.0,
        "weight_past_paper_performance": 1.0,
        "weight_homework_performance": 1.0,
        "weight_assessment_performance": 1.0,
        "weight_syllabus_coverage": 1.0,
        "weight_mistake_analysis": 1.0,
        "weight_consistency": 1.0,
        "half_life_days": 45.0,
    }
    await client.put("/api/v1/readiness/weights", json=payload, headers=tutor["headers"])
    async with async_session() as session:
        jobs = (
            await session.scalars(
                select(Job).where(Job.type == "compute_readiness_v2")
            )
        ).all()
        assert len(jobs) == 1
        assert jobs[0].payload["student_id"] == world["student_id"]


async def test_weights_reject_out_of_range_values(client, tutor):
    resp = await client.put(
        "/api/v1/readiness/weights",
        json={
            "weight_topic_mastery": 99.0,
            "weight_past_paper_performance": 1.0,
            "weight_homework_performance": 1.0,
            "weight_assessment_performance": 1.0,
            "weight_syllabus_coverage": 1.0,
            "weight_mistake_analysis": 1.0,
            "weight_consistency": 1.0,
            "half_life_days": 45.0,
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_students_cannot_read_or_change_the_weights(client, tutor, world):  # noqa: F811
    headers = world["student_headers"]
    assert (
        await client.get("/api/v1/readiness/weights", headers=headers)
    ).status_code == 403
    assert (
        await client.put(
            "/api/v1/readiness/weights",
            json={
                "weight_topic_mastery": 3.0,
                "weight_past_paper_performance": 1.0,
                "weight_homework_performance": 1.0,
                "weight_assessment_performance": 1.0,
                "weight_syllabus_coverage": 1.0,
                "weight_mistake_analysis": 1.0,
                "weight_consistency": 1.0,
                "half_life_days": 45.0,
            },
            headers=headers,
        )
    ).status_code == 403


async def test_a_student_sees_their_own_v2_readiness(client, tutor, world):  # noqa: F811
    await _write_snapshot(world)
    resp = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    assert resp.status_code == 200
    subject = resp.json()["subjects"][0]
    assert subject["engine"] == "v2"
    assert subject["score"] == 72.0
