"""Student CRM: profile, subject enrollments, notes, parent communications,
and the aggregated /students/{id}/crm endpoint."""

from app.db import async_session
from tests.factories import write_v2_snapshot
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_profile_upsert(client, tutor, world):
    resp = await client.put(
        f"/api/v1/students/{world['student_id']}/profile",
        json={
            "school": "Greenwood High",
            "year_group": "Year 10",
            "parent_name": "Mr Parent",
            "parent_email": "parent@example.com",
            "parent_phone": "+44 7000 000000",
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["school"] == "Greenwood High"
    assert body["year_group"] == "Year 10"
    assert body["parent_email"] == "parent@example.com"

    # A second PUT replaces the row rather than creating a new one.
    resp2 = await client.put(
        f"/api/v1/students/{world['student_id']}/profile",
        json={"school": "New School"},
        headers=tutor["headers"],
    )
    assert resp2.status_code == 200
    assert resp2.json()["school"] == "New School"
    assert resp2.json()["year_group"] is None


async def test_enroll_subject_and_crud(client, tutor, world):
    resp = await client.post(
        f"/api/v1/students/{world['student_id']}/subjects",
        json={"subject_id": world["subject_id"], "target_grade": "8"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["target_grade"] == "8"

    # Duplicate enrollment is rejected.
    dup = await client.post(
        f"/api/v1/students/{world['student_id']}/subjects",
        json={"subject_id": world["subject_id"], "target_grade": "9"},
        headers=tutor["headers"],
    )
    assert dup.status_code == 409

    # Update the target grade.
    patched = await client.patch(
        f"/api/v1/students/{world['student_id']}/subjects/{world['subject_id']}",
        json={"target_grade": "9"},
        headers=tutor["headers"],
    )
    assert patched.status_code == 200
    assert patched.json()["target_grade"] == "9"

    # Remove it.
    deleted = await client.delete(
        f"/api/v1/students/{world['student_id']}/subjects/{world['subject_id']}",
        headers=tutor["headers"],
    )
    assert deleted.status_code == 204


async def test_notes_and_communications(client, tutor, world):
    note = await client.post(
        f"/api/v1/students/{world['student_id']}/notes",
        json={"body": "Struggles with ionic bonding, needs more practice."},
        headers=tutor["headers"],
    )
    assert note.status_code == 201
    assert note.json()["tutor_name"] == "Test Tutor"

    comm = await client.post(
        f"/api/v1/students/{world['student_id']}/communications",
        json={"body": "Called parent to discuss progress."},
        headers=tutor["headers"],
    )
    assert comm.status_code == 201
    assert comm.json()["body"] == "Called parent to discuss progress."


async def test_crm_aggregate_endpoint(client, tutor, world):
    await client.put(
        f"/api/v1/students/{world['student_id']}/profile",
        json={"school": "Greenwood High"},
        headers=tutor["headers"],
    )
    await client.post(
        f"/api/v1/students/{world['student_id']}/subjects",
        json={"subject_id": world["subject_id"], "target_grade": "8"},
        headers=tutor["headers"],
    )
    await client.post(
        f"/api/v1/students/{world['student_id']}/notes",
        json={"body": "Doing well overall."},
        headers=tutor["headers"],
    )
    await client.post(
        f"/api/v1/students/{world['student_id']}/communications",
        json={"body": "Emailed parent the monthly report."},
        headers=tutor["headers"],
    )

    resp = await client.get(f"/api/v1/students/{world['student_id']}/crm", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["student_name"] == "Sara"
    assert body["profile"]["school"] == "Greenwood High"
    assert len(body["enrollments"]) == 1
    assert body["enrollments"][0]["target_grade"] == "8"
    assert len(body["notes"]) == 1
    assert len(body["communications"]) == 1
    assert any(s["subject_id"] == world["subject_id"] for s in body["readiness"])

    # The student can view their own CRM record too.
    own = await client.get(
        f"/api/v1/students/{world['student_id']}/crm", headers=world["student_headers"]
    )
    assert own.status_code == 200


async def test_crm_reads_v2_readiness(client, tutor, world):
    """The CRM's readiness list is served from build_summary_v2, not v1 —
    proves student_crm.py reads the same engine as the profile."""
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=66.0,
            predicted_grade="6",
        )
        await session.commit()

    resp = await client.get(f"/api/v1/students/{world['student_id']}/crm", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    subject = next(s for s in resp.json()["readiness"] if s["subject_id"] == world["subject_id"])
    assert subject["score"] == 66.0


async def test_crm_access_control(client, tutor, world):
    other_tutor = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-crm@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other_tutor.json()['tokens']['access_token']}"}

    # A tutor who doesn't teach this student can't view or edit their CRM record.
    view = await client.get(f"/api/v1/students/{world['student_id']}/crm", headers=other_headers)
    assert view.status_code == 404

    edit = await client.put(
        f"/api/v1/students/{world['student_id']}/profile",
        json={"school": "Nope"},
        headers=other_headers,
    )
    assert edit.status_code == 404

    # Another student can't view this student's CRM record.
    await client.post(
        f"/api/v1/groups/{world['group']['id']}/students",
        json={"name": "Bob", "username": "bob01", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "bob01", "password": "password123"}
    )
    bob_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    forbidden = await client.get(f"/api/v1/students/{world['student_id']}/crm", headers=bob_headers)
    assert forbidden.status_code == 404


async def test_profile_enrollments_are_the_class_subjects_with_targets_merged(client, tutor, world):
    """No StudentSubject row: the class still lists. With one: its target grade merges."""
    url = f"/api/v1/students/{world['student_id']}/crm"
    body = (await client.get(url, headers=tutor["headers"])).json()
    assert [(e["subject_id"], e["target_grade"]) for e in body["enrollments"]] == [
        (world["subject_id"], None)
    ]

    await client.post(
        f"/api/v1/students/{world['student_id']}/subjects",
        json={"subject_id": world["subject_id"], "target_grade": "8"},
        headers=tutor["headers"],
    )
    body = (await client.get(url, headers=tutor["headers"])).json()
    assert [(e["subject_id"], e["target_grade"]) for e in body["enrollments"]] == [
        (world["subject_id"], "8")
    ]


async def test_a_deleted_class_drops_out_of_the_profile_enrollments(client, tutor, world):
    """Another live class keeps the tutor teaching the student, so the profile
    opens; the deleted Chemistry class is simply not listed."""
    physics = await make_subject_group(client, tutor, world["student_id"])
    await client.delete(f"/api/v1/groups/{world['group']['id']}", headers=tutor["headers"])
    body = (
        await client.get(f"/api/v1/students/{world['student_id']}/crm", headers=tutor["headers"])
    ).json()
    assert [e["subject_id"] for e in body["enrollments"]] == [physics]


async def make_subject_group(client, tutor, student_id: int) -> int:
    from app.db import async_session
    from app.models import GroupMember
    from tests.factories import make_subject

    async with async_session() as session:
        subject = await make_subject(session, code="4PH1", name="Physics")
        await session.commit()
        subject_id = subject.id
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Phys", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        session.add(GroupMember(group_id=group["id"], student_id=student_id))
        await session.commit()
    return subject_id


async def test_a_student_sees_only_their_own_organizations_enrollments(client, tutor, world):
    """A class of another organization the student also sits in is not listed
    on their own profile (SEC-7)."""
    from sqlalchemy import select

    from app.models import Group, GroupMember, User
    from tests.factories import other_org_subject

    async with async_session() as session:
        foreign_subject = await other_org_subject(session)
        tutor_row = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        foreign = Group(
            organization_id=foreign_subject.organization_id,
            tutor_id=tutor_row.id,
            subject_id=foreign_subject.id,
            name="Foreign",
        )
        session.add(foreign)
        await session.flush()
        session.add(GroupMember(group_id=foreign.id, student_id=world["student_id"]))
        await session.commit()
        foreign_id = foreign_subject.id
    body = (
        await client.get(
            f"/api/v1/students/{world['student_id']}/crm", headers=world["student_headers"]
        )
    ).json()
    ids = [e["subject_id"] for e in body["enrollments"]]
    assert ids == [world["subject_id"]]
    assert foreign_id not in ids
