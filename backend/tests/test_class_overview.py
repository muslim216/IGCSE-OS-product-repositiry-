"""PR 19 — the class page's headline endpoint.

The property that matters: NEEDS YOU is selected on direction, not level. A
learner sliding from a grade 8 to a 6 is the one the tutor can still help; a
learner who has been a stable grade 4 all year is why the class carries its
status and is not news. Both stay visible under Learners.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import FactorConfidence, Subject, Topic
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


async def _learner(client, tutor, group_id, name, username, score, history=(), homework=None):
    """Write the learner's readiness as v2 snapshots: one ready run per
    `history` value, oldest first and 5 days apart, with the *final* one at
    `score` — the same run the class page reads (services/class_readiness.py).
    An empty `history` writes just that one. `homework` (assignment_count,
    submitted_count), when given, lands on that final run only, since only the
    latest run's homework_performance row is ever read."""
    student = (
        await client.post(
            f"/api/v1/groups/{group_id}/students",
            json={"name": name, "username": username, "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        topic_id = await session.scalar(select(Topic.id))
        subject_id = await session.scalar(select(Topic.subject_id))
        points = list(history) or [score]
        points[-1] = score  # the latest run is always the score under test
        now = datetime.now(timezone.utc)
        for i, value in enumerate(points):
            await write_v2_snapshot(
                session,
                student_id=student["id"],
                subject_id=subject_id,
                score=value,
                topics={topic_id: (value, FactorConfidence.high)},
                homework=homework if i == len(points) - 1 else None,
                created_at=now - timedelta(days=(len(points) - 1 - i) * 5),
            )
        await session.commit()
    return student


async def test_declining_high_learner_is_in_needs_you(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    # Was a grade 8, now a 6 — still a good grade, but the movement is the story.
    await _learner(client, tutor, group["id"], "Slider", "slide01", 62.0, history=(85.0, 62.0))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    names = [r["student_name"] for r in body["needs_you"]]
    assert names == ["Slider"]
    assert body["needs_you"][0]["direction"] == "down"


async def test_stable_low_learner_is_absent_from_needs_you_but_present_under_learners(
    client, tutor, subject_id
):
    group = await _class_with(client, tutor, subject_id)
    # A steady grade 4 all year: why the class carries its status, but not news.
    await _learner(client, tutor, group["id"], "Steady", "steady01", 42.0, history=(41.0, 42.0))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    assert body["needs_you"] == []
    assert [r["student_name"] for r in body["learners"]] == ["Steady"]
    assert body["learners"][0]["direction"] == "flat"


async def test_one_history_point_yields_no_direction_never_flat(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "New", "new01", 70.0, history=(70.0,))

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    # One point is not a trend: null, so the surface renders no arrow at all.
    assert body["learners"][0]["direction"] is None


async def test_a_learner_without_evidence_appears_unscored_not_absent(client, tutor, subject_id):
    """Fix round 1: a learner with no snapshot at all still gets a row on the
    class page — score, predicted_grade, status and direction are all null
    (PROD-2), never a fabricated 0 and never a silently dropped learner. The
    class's own score and coverage stay unaffected — Ghost never enters
    either denominator."""
    group = await _class_with(client, tutor, subject_id)
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ghost", "username": "ghost01", "password": "password123"},
        headers=tutor["headers"],
    )
    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    assert [r["student_name"] for r in body["learners"]] == ["Ghost"]
    row = body["learners"][0]
    assert row["score"] is None
    assert row["predicted_grade"] is None
    assert row["status"] is None
    assert row["direction"] is None
    assert body["member_count"] == 1
    assert body["students_with_evidence"] == 0
    assert body["score"] is None


async def test_another_tutors_class_is_404_not_403(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    other = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "T2", "email": "t2@example.com", "password": "password123"},
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/today/classes/{group['id']}", headers=headers)
    assert resp.status_code == 404


async def test_a_student_cannot_reach_the_class_overview(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0)
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "aya01", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/today/classes/{group['id']}", headers=headers)
    assert resp.status_code == 403


async def test_learner_row_carries_homework_completion(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0, homework=(5, 4))
    row = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()["learners"][0]
    assert (row["homework_assignment_count"], row["homework_submitted_count"]) == (5, 4)


async def test_learner_without_homework_row_reports_null_not_zero(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0)
    row = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()["learners"][0]
    assert row["homework_assignment_count"] is None and row["homework_submitted_count"] is None


async def test_class_page_lists_every_learner_scored_then_unscored_by_name(
    client, tutor, subject_id
):
    """Fix round 1: a learner whose latest run found no evidence, and one who
    has no snapshot at all, both still get a row — sorted after the scored
    learner, by name. The class score stays the scored learner's own alone
    (decision 13's denominator is unchanged; only the learner list widened),
    and homework completion still reaches the no-evidence learner even though
    their score does not (5.1, AV-32)."""
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 80.0)
    await _learner(client, tutor, group["id"], "Zed", "zed01", None, homework=(2, 1))
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Milo", "username": "milo01", "password": "password123"},
        headers=tutor["headers"],
    )

    body = (
        await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    ).json()
    # Scored first, then the unscored two in name order — never omitted.
    assert [r["student_name"] for r in body["learners"]] == ["Aya", "Milo", "Zed"]

    by_name = {r["student_name"]: r for r in body["learners"]}
    zed = by_name["Zed"]
    assert zed["score"] is None
    assert zed["predicted_grade"] is None
    assert zed["status"] is None
    assert (zed["homework_assignment_count"], zed["homework_submitted_count"]) == (2, 1)

    milo = by_name["Milo"]
    assert milo["score"] is None
    assert milo["homework_assignment_count"] is None and milo["homework_submitted_count"] is None

    assert body["score"] == 80.0  # the scored learner's own score, unaveraged with nothing


async def test_class_overview_query_count_is_flat_in_roster_size(client, tutor, subject_id):
    """The class page reads every scored learner's series in one query
    (PERF-1) — this is the assertion that would catch a regression to one
    v2_score_points call per learner."""
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Solo", "solo01", 70.0)

    def count_queries():
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        return queries, lambda: event.remove(engine.sync_engine, "before_cursor_execute", before)

    queries, stop = count_queries()
    await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    stop()
    baseline = len(queries)

    for i in range(5):
        await _learner(client, tutor, group["id"], f"S{i}", f"roster{i}", 60.0 + i)

    queries, stop = count_queries()
    await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])
    stop()
    grown = len(queries)

    assert grown == baseline, (
        f"query count grew from {baseline} to {grown} as the roster went 1 -> 6; "
        "the class page must not fan out per learner"
    )
