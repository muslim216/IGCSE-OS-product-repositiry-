"""One tutor's workspace per student at launch (owner, 18 Oct 2026).

A student who sat in a second organization's class let that organization's
tutor reset the child's password, mint a parent link to them, change their
enrolments and read the first organization's record. The join is now refused,
and every edit to a student's record is their home organization's alone — so a
membership made before the refusal reaches nothing it should not. Every refusal
of a record the caller may not know about is a 404 (`API-7`, `SEC-9`, `QA-12`).
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import GroupMember, Invite, StudentSubject, User
from tests.factories import make_subject

API = "/api/v1"


@pytest.fixture
async def other_tutor(client, tutor):
    """A tutor who signed up separately, so has an organization of their own.
    After `tutor`, whose organization the shared `subject` fixture files under."""
    resp = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "Other Tutor", "email": "other@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


@pytest.fixture
async def other_class(client, other_tutor) -> dict:
    """A class in the other tutor's organization, on a subject of its own."""
    async with async_session() as session:
        tutor = await session.get(User, other_tutor["user"]["id"])
        subject = await make_subject(
            session, organization_id=tutor.organization_id, code="4PH1", name="Physics"
        )
        await session.commit()
        subject_id = subject.id
    resp = await client.post(
        f"{API}/groups",
        json={"name": "Phys Y10", "subject_id": subject_id},
        headers=other_tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return {"id": resp.json()["id"], "subject_id": subject_id}


@pytest.fixture
async def already_in_other_class(student, other_class) -> int:
    """The shape a join made before the refusal left behind."""
    sid = student["user"]["id"]
    async with async_session() as session:
        session.add(GroupMember(group_id=other_class["id"], student_id=sid))
        await session.commit()
    return sid


async def _memberships(student_id: int) -> list[int]:
    async with async_session() as session:
        return list(
            await session.scalars(
                select(GroupMember.group_id).where(GroupMember.student_id == student_id)
            )
        )


# --- The join ----------------------------------------------------------------


async def test_joining_another_organizations_class_is_refused(
    client, student, group, other_tutor, other_class
):
    invite = await client.post(
        f"{API}/groups/{other_class['id']}/invites", headers=other_tutor["headers"]
    )
    assert invite.status_code == 201, invite.text

    resp = await client.post(
        f"{API}/auth/join", json={"invite_code": invite.json()["code"]}, headers=student["headers"]
    )

    assert resp.status_code == 409, resp.text
    assert "another tutor" in resp.json()["detail"]
    assert await _memberships(student["user"]["id"]) == [group["id"]]


async def test_joining_a_second_class_of_the_same_organization_still_works(
    client, tutor, subject, student, group
):
    second = await client.post(
        f"{API}/groups",
        json={"name": "Chem Y11", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    assert second.status_code == 201, second.text
    invite = await client.post(
        f"{API}/groups/{second.json()['id']}/invites", headers=tutor["headers"]
    )

    resp = await client.post(
        f"{API}/auth/join", json={"invite_code": invite.json()["code"]}, headers=student["headers"]
    )

    assert resp.status_code == 204, resp.text
    assert sorted(await _memberships(student["user"]["id"])) == sorted(
        [group["id"], second.json()["id"]]
    )


# --- A membership made before the refusal ------------------------------------


async def test_the_other_tutor_cannot_reset_the_students_password(
    client, other_tutor, other_class, already_in_other_class
):
    sid = already_in_other_class
    async with async_session() as session:
        # Only an account without an email can be reset at all, so the
        # organization check is the one refusing here.
        student = await session.get(User, sid)
        student.email = None
        await session.commit()
        before = student.token_version

    resp = await client.post(
        f"{API}/groups/{other_class['id']}/students/{sid}/reset-password",
        json={"password": "taken-over-1"},
        headers=other_tutor["headers"],
    )

    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        assert (await session.get(User, sid)).token_version == before


async def test_the_other_tutor_cannot_mint_a_parent_link(
    client, other_tutor, already_in_other_class
):
    sid = already_in_other_class
    resp = await client.post(f"{API}/students/{sid}/parent-code", headers=other_tutor["headers"])

    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        assert (await session.scalars(select(Invite).where(Invite.student_id == sid))).all() == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "notes", {"body": "x"}),
        ("POST", "communications", {"body": "x"}),
        ("PUT", "profile", {"school": "Overwritten"}),
        ("POST", "subjects", None),
    ],
)
async def test_the_other_tutor_cannot_write_to_the_record(
    client, other_tutor, other_class, already_in_other_class, method, path, body
):
    """One case each, so every write is shown refused on its own."""
    sid = already_in_other_class
    resp = await client.request(
        method,
        f"{API}/students/{sid}/{path}",
        json=body or {"subject_id": other_class["subject_id"]},
        headers=other_tutor["headers"],
    )
    assert resp.status_code == 404, resp.text


