"""The tutor-set weak-topic threshold (task 5.6, decisions 8 and 10).

A weak topic is deterministic: a Topic Mastery row from the snapshot's own run
with a score, confidence better than no_data, and a score at or below the
threshold resolved for (organization, subject) — lowest first, top five. The
AI no longer picks them, and they are derived at read time, so changing the
threshold changes what is shown with no recompute and no new snapshot.
"""

from sqlalchemy import func, select, update

from app.db import async_session
from app.models import (
    FactorConfidence,
    Job,
    ReadinessSnapshot,
    ReadinessWeights,
    Topic,
    User,
    UserRole,
)
from app.services.prompts import PROMPTS
from app.services.readiness_config import resolve_readiness_config
from app.services.readiness_v2_ai import ReadinessSynthesis, compute_readiness_v2
from app.services.reports import build_report_facts
from tests.factories import other_org_subject, write_v2_snapshot
from tests.test_readiness_api import world  # noqa: F401 - shared fixture
from tests.test_readiness_config import _body


async def _org(world) -> int:  # noqa: F811
    async with async_session() as session:
        return (await session.get(User, world["student_id"])).organization_id


async def _add_topics(world, *codes: str) -> list[int]:  # noqa: F811
    async with async_session() as session:
        topics = [
            Topic(subject_id=world["subject_id"], code=c, title=f"Topic {c}", weight=1.0)
            for c in codes
        ]
        session.add_all(topics)
        await session.commit()
        return [t.id for t in topics]


async def _snapshot(world, topics) -> None:  # noqa: F811
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=55.0,
            topics=topics,
        )
        await session.commit()


async def _weak_ids(client, tutor, world) -> list[int]:  # noqa: F811
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    return [t["topic_id"] for t in resp.json()["subjects"][0]["weak_topics"]]


async def _count(model) -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count()).select_from(model))


# ---- The resolver ----


async def test_threshold_resolves_subject_then_account_then_default(client, tutor, world):  # noqa: F811
    org = await _org(world)
    async with async_session() as session:
        assert (
            await resolve_readiness_config(session, org, world["subject_id"])
        ).weak_threshold == 60.0
        session.add(
            ReadinessWeights(organization_id=org, tutor_id=tutor["user"]["id"], weak_threshold=40.0)
        )
        await session.commit()
        assert (
            await resolve_readiness_config(session, org, world["subject_id"])
        ).weak_threshold == 40.0
        # Whole-row override: the subject row never set a threshold, so it is
        # its own default — not the account row's 40 (decision 8).
        session.add(
            ReadinessWeights(
                organization_id=org, subject_id=world["subject_id"], tutor_id=tutor["user"]["id"]
            )
        )
        await session.commit()
        assert (
            await resolve_readiness_config(session, org, world["subject_id"])
        ).weak_threshold == 60.0


# ---- The student's summary ----


async def test_weak_topics_are_scored_topics_at_or_below_the_threshold(client, tutor, world):  # noqa: F811
    at, above, low, no_data = await _add_topics(world, "2.1", "2.2", "2.3", "2.4")
    await _snapshot(
        world,
        {
            at: (60.0, FactorConfidence.high),
            above: (60.1, FactorConfidence.high),
            low: (20.0, FactorConfidence.low),
            no_data: (None, FactorConfidence.no_data),
        },
    )
    assert await _weak_ids(client, tutor, world) == [low, at]


async def test_weak_topics_are_capped_at_five_lowest_first(client, tutor, world):  # noqa: F811
    ids = await _add_topics(world, "3.1", "3.2", "3.3", "3.4", "3.5", "3.6")
    await _snapshot(world, {tid: (50.0 - i, FactorConfidence.high) for i, tid in enumerate(ids)})
    assert await _weak_ids(client, tutor, world) == list(reversed(ids))[:5]


async def test_the_stored_ai_list_is_ignored(client, tutor, world):  # noqa: F811
    """Old snapshots carry the AI's picks; since 5.6 nothing reads them."""
    await _snapshot(world, {world["topic1"]: (90.0, FactorConfidence.high)})
    async with async_session() as session:
        await session.execute(
            update(ReadinessSnapshot).values(
                weak_topics=[
                    {"topic_id": world["topic1"], "topic_title": "x", "reason": "AI said so"},
                    {"topic_id": world["topic2"], "topic_title": "y", "reason": "no row"},
                ]
            )
        )
        await session.commit()
    assert await _weak_ids(client, tutor, world) == []
    resp = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["subjects"][0]["weak_topics"] == []


async def test_changing_the_threshold_changes_weak_topics_without_a_recompute(
    client,
    tutor,
    world,  # noqa: F811
):
    await _snapshot(world, {world["topic1"]: (70.0, FactorConfidence.high)})
    assert await _weak_ids(client, tutor, world) == []
    jobs, snapshots = await _count(Job), await _count(ReadinessSnapshot)

    resp = await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(weak_threshold=75),
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["weak_threshold"] == 75.0

    assert await _weak_ids(client, tutor, world) == [world["topic1"]]
    assert await _count(Job) == jobs
    assert await _count(ReadinessSnapshot) == snapshots
    # The raw v2 surface agrees, and carries the score instead of an AI reason.
    resp = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.json()["subjects"][0]["weak_topics"] == [
        {"topic_id": world["topic1"], "topic_title": "Atomic structure", "score": 70.0}
    ]


