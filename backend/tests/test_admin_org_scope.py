"""An admin is a tutor with wider reach inside their own organization — never
across organizations (`SEC-7`, `PROD-4`).

Each helper these routes go through had `user.role == admin` short-circuit the
ownership test with no organization check, so an admin in one tenant could read
and write another tenant's students, classes and lessons by integer id. Every
refusal here is a 404, not a 403: ids are enumerable (`API-7`, `SEC-9`).
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Group, GroupMember, Invite, Lesson, Organization, User, UserRole
from app.security import create_access_token, hash_password
from tests.factories import make_subject


async def _admin_headers(organization_id: int | None = None) -> dict:
    """An admin in `organization_id`, or in a brand-new organization."""
    async with async_session() as session:
        if organization_id is None:
            org = Organization(name="Org A")
            session.add(org)
            await session.flush()
            organization_id = org.id
        admin = User(
            email=f"admin-{organization_id}@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            name="Admin",
            organization_id=organization_id,
        )
        session.add(admin)
        await session.commit()
        token = create_access_token(admin.id, admin.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def foreign_admin(student):
    """An admin whose organization is not the fixture tutor's."""
    return await _admin_headers()


@pytest.fixture
async def home_org_id(group) -> int:
    async with async_session() as session:
        return (await session.get(Group, group["id"])).organization_id


@pytest.fixture
async def lesson_id(group, home_org_id):
    async with async_session() as session:
        lesson = Lesson(
            organization_id=home_org_id,
            group_id=group["id"],
            date=date(2026, 9, 1),
            duration_min=60,
        )
        session.add(lesson)
        await session.commit()
        return lesson.id


async def test_admin_cannot_read_another_organizations_student_crm(client, student, foreign_admin):
    sid = student["user"]["id"]
    resp = await client.get(f"/api/v1/students/{sid}/crm", headers=foreign_admin)
    assert resp.status_code == 404, resp.text
    resp = await client.get(f"/api/v1/students/{sid}/custom-criteria", headers=foreign_admin)
    assert resp.status_code == 404, resp.text


async def test_admin_cannot_score_another_organizations_student(client, student, foreign_admin):
    """The criterion is the admin's own, so only the student check can refuse."""
    criterion = await client.post(
        "/api/v1/custom-criteria", json={"name": "Exam technique"}, headers=foreign_admin
    )
    assert criterion.status_code == 201, criterion.text
    url = f"/api/v1/students/{student['user']['id']}/custom-criteria/{criterion.json()['id']}"

    resp = await client.put(url, json={"score": 70}, headers=foreign_admin)
    assert resp.status_code == 404, resp.text
    assert (await client.delete(url, headers=foreign_admin)).status_code == 404


async def test_admin_cannot_mint_a_parent_code_for_another_organizations_student(
    client, student, foreign_admin
):
    """The worst of them: the code links a parent to a named child's whole record."""
    sid = student["user"]["id"]
    resp = await client.post(f"/api/v1/students/{sid}/parent-code", headers=foreign_admin)
    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        minted = (await session.scalars(select(Invite).where(Invite.student_id == sid))).all()
    assert minted == []


async def test_admin_cannot_read_another_organizations_group(client, group, foreign_admin):
    gid = group["id"]
    for path in (f"/api/v1/analytics/groups/{gid}", f"/api/v1/groups/{gid}"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)


async def test_admin_cannot_reach_another_organizations_lessons(
    client, group, lesson_id, foreign_admin
):
    for path in (f"/api/v1/lessons/group/{group['id']}", f"/api/v1/lessons/{lesson_id}"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)


