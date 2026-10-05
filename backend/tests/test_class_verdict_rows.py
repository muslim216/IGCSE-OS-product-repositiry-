"""Coherence C.1 follow-up: the class page's learner rows carry the shared
verdict, the same one the learner's profile prints."""

import pytest
from sqlalchemy import event

from app.db import async_session, engine
from app.models import FactorConfidence, Subject
from app.services.grade_boundaries import set_org_boundaries
from tests.factories import chemistry_with_topics, write_v2_snapshot

API = "/api/v1"


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        ids = await chemistry_with_topics(session, ["Atomic structure", "Ionic bonding"])
    group = (
        await client.post(
            f"{API}/groups",
            json={"name": "Chem", "subject_id": ids[0]},
            headers=tutor["headers"],
        )
    ).json()
    return {"subject_id": ids[0], "topic_ids": ids[1], "group_id": group["id"]}


async def _student(client, tutor, world, name, username, score=None, grade=None):
    student = (
        await client.post(
            f"{API}/groups/{world['group_id']}/students",
            json={"name": name, "username": username, "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    if score is not None:
        async with async_session() as session:
            await write_v2_snapshot(
                session,
                student_id=student["id"],
                subject_id=world["subject_id"],
                score=score,
                predicted_grade=grade,
                topics={
                    world["topic_ids"][0]: (85.0, FactorConfidence.high),
                    world["topic_ids"][1]: (score - 20, FactorConfidence.high),
                },
            )
            await session.commit()
    return student


async def _overview(client, tutor, world):
    r = await client.get(f"{API}/today/classes/{world['group_id']}", headers=tutor["headers"])
    assert r.status_code == 200
    return r.json()


async def test_row_verdict_equals_the_profiles_verdict(client, tutor, world):
    student = await _student(client, tutor, world, "Sara", "sara01", 62.0, "6")
    row = (await _overview(client, tutor, world))["learners"][0]
    profile = (
        await client.get(f"{API}/readiness/students/{student['id']}", headers=tutor["headers"])
    ).json()
    expected = profile["subjects"][0]["verdict"]
    assert expected["status"] != "not_enough_data"
    assert expected["reason_topics"] == ["Ionic bonding"]
    assert row["verdict"] == expected
    assert "status" not in row  # replaced by the verdict, not kept beside it


async def test_learner_without_a_snapshot_is_not_enough_data(client, tutor, world):
    await _student(client, tutor, world, "Blank", "blank01")
    row = (await _overview(client, tutor, world))["learners"][0]
    assert row["verdict"]["status"] == "not_enough_data"
    assert row["verdict"]["reason_topics"] == []


async def test_a_score_with_no_boundaries_gets_no_status(client, tutor, world):
    await _student(client, tutor, world, "Sara", "sara01", 62.0, "6")
    async with async_session() as session:
        subject = await session.get(Subject, world["subject_id"])
        await set_org_boundaries(session, subject.organization_id, subject.id, [])
        await session.commit()
    row = (await _overview(client, tutor, world))["learners"][0]
    assert row["verdict"]["status"] == "not_enough_data"
    assert row["predicted_grade"] is None


async def test_another_organizations_learner_never_appears(client, tutor, world):
    await _student(client, tutor, world, "Sara", "sara01", 62.0, "6")
    other = (
        await client.post(
            f"{API}/auth/register/tutor",
            json={"name": "Other", "email": "other@example.com", "password": "password123"},
        )
    ).json()
    token = other["tokens"]["access_token"]
    # The other tutor cannot read this class at all, and the verdict's data
    # never leaks into a 404 (SEC-7, API-7).
    r = await client.get(
        f"{API}/today/classes/{world['group_id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 404
    assert "verdict" not in r.text


async def test_query_count_does_not_grow_with_the_roster(client, tutor, world):
    await _student(client, tutor, world, "S0", "s000", 62.0, "6")

    async def count():
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            await _overview(client, tutor, world)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        return len(queries)

    baseline = await count()
    for i in range(1, 5):
        await _student(client, tutor, world, f"S{i}", f"s00{i}", 55.0 + i, "5")
    assert await count() == baseline


async def test_a_learner_missing_from_the_verdicts_degrades_to_not_enough_data(
    client, tutor, world, monkeypatch
):
    from app.services import today

    async def none_at_all(db, group, snapshots=None):
        return {}

    monkeypatch.setattr(today, "class_verdicts", none_at_all)
    await _student(client, tutor, world, "Sara", "sara01", 62.0, "6")
    row = (await _overview(client, tutor, world))["learners"][0]
    assert row["verdict"]["status"] == "not_enough_data"