async def test_report_facts_use_the_resolved_threshold(client, tutor, world):  # noqa: F811
    await _snapshot(world, {world["topic2"]: (45.0, FactorConfidence.high)})
    await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(weak_threshold=40),
        headers=tutor["headers"],
    )
    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        facts = await build_report_facts(session, student, [world["subject_id"]])
    assert "Weakest topics" not in facts


async def test_another_organizations_threshold_does_not_apply(client, tutor, world):  # noqa: F811
    async with async_session() as session:
        rival_subject = await other_org_subject(session)
        rival = User(
            email="rival@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="Rival",
            organization_id=rival_subject.organization_id,
        )
        session.add(rival)
        await session.flush()
        session.add(
            ReadinessWeights(
                organization_id=rival_subject.organization_id,
                tutor_id=rival.id,
                weak_threshold=100.0,
            )
        )
        await session.commit()
    await _snapshot(world, {world["topic1"]: (70.0, FactorConfidence.high)})
    assert await _weak_ids(client, tutor, world) == []


# ---- The settings API ----


async def test_a_threshold_only_save_enqueues_no_recompute(client, tutor, world):  # noqa: F811
    before = await _count(Job)
    resp = await client.put(
        "/api/v1/readiness/weights", json=_body(weak_threshold=50), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert await _count(Job) == before

    resp = await client.put(
        "/api/v1/readiness/weights",
        json=_body(weak_threshold=50, weight_topic_mastery=2.0),
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        jobs = (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()
    assert [j.payload for j in jobs] == [
        {"student_id": world["student_id"], "subject_id": world["subject_id"]}
    ]


async def test_an_older_client_without_the_field_is_not_refused(client, tutor, world):  # noqa: F811
    body = _body()
    body.pop("weak_threshold", None)
    resp = await client.put("/api/v1/readiness/weights", json=body, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["weak_threshold"] == 60.0


async def test_omitting_the_field_keeps_the_tutors_threshold(client, tutor, world):  # noqa: F811
    """Omitted means "keep", never "reset to 60" — on the row itself, and on a
    new subject override, which starts from what the subject resolved to."""
    resp = await client.put(
        "/api/v1/readiness/weights", json=_body(weak_threshold=40), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = _body(weight_topic_mastery=2.0)
    body.pop("weak_threshold", None)
    resp = await client.put("/api/v1/readiness/weights", json=body, headers=tutor["headers"])
    assert resp.json()["weak_threshold"] == 40.0
    resp = await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=body,
        headers=tutor["headers"],
    )
    assert resp.json()["source"] == "subject"
    assert resp.json()["weak_threshold"] == 40.0


async def test_the_threshold_is_bounded(client, tutor):
    for bad in (101, -1):
        resp = await client.put(
            "/api/v1/readiness/weights", json=_body(weak_threshold=bad), headers=tutor["headers"]
        )
        assert resp.status_code == 422, bad


# ---- The class view ----


async def test_class_views_show_only_topics_under_the_subject_threshold(client, tutor, world):  # noqa: F811
    await _snapshot(
        world,
        {
            world["topic1"]: (70.0, FactorConfidence.high),
            world["topic2"]: (50.0, FactorConfidence.high),
        },
    )
    group_id = world["group"]["id"]

    async def codes() -> tuple[list[str], list[str]]:
        analytics = await client.get(
            f"/api/v1/analytics/groups/{group_id}", headers=tutor["headers"]
        )
        overview = await client.get(f"/api/v1/today/classes/{group_id}", headers=tutor["headers"])
        assert analytics.status_code == 200 and overview.status_code == 200
        return (
            [t["topic_code"] for t in analytics.json()["weak_topics"]],
            [t["topic_code"] for t in overview.json()["weak_topics"]],
        )

    assert await codes() == (["1.6"], ["1.6"])
    await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(weak_threshold=80),
        headers=tutor["headers"],
    )
    assert await codes() == (["1.6", "1.3"], ["1.6", "1.3"])
    await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(weak_threshold=10),
        headers=tutor["headers"],
    )
    assert await codes() == ([], [])


# ---- Synthesis ----


def test_the_model_is_no_longer_asked_for_weak_topics():
    assert "weak_topics" not in ReadinessSynthesis.model_json_schema()["properties"]
    assert "weak_topics" not in PROMPTS["readiness"].system
    assert PROMPTS["readiness"].version == "v4"


async def test_synthesis_stores_no_weak_topics(client, tutor, world, monkeypatch, fake_ai):  # noqa: F811
    await client.post(
        f"/api/v1/students/{world['student_id']}/seed-readiness",
        json={"topics": [{"topic_id": world["topic1"], "score_pct": 30}]},
        headers=tutor["headers"],
    )
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        fake_ai(ReadinessSynthesis(score=30, rationale="r", recommended_revision="-")),
    )
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )
        snapshot = await session.scalar(select(ReadinessSnapshot))
    assert snapshot.score is not None and snapshot.weak_topics == []
    assert await _weak_ids(client, tutor, world) == [world["topic1"]]
