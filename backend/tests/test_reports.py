import pytest

from app.db import async_session
from app.workers.jobs import process_one_job


@pytest.fixture
async def world(client, tutor):
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
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    # Link a parent.
    code = (
        await client.post(
            f"/api/v1/students/{student['id']}/parent-code", headers=tutor["headers"]
        )
    ).json()["code"]
    parent = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Parent",
            "email": "parent@example.com",
            "password": "password123",
        },
    )
    return {
        "subject_id": subject_id,
        "group": group,
        "student_id": student["id"],
        "parent_headers": {
            "Authorization": f"Bearer {parent.json()['tokens']['access_token']}"
        },
    }


async def fake_write(audience, facts):
    return "# Progress report\n\nYour child is making steady progress."


async def test_tutor_generates_parent_report(client, tutor, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "generating"
    report_id = resp.json()["id"]

    assert await process_one_job() is True

    detail = await client.get(f"/api/v1/reports/{report_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "ready"
    assert "progress" in detail.json()["content"].lower()


async def test_parent_sees_only_parent_reports(client, tutor, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    # Tutor generates a parent report and a tutor report.
    await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "tutor"},
        headers=tutor["headers"],
    )
    await process_one_job()
    await process_one_job()

    listing = await client.get(
        f"/api/v1/reports?student_id={world['student_id']}", headers=world["parent_headers"]
    )
    assert listing.status_code == 200
    audiences = {r["audience"] for r in listing.json()}
    assert audiences == {"parent"}


async def test_parent_can_generate_own_report(client, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=world["parent_headers"],
    )
    assert resp.status_code == 201


async def test_parent_cannot_generate_tutor_report(client, world):
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "tutor"},
        headers=world["parent_headers"],
    )
    assert resp.status_code == 403


async def test_report_generation_fails_gracefully(client, tutor, world):
    # No API key configured -> the real generator should fail the report.
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    report_id = resp.json()["id"]
    await process_one_job()
    await process_one_job()  # retry
    detail = await client.get(f"/api/v1/reports/{report_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "failed"
    assert "ANTHROPIC_API_KEY" in detail.json()["error"]


async def test_unrelated_parent_cannot_generate(client, tutor, world):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=headers,
    )
    # A tutor who doesn't teach this student cannot see them.
    assert resp.status_code in (403, 404)
