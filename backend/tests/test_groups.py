import pytest

from app.services.groups import class_health


@pytest.fixture
async def subject_id(client, tutor):
    """Seed one subject directly via the DB."""
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        return subject.id


@pytest.fixture
async def group(client, tutor, subject_id):
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Chemistry Y10", "subject_id": subject_id},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_and_list_groups(client, tutor, group):
    resp = await client.get("/api/v1/groups", headers=tutor["headers"])
    assert resp.status_code == 200
    groups = resp.json()
    assert len(groups) == 1
    assert groups[0]["name"] == "Chemistry Y10"
    assert groups[0]["subject"]["code"] == "4CH1"


async def test_other_tutor_cannot_see_group(client, group):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other Tutor", "email": "other@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    listing = await client.get("/api/v1/groups", headers=other_headers)
    assert listing.json() == []
    detail = await client.get(f"/api/v1/groups/{group['id']}", headers=other_headers)
    assert detail.status_code == 404


async def test_student_join_via_invite(client, tutor, group):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    code = invite.json()["code"]

    preview = await client.get(f"/api/v1/auth/invites/{code}")
    assert preview.status_code == 200
    assert preview.json()["group_name"] == "Chemistry Y10"

    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": code,
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "student"

    detail = await client.get(f"/api/v1/groups/{group['id']}", headers=tutor["headers"])
    members = detail.json()["members"]
    assert [m["name"] for m in members] == ["Sara"]

    # The student sees the group on their side too.
    student_headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    mine = await client.get("/api/v1/me/groups", headers=student_headers)
    assert [g["name"] for g in mine.json()] == ["Chemistry Y10"]


async def test_tutor_created_student_account(client, tutor, group):
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ali", "username": "ali_2010", "password": "password123"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["username"] == "ali_2010"

    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "ali_2010", "password": "password123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "student"

    # Tutor can reset the password for username-only accounts.
    student_id = resp.json()["id"]
    reset = await client.post(
        f"/api/v1/groups/{group['id']}/students/{student_id}/reset-password",
        json={"password": "newpassword1"},
        headers=tutor["headers"],
    )
    assert reset.status_code == 204
    relogin = await client.post(
        "/api/v1/auth/login", json={"identifier": "ali_2010", "password": "newpassword1"}
    )
    assert relogin.status_code == 200


async def test_parent_link_flow(client, tutor, group):
    student = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ali", "username": "ali_2010", "password": "password123"},
        headers=tutor["headers"],
    )
    student_id = student.json()["id"]

    code_resp = await client.post(
        f"/api/v1/students/{student_id}/parent-code", headers=tutor["headers"]
    )
    assert code_resp.status_code == 201
    code = code_resp.json()["code"]

    parent = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Ali's Parent",
            "email": "parent@example.com",
            "password": "password123",
        },
    )
    assert parent.status_code == 201
    parent_headers = {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"}
    children = await client.get("/api/v1/me/children", headers=parent_headers)
    assert [c["name"] for c in children.json()] == ["Ali"]


async def test_lessons_and_student_view(client, tutor, group):
    lesson = await client.post(
        f"/api/v1/groups/{group['id']}/lessons",
        json={"weekday": 1, "start_time": "17:00", "duration_min": 90, "title": "Weekly"},
        headers=tutor["headers"],
    )
    assert lesson.status_code == 201, lesson.text

    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    student = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    student_headers = {"Authorization": f"Bearer {student.json()['tokens']['access_token']}"}
    lessons = await client.get("/api/v1/me/lessons", headers=student_headers)
    assert lessons.status_code == 200
    assert lessons.json()[0]["subject_name"] == "Chemistry"
    assert lessons.json()[0]["weekday"] == 1


async def test_student_cannot_create_group(client, tutor, group, subject_id):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    student = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    student_headers = {"Authorization": f"Bearer {student.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Hacked", "subject_id": subject_id},
        headers=student_headers,
    )
    assert resp.status_code == 403