async def test_enrolment_changes_need_the_callers_own_subject(
    client, tutor, other_tutor, other_class, already_in_other_class
):
    """An enrolment the other organization made before the refusal: the home
    tutor can't change or remove it by naming that organization's subject in
    the path, and the other tutor can't touch the student's at all."""
    sid = already_in_other_class
    async with async_session() as session:
        session.add(
            StudentSubject(student_id=sid, subject_id=other_class["subject_id"], target_grade="7")
        )
        await session.commit()
    path = f"{API}/students/{sid}/subjects/{other_class['subject_id']}"

    for headers in (tutor["headers"], other_tutor["headers"]):
        resp = await client.patch(path, json={"target_grade": "9"}, headers=headers)
        assert resp.status_code == 404, resp.text
        assert (await client.delete(path, headers=headers)).status_code == 404

    async with async_session() as session:
        kept = await session.scalar(
            select(StudentSubject).where(
                StudentSubject.student_id == sid,
                StudentSubject.subject_id == other_class["subject_id"],
            )
        )
    assert kept is not None
    assert kept.target_grade == "7"


async def test_the_other_tutors_view_holds_only_their_own_organizations_work(
    client, tutor, subject, published_assignment, other_tutor, other_class, already_in_other_class
):
    sid = already_in_other_class
    resp = await client.post(
        f"{API}/students/{sid}/subjects",
        json={"subject_id": subject["id"], "target_grade": "8"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    home = (await client.get(f"{API}/students/{sid}/crm", headers=tutor["headers"])).json()
    # The home tutor's view has each of these, so their absence below is the
    # scoping and not an empty record.
    assert home["homework"]
    assert [e["subject_id"] for e in home["enrollments"]] == [subject["id"]]
    assert subject["id"] in {r["subject_id"] for r in home["readiness"]}

    theirs = await client.get(f"{API}/students/{sid}/crm", headers=other_tutor["headers"])

    assert theirs.status_code == 200, theirs.text
    body = theirs.json()
    assert body["homework"] == []
    assert body["enrollments"] == []
    assert {r["subject_id"] for r in body["readiness"]} == {other_class["subject_id"]}


# --- Notes are the tutor's alone ---------------------------------------------


async def test_the_student_and_parent_never_see_notes_or_parent_contact(client, tutor, student):
    sid = student["user"]["id"]
    for path, body in (("notes", "private note"), ("communications", "called mum")):
        resp = await client.post(
            f"{API}/students/{sid}/{path}", json={"body": body}, headers=tutor["headers"]
        )
        assert resp.status_code == 201, resp.text
    code = await client.post(f"{API}/students/{sid}/parent-code", headers=tutor["headers"])
    parent = await client.post(
        f"{API}/auth/register/parent",
        json={
            "link_code": code.json()["code"],
            "name": "Mum",
            "email": "mum@example.com",
            "password": "password123",
        },
    )
    assert parent.status_code == 201, parent.text
    parent_headers = {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"}

    for headers in (student["headers"], parent_headers):
        resp = await client.get(f"{API}/students/{sid}/crm", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["notes"] == []
        assert resp.json()["communications"] == []

    mine = (await client.get(f"{API}/students/{sid}/crm", headers=tutor["headers"])).json()
    assert [n["body"] for n in mine["notes"]] == ["private note"]
    assert [c["body"] for c in mine["communications"]] == ["called mum"]
