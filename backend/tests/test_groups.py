import pytest


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
    student_headers = {
        "Authorization": f"Bearer {resp.json()['tokens']['access_token']}"
    }
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
    parent_headers = {
        "Authorization": f"Bearer {parent.json()['tokens']['access_token']}"
    }
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
    student_headers = {
        "Authorization": f"Bearer {student.json()['tokens']['access_token']}"
    }
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
    student_headers = {
        "Authorization": f"Bearer {student.json()['tokens']['access_token']}"
    }
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
    detail = (
        await client.get(f"/api/v1/groups/{group['id']}", headers=tutor["headers"])
    ).json()
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