async def test_group_summary_counts_feed_the_class_card(client, tutor, group):
    """The card fields must be populated on both the list and the detail view."""
    listing = (await client.get("/api/v1/groups", headers=tutor["headers"])).json()[0]
    assert listing["member_count"] == 0
    assert listing["published_assignment_count"] == 0
    assert listing["awaiting_review_count"] == 0
    assert listing["next_lesson"] is None

    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ali", "username": "ali_2010", "password": "password123"},
        headers=tutor["headers"],
    )
    await client.post(
        f"/api/v1/groups/{group['id']}/lessons",
        json={"weekday": 2, "start_time": "17:00", "duration_min": 90},
        headers=tutor["headers"],
    )

    listing = (await client.get("/api/v1/groups", headers=tutor["headers"])).json()[0]
    assert listing["member_count"] == 1
    assert listing["next_lesson"]["weekday"] == 2
    assert listing["next_lesson"]["duration_min"] == 90

    # GroupDetail carries the same summary, so the header needs no second request.
    detail = (await client.get(f"/api/v1/groups/{group['id']}", headers=tutor["headers"])).json()
    assert detail["member_count"] == 1
    assert detail["next_lesson"]["weekday"] == 2


async def test_next_lesson_picks_the_soonest_slot(client, tutor, group):
    """With several weekly slots the card shows whichever comes round first."""
    for weekday in (0, 3, 6):
        await client.post(
            f"/api/v1/groups/{group['id']}/lessons",
            json={"weekday": weekday, "start_time": "09:00", "duration_min": 60},
            headers=tutor["headers"],
        )

    from datetime import datetime, timezone

    listing = (await client.get("/api/v1/groups", headers=tutor["headers"])).json()[0]
    today = datetime.now(timezone.utc).weekday()
    expected = min((0, 3, 6), key=lambda d: (d - today) % 7 or 7)
    # A slot earlier today has passed, so "0 days away" only counts before 09:00.
    assert listing["next_lesson"]["weekday"] in (expected, today)


# --------------------------------------------------------------------------- #
# class_health — per-class readiness in one query (PERF-1). Exercised through
# /api/v1/today as well, but these hit the function directly so the averaging
# and scoping rules are pinned independently of that surface.
# --------------------------------------------------------------------------- #


async def _add_topic(subject_id: int, code: str, title: str = "Topic", weight: float = 1.0) -> int:
    from app.db import async_session
    from app.models import Topic

    async with async_session() as session:
        topic = Topic(subject_id=subject_id, code=code, title=title, weight=weight)
        session.add(topic)
        await session.commit()
        return topic.id


async def _give_topic_readiness(student_id: int, topic_id: int, score: float, confidence: str):
    from app.db import async_session
    from app.models import ReadinessConfidence, TopicReadiness

    async with async_session() as session:
        session.add(
            TopicReadiness(
                student_id=student_id,
                topic_id=topic_id,
                score=score,
                confidence=ReadinessConfidence(confidence),
                evidence_count=3,
            )
        )
        await session.commit()


async def test_class_health_returns_empty_dict_for_no_groups():
    from app.db import async_session

    async with async_session() as session:
        assert await class_health(session, []) == {}


async def test_class_health_reports_absence_not_zero_with_no_evidence(client, tutor, group):
    """A class with no confident evidence maps to (None, 0), never (0.0, 0),
    which a surface would render as a real score (PROD-2)."""
    from app.db import async_session
    from app.models import Group

    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Ghost", "username": "ghost01", "password": "password123"},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        g = await session.get(Group, group["id"])
        result = await class_health(session, [g])
    assert result[group["id"]] == (None, 0)