async def test_same_organization_admin_keeps_their_reach(
    client, student, group, lesson_id, home_org_id
):
    """The fix narrows the admin branch to the tenant; it does not remove it."""
    headers = await _admin_headers(home_org_id)
    sid, gid = student["user"]["id"], group["id"]
    for path in (
        f"/api/v1/students/{sid}/crm",
        f"/api/v1/analytics/groups/{gid}",
        f"/api/v1/groups/{gid}",
        f"/api/v1/lessons/group/{gid}",
        f"/api/v1/lessons/{lesson_id}",
    ):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.text)
    resp = await client.post(f"/api/v1/students/{sid}/parent-code", headers=headers)
    assert resp.status_code == 201, resp.text


async def test_admin_reaches_a_student_homed_elsewhere_who_sits_in_their_class(
    client, tutor, student
):
    """Reach is "in a class of my organization, or homed in it" — the rule
    `visible_subject_ids` already used. Home organization alone left an admin
    with less reach than a tutor in the same organization."""
    sid = student["user"]["id"]
    async with async_session() as session:
        org = Organization(name="Org A")
        session.add(org)
        await session.flush()
        teacher = User(
            email="teacher-a@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.tutor,
            name="Teacher A",
            organization_id=org.id,
        )
        session.add(teacher)
        subject = await make_subject(session, organization_id=org.id, code="4PH1", name="Physics")
        await session.flush()
        class_a = Group(
            organization_id=org.id, tutor_id=teacher.id, subject_id=subject.id, name="Phys"
        )
        session.add(class_a)
        await session.commit()
        org_id, class_id = org.id, class_a.id
    headers = await _admin_headers(org_id)

    # No tie to the organization yet: still a 404 (`API-7`).
    resp = await client.get(f"/api/v1/students/{sid}/crm", headers=headers)
    assert resp.status_code == 404, resp.text
    resp = await client.post(f"/api/v1/students/{sid}/notes", json={"body": "x"}, headers=headers)
    assert resp.status_code == 404, resp.text

    async with async_session() as session:
        session.add(GroupMember(group_id=class_id, student_id=sid))
        await session.commit()

    # `_viewable_student` and `_tutor_student`, one rule in both.
    resp = await client.get(f"/api/v1/students/{sid}/crm", headers=headers)
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/students/{sid}/notes", json={"body": "x"}, headers=headers)
    assert resp.status_code == 201, resp.text

    # Reaching the student is not reaching what the home organization wrote
    # about the family: its profile, notes and parent communications stay its
    # own, in both directions (`SEC-7`).
    home = tutor["headers"]
    profile = {"school": "Home School", "parent_email": "parent@home.example"}
    assert (
        await client.put(f"/api/v1/students/{sid}/profile", json=profile, headers=home)
    ).status_code == 200
    for path, body in (("notes", "home note"), ("communications", "home call")):
        resp = await client.post(
            f"/api/v1/students/{sid}/{path}", json={"body": body}, headers=home
        )
        assert resp.status_code == 201, resp.text

    theirs = (await client.get(f"/api/v1/students/{sid}/crm", headers=headers)).json()
    assert theirs["profile"] is None
    assert [n["body"] for n in theirs["notes"]] == ["x"]
    assert theirs["communications"] == []
    resp = await client.put(
        f"/api/v1/students/{sid}/profile", json={"school": "Overwritten"}, headers=headers
    )
    assert resp.status_code == 409, resp.text

    mine = (await client.get(f"/api/v1/students/{sid}/crm", headers=home)).json()
    assert mine["profile"]["school"] == "Home School"
    assert [n["body"] for n in mine["notes"]] == ["home note"]
    assert [c["body"] for c in mine["communications"]] == ["home call"]


async def test_a_student_asking_for_another_students_record_gets_404(client, tutor, group, student):
    """`API-7`: a 403 would confirm that a student with that id exists."""
    other = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Bob", "username": "bob01", "password": "password123"},
        headers=tutor["headers"],
    )
    assert other.status_code == 201, other.text
    resp = await client.get(
        f"/api/v1/students/{other.json()['id']}/crm", headers=student["headers"]
    )
    assert resp.status_code == 404, resp.text
