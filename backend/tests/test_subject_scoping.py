"""A subject belongs to one tenant, and nobody else can see it (task 2.2).

Subjects were global until this task — five built-in syllabuses every
organization shared — so `GET /subjects` returning the whole table was harmless.
The moment they became tutor-owned (`AV-6`) that same query was a cross-tenant
listing, and every route resolving a caller-supplied `subject_id` became an
enumeration oracle.

`QA-12`: a change touching authorization ships with the negative case.
"""

from app.db import async_session
from app.models import User, UserRole
from app.services.subjects import visible_subject_ids
from tests.factories import make_subject, org_id, subject_for_tutor
from tests.test_homework import group, subject  # noqa: F401 - shared fixtures


async def _rival(client, email: str = "rival@example.com"):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def test_a_tutor_only_lists_their_own_subjects(client, tutor):
    rival_headers = await _rival(client)
    async with async_session() as session:
        mine = await make_subject(session, code="4MINE", name="Mine")
        theirs = await subject_for_tutor(session, "rival@example.com", code="4THRS")
        await session.commit()
        mine_id, theirs_id = mine.id, theirs.id

    listing = await client.get("/api/v1/subjects", headers=tutor["headers"])
    assert listing.status_code == 200
    ids = [s["id"] for s in listing.json()]
    assert mine_id in ids
    assert theirs_id not in ids

    rival_listing = await client.get("/api/v1/subjects", headers=rival_headers)
    rival_ids = [s["id"] for s in rival_listing.json()]
    assert theirs_id in rival_ids
    assert mine_id not in rival_ids


async def test_another_organizations_subject_is_404_not_403(client, tutor):
    """404, never 403.

    Integer keys are enumerable, so a 403 would confirm that a subject with that
    id exists in someone else's account — the difference between "no" and "yes,
    but not for you" is the whole leak (`API-7`, `SEC-9`).
    """
    await _rival(client)
    async with async_session() as session:
        theirs = await subject_for_tutor(session, "rival@example.com", code="4THRS")
        await session.commit()
        theirs_id = theirs.id

    topics = await client.get(f"/api/v1/subjects/{theirs_id}/topics", headers=tutor["headers"])
    assert topics.status_code == 404

    # A subject that does not exist at all must be indistinguishable from one
    # that exists in another tenant — same status, same body.
    missing = await client.get("/api/v1/subjects/999999/topics", headers=tutor["headers"])
    assert missing.status_code == 404
    assert topics.json() == missing.json()


async def test_a_tutor_cannot_build_on_another_organizations_subject(client, tutor):
    """The write paths refuse it too, not only the reads."""
    await _rival(client)
    async with async_session() as session:
        theirs = await subject_for_tutor(session, "rival@example.com", code="4THRS")
        await session.commit()
        theirs_id = theirs.id

    created = await client.post(
        "/api/v1/groups",
        json={"name": "Poached", "subject_id": theirs_id},
        headers=tutor["headers"],
    )
    assert created.status_code == 404, created.text


async def test_a_student_sees_the_subject_they_are_taught(client, tutor, subject, group):  # noqa: F811
    """Scoped by enrolment, not by the student's own organization.

    A student who joins a second tutor's group with an invite does not move
    organization, so filtering subjects on `user.organization_id` would hide a
    subject they are actively being taught. `_enrolled_scope` in
    `api/past_papers.py` records the same reasoning for past papers (`SEC-8`).
    """
    created = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Pupil", "username": "pupil01", "password": "password123"},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text

    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "pupil01", "password": "password123"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    listing = await client.get("/api/v1/subjects", headers=headers)
    assert listing.status_code == 200
    assert [s["id"] for s in listing.json()] == [subject["id"]]


async def test_a_student_in_no_groups_sees_no_subjects(client, tutor, subject):  # noqa: F811
    """Absence is empty, not everything — the pre-2.2 behaviour was everything.

    Asserted against `visible_subject_ids` rather than the endpoint because a
    student cannot reach that state through the API: registration requires an
    invite, which puts them in a group. The branch exists all the same, and an
    empty enrolment returning "every subject" is exactly the regression this
    guards.
    """
    async with async_session() as session:
        await make_subject(session, code="4LONE", name="Unreachable")
        orphan = User(
            email="loner@example.com",
            password_hash="x",
            role=UserRole.student,
            name="Loner",
            organization_id=await org_id(session),
        )
        session.add(orphan)
        await session.commit()

        assert await visible_subject_ids(session, orphan) == set()


async def test_a_parent_with_no_children_sees_no_subjects(client, tutor, subject):  # noqa: F811
    async with async_session() as session:
        unlinked = User(
            email="nobody-parent@example.com",
            password_hash="x",
            role=UserRole.parent,
            name="Unlinked",
            organization_id=await org_id(session),
        )
        session.add(unlinked)
        await session.commit()

        assert await visible_subject_ids(session, unlinked) == set()