async def test_class_health_weights_by_topic_weight(client, tutor, group, subject_id):
    """SUM(weight * score) / SUM(weight) for one confident learner across two
    topics of different weight."""
    from app.db import async_session
    from app.models import Group

    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Aya", "username": "aya01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    heavy = await _add_topic(subject_id, "1.1", weight=3.0)
    light = await _add_topic(subject_id, "1.2", weight=1.0)
    await _give_topic_readiness(student["id"], heavy, 80.0, "high")
    await _give_topic_readiness(student["id"], light, 40.0, "high")

    async with async_session() as session:
        g = await session.get(Group, group["id"])
        score, count = (await class_health(session, [g]))[group["id"]]
    assert count == 1
    assert score == round((3.0 * 80.0 + 1.0 * 40.0) / 4.0, 1)  # 70.0


@pytest.mark.parametrize(
    "confidence,expected",
    [("high", (90.0, 1)), ("medium", (90.0, 1)), ("low", (None, 0))],
)
async def test_class_health_counts_only_confident_readiness(
    client, tutor, group, subject_id, confidence, expected
):
    """Only medium/high confidence counts as confident evidence — a low-
    confidence row must not silently produce a class score.

    `medium` is here because it is the *inclusive* boundary: with only `high`
    and `low` asserted, a filter that had narrowed to `high` alone would still
    have passed both, and half the class's evidence would have vanished from
    every class score with nothing to catch it.
    """
    from app.db import async_session
    from app.models import Group

    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Aya", "username": "aya01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    topic = await _add_topic(subject_id, "1.1")
    await _give_topic_readiness(student["id"], topic, 90.0, confidence)

    async with async_session() as session:
        g = await session.get(Group, group["id"])
        score, count = (await class_health(session, [g]))[group["id"]]
    assert (score, count) == expected


async def test_class_health_means_across_contributing_learners(client, tutor, group, subject_id):
    """The class score is the mean of each confident learner's own weighted
    score, and the second return value counts how many learners contributed."""
    from app.db import async_session
    from app.models import Group

    a = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Aya", "username": "aya01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    b = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Omar", "username": "omar01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    topic = await _add_topic(subject_id, "1.1")
    await _give_topic_readiness(a["id"], topic, 80.0, "high")
    await _give_topic_readiness(b["id"], topic, 40.0, "high")

    async with async_session() as session:
        g = await session.get(Group, group["id"])
        score, count = (await class_health(session, [g]))[group["id"]]
    assert count == 2
    assert score == 60.0


async def test_class_health_scopes_two_classes_independently(client, tutor, subject_id, group):
    """One query serves every class the tutor has; each group's score must not
    leak into another's."""
    from app.db import async_session
    from app.models import Group

    other = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chemistry Y11", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()

    a = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Aya", "username": "aya01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    b = (
        await client.post(
            f"/api/v1/groups/{other['id']}/students",
            json={"name": "Omar", "username": "omar01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    topic = await _add_topic(subject_id, "1.1")
    await _give_topic_readiness(a["id"], topic, 90.0, "high")
    await _give_topic_readiness(b["id"], topic, 30.0, "high")

    async with async_session() as session:
        groups = [await session.get(Group, group["id"]), await session.get(Group, other["id"])]
        result = await class_health(session, groups)
    assert result[group["id"]] == (90.0, 1)
    assert result[other["id"]] == (30.0, 1)


async def test_class_health_ignores_topics_from_a_different_subject(
    client, tutor, group, subject_id
):
    """Topics are global, so a student's readiness in a subject this class does
    not teach must not leak into the class's score."""
    from app.db import async_session
    from app.models import Group, Subject

    async with async_session() as session:
        other_subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add(other_subject)
        await session.commit()
        other_subject_id = other_subject.id

    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Aya", "username": "aya01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    physics_topic = await _add_topic(other_subject_id, "P1.1")
    await _give_topic_readiness(student["id"], physics_topic, 95.0, "high")

    async with async_session() as session:
        g = await session.get(Group, group["id"])
        score, count = (await class_health(session, [g]))[group["id"]]
    assert (score, count) == (None, 0)
