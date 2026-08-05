"""Student CRM: profile, subject enrollments, notes, parent communications,
and the aggregated /students/{id}/crm endpoint."""

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

    resp = await client.get(
        f"/api/v1/students/{world['student_id']}/crm", headers=tutor["headers"]
    )
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


async def test_crm_access_control(client, tutor, world):
    other_tutor = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-crm@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other_tutor.json()['tokens']['access_token']}"}

    # A tutor who doesn't teach this student can't view or edit their CRM record.
    view = await client.get(
        f"/api/v1/students/{world['student_id']}/crm", headers=other_headers
    )
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
    bob_headers = {
        "Authorization": f"Bearer {login.json()['tokens']['access_token']}"
    }
    forbidden = await client.get(
        f"/api/v1/students/{world['student_id']}/crm", headers=bob_headers
    )
    assert forbidden.status_code == 403
