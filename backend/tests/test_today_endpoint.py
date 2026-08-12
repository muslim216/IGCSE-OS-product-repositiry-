"""PR 17 — the tutor home's one aggregate endpoint.

The assertion that matters most is the query-count one: the surface this replaces
fanned out one analytics call per class, each of which looped per learner, so the
cost grew with the roster. If that regresses, nothing else here will notice.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import (
    Evidence,
    EvidenceSource,
    Group,
    ReadinessConfidence,
    Subject,
    Topic,
    TopicReadiness,
)


@pytest.fixture
async def subject_id():
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[
                {"grade": "9", "min": 90},
                {"grade": "8", "min": 80},
                {"grade": "7", "min": 70},
                {"grade": "6", "min": 60},
                {"grade": "5", "min": 50},
                {"grade": "U", "min": 0},
            ],
        )
        session.add(subject)
        await session.flush()
        session.add(Topic(subject_id=subject.id, code="1.3", title="Atoms", weight=1.0))
        await session.commit()
        return subject.id


async def _make_class(client, tutor, subject_id, name="Chem"):
    return (
        await client.post(
            "/api/v1/groups",
            json={"name": name, "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()


async def _add_student(client, tutor, group_id, name, username):
    return (
        await client.post(
            f"/api/v1/groups/{group_id}/students",
            json={"name": name, "username": username, "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()


async def _give_readiness(student_id, score, confidence=ReadinessConfidence.high):
    async with async_session() as session:
        topic_id = await session.scalar(select(Topic.id))
        session.add(
            TopicReadiness(
                student_id=student_id,
                topic_id=topic_id,
                score=score,
                confidence=confidence,
                evidence_count=3,
            )
        )
        session.add(
            Evidence(
                student_id=student_id,
                topic_id=topic_id,
                source_type=EvidenceSource.homework,
                score_pct=score,
                max_marks=20,
                occurred_at=datetime.now(timezone.utc),
                source_ref=f"submission:{student_id}",
            )
        )
        await session.commit()


async def test_a_student_cannot_reach_the_tutor_home(client, tutor, subject_id):
    group = await _make_class(client, tutor, subject_id)
    await _add_student(client, tutor, group["id"], "Aya", "aya01")
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "aya01", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    resp = await client.get("/api/v1/today", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tutor account required"


async def test_no_token_is_refused(client):
    assert (await client.get("/api/v1/today")).status_code == 401


async def test_a_class_with_no_evidence_reports_absence_not_zero(client, tutor, subject_id):
    """PROD-2: a missing measurement is null, never 0 or an empty bar."""
    await _make_class(client, tutor, subject_id)
    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    row = body["classes"][0]
    assert row["score"] is None
    assert row["predicted_grade"] is None
    assert row["status"] is None
    assert body["classes_with_evidence"] == 0


async def test_class_carries_grade_band_and_coverage(client, tutor, subject_id):
    group = await _make_class(client, tutor, subject_id)
    a = await _add_student(client, tutor, group["id"], "Aya", "aya01")
    await _add_student(client, tutor, group["id"], "Omar", "omar01")
    await _give_readiness(a["id"], 85.0)

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    row = body["classes"][0]
    assert row["score"] == 85.0
    assert row["predicted_grade"] == "8"
    assert row["status"] == "on_track"  # index 1 of the boundary list
    # Coverage travels as a pair: one of two learners has confident evidence, so
    # the surface can say 1/2 rather than implying the score speaks for both.
    assert row["students_with_evidence"] == 1
    assert row["member_count"] == 2


async def test_a_subject_without_boundaries_is_flagged_not_defaulted(client, tutor):
    """No boundaries means no grade and no colour — plus the flag that lets the
    surface offer "Set them →" instead of silently showing nothing."""
    async with async_session() as session:
        subject = Subject(
            exam_board="CIE",
            code="0620",
            name="Bare",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add(subject)
        await session.flush()
        session.add(Topic(subject_id=subject.id, code="1", title="T", weight=1.0))
        await session.commit()
        bare_id = subject.id

    group = await _make_class(client, tutor, bare_id, name="Bare class")
    student = await _add_student(client, tutor, group["id"], "Zed", "zed01")
    await _give_readiness(student["id"], 85.0)

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    row = next(r for r in body["classes"] if r["name"] == "Bare class")
    assert row["boundaries_missing"] is True
    assert row["predicted_grade"] is None
    assert row["status"] is None
    assert row["score"] == 85.0  # the score itself is still honest


async def test_exceptions_sort_before_healthy_classes(client, tutor, subject_id):
    healthy = await _make_class(client, tutor, subject_id, name="Healthy")
    struggling = await _make_class(client, tutor, subject_id, name="Struggling")
    good = await _add_student(client, tutor, healthy["id"], "Good", "good01")
    weak = await _add_student(client, tutor, struggling["id"], "Weak", "weak01")
    await _give_readiness(good["id"], 92.0)  # grade 9 -> on_track
    await _give_readiness(weak["id"], 20.0)  # grade U -> at_risk

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    assert body["classes"][0]["name"] == "Struggling"
    assert body["classes"][0]["status"] == "at_risk"
    assert body["classes"][-1]["status"] == "on_track"


async def test_another_tutors_class_is_not_in_the_response(client, tutor, subject_id):
    """SEC-7: scoped by the authenticated user, never by a parameter."""
    await _make_class(client, tutor, subject_id, name="Mine")
    other = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "T2", "email": "t2@example.com", "password": "password123"},
        )
    ).json()
    other_headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    await _make_class(client, {"headers": other_headers}, subject_id, name="Theirs")

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    names = [c["name"] for c in body["classes"]]
    assert names == ["Mine"]


async def test_query_count_does_not_grow_with_group_count(client, tutor, subject_id):
    """The assertion that keeps the fix from regressing.

    The old home issued one analytics request per class, and each of those ran a
    db.get(User) plus a readiness select per learner. Here the whole home is one
    request whose query count is flat in the number of classes.
    """

    def count_queries():
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        return queries, lambda: event.remove(engine.sync_engine, "before_cursor_execute", before)

    # One class, three learners.
    small = await _make_class(client, tutor, subject_id, name="Small")
    for i in range(3):
        s = await _add_student(client, tutor, small["id"], f"S{i}", f"small{i}")
        await _give_readiness(s["id"], 70.0 + i)

    queries, stop = count_queries()
    await client.get("/api/v1/today", headers=tutor["headers"])
    stop()
    baseline = len(queries)

    # Five more classes, each with learners and evidence.
    for c in range(5):
        g = await _make_class(client, tutor, subject_id, name=f"Class{c}")
        for i in range(3):
            s = await _add_student(client, tutor, g["id"], f"C{c}S{i}", f"c{c}s{i}")
            await _give_readiness(s["id"], 60.0 + i)

    queries, stop = count_queries()
    await client.get("/api/v1/today", headers=tutor["headers"])
    stop()
    grown = len(queries)

    assert grown == baseline, (
        f"query count grew from {baseline} to {grown} when classes went 1 -> 6; "
        "the aggregate must not fan out per class"
    )


async def test_lessons_use_the_org_timezone(client, tutor, subject_id):
    """The aggregate answers with the organization's today, not the server's —
    the same rule /me/today-lessons follows, reusing its handler so the two
    cannot drift apart."""
    from app.services.timezones import today_weekday

    group = await _make_class(client, tutor, subject_id)
    await client.put(
        "/api/v1/me/organization/timezone",
        json={"timezone": "Africa/Cairo"},
        headers=tutor["headers"],
    )
    weekday = today_weekday("Africa/Cairo")
    await client.post(
        f"/api/v1/groups/{group['id']}/lessons",
        json={"weekday": weekday, "start_time": "16:00:00", "duration_min": 60, "title": None},
        headers=tutor["headers"],
    )

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    assert len(body["lessons"]) == 1
    assert body["lessons"][0]["weekday"] == weekday


async def test_past_paper_review_counts_toward_the_workload(client, tutor, subject_id):
    """The count drives the Mark link and NEEDS YOU. Submission is polymorphic,
    so counting only through Assignment silently drops every past paper and the
    home can report a clear day while past-paper work waits (API-20)."""
    from app.models import PastPaper, Submission, SubmissionStatus

    group = await _make_class(client, tutor, subject_id)
    student = await _add_student(client, tutor, group["id"], "Aya", "aya01")

    async with async_session() as session:
        org_id = await session.scalar(select(Group.organization_id).where(Group.id == group["id"]))
        paper = PastPaper(
            organization_id=org_id,
            subject_id=subject_id,
            session_label="June 2025",
            paper_number="1",
        )
        session.add(paper)
        await session.flush()
        session.add(
            Submission(
                past_paper_id=paper.id,
                student_id=student["id"],
                status=SubmissionStatus.needs_review,
            )
        )
        await session.commit()

    body = (await client.get("/api/v1/today", headers=tutor["headers"])).json()
    assert body["review_count"] == 1, "a past paper awaiting review must count as work"


async def test_an_admin_cannot_read_another_organizations_class(client, tutor, subject_id):
    """SEC-7: the organization comes from the authenticated user. An admin is a
    tutor with wider reach inside their own organization, not across them."""
    from app.models import User, UserRole

    group = await _make_class(client, tutor, subject_id)
    other = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "Admin", "email": "admin@example.com", "password": "password123"},
        )
    ).json()
    async with async_session() as session:
        admin = await session.get(User, other["user"]["id"])
        admin.role = UserRole.admin
        await session.commit()
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "admin@example.com", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    resp = await client.get(f"/api/v1/today/classes/{group['id']}", headers=headers)
    assert resp.status_code == 404
