"""Google Classroom integration: OAuth connect/disconnect, course linking,
and the sync_classroom job — all driven against monkeypatched Google API
calls (mirroring how test_homework.py fakes get_client()), so nothing here
needs real Google credentials."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import (
    Assignment,
    ClassroomCourseLink,
    ClassroomWorkLink,
    GoogleAccount,
    Submission,
    SubmissionFile,
    User,
)
from app.workers.jobs import process_one_job

PDF_BYTES = b"%PDF-1.4 fake classroom pdf"


@pytest.fixture(autouse=True)
def _google_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


@pytest.fixture
async def subject(client, tutor):
    from app.models import Subject, Topic

    async with async_session() as session:
        s = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(s)
        await session.flush()
        session.add(Topic(subject_id=s.id, code="1.3", title="Atomic structure"))
        await session.commit()
        return {"id": s.id}


@pytest.fixture
async def group(client, tutor, subject):
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    return resp.json()


@pytest.fixture
async def student(client, tutor, group):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara-classroom@example.com",
            "password": "password123",
        },
    )
    return resp.json()


async def _fake_exchange_code(code: str) -> dict:
    return {"access_token": "fake-access", "refresh_token": "fake-refresh", "scope": "classroom.readonly"}


async def _fake_fetch_email(access_token: str) -> str:
    return "tutor@gmail.com"


async def _fake_refresh_access_token(refresh_token: str) -> str:
    return "fresh-access-token"


async def _connect(client, tutor, monkeypatch) -> None:
    monkeypatch.setattr("app.services.google_classroom.exchange_code", _fake_exchange_code)
    monkeypatch.setattr("app.services.google_classroom.fetch_google_email", _fake_fetch_email)
    resp = await client.post("/api/v1/classroom/connect", json={"code": "auth-code"}, headers=tutor["headers"])
    assert resp.status_code == 201, resp.text


async def test_status_not_configured_without_credentials(client, tutor, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)

    resp = await client.get("/api/v1/classroom/status", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["connected"] is False

    auth = await client.get("/api/v1/classroom/auth-url", headers=tutor["headers"])
    assert auth.status_code == 503


async def test_auth_url_configured(client, tutor):
    resp = await client.get("/api/v1/classroom/auth-url", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state" in body


async def test_connect_status_disconnect(client, tutor, monkeypatch):
    await _connect(client, tutor, monkeypatch)

    status_resp = await client.get("/api/v1/classroom/status", headers=tutor["headers"])
    body = status_resp.json()
    assert body["connected"] is True
    assert body["google_email"] == "tutor@gmail.com"

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        account = await session.scalar(
            select(GoogleAccount).where(GoogleAccount.tutor_id == tutor_user.id)
        )
        assert account is not None
        assert account.encrypted_refresh_token != "fake-refresh"  # stored encrypted, not plaintext

    disconnect = await client.delete("/api/v1/classroom/account", headers=tutor["headers"])
    assert disconnect.status_code == 204

    status_resp2 = await client.get("/api/v1/classroom/status", headers=tutor["headers"])
    assert status_resp2.json()["connected"] is False


async def test_connect_without_refresh_token_fails(client, tutor, monkeypatch):
    async def fake_exchange_no_refresh(code: str) -> dict:
        return {"access_token": "fake-access", "scope": "classroom.readonly"}

    monkeypatch.setattr("app.services.google_classroom.exchange_code", fake_exchange_no_refresh)
    monkeypatch.setattr("app.services.google_classroom.fetch_google_email", _fake_fetch_email)
    resp = await client.post("/api/v1/classroom/connect", json={"code": "x"}, headers=tutor["headers"])
    assert resp.status_code == 503


async def test_list_courses_and_link_lifecycle(client, tutor, group, monkeypatch):
    await _connect(client, tutor, monkeypatch)

    async def fake_refresh(refresh_token: str) -> str:
        return "fresh-access-token"

    async def fake_list_courses(access_token: str) -> list[dict]:
        assert access_token == "fresh-access-token"
        return [{"id": "course-1", "name": "Period 3 Chemistry"}]

    monkeypatch.setattr("app.services.google_classroom.refresh_access_token", fake_refresh)
    monkeypatch.setattr("app.services.google_classroom.list_courses", fake_list_courses)

    courses = await client.get("/api/v1/classroom/courses", headers=tutor["headers"])
    assert courses.status_code == 200
    assert courses.json() == [{"id": "course-1", "name": "Period 3 Chemistry"}]

    link = await client.post(
        "/api/v1/classroom/links",
        json={"group_id": group["id"], "classroom_course_id": "course-1", "classroom_course_name": "Period 3 Chemistry"},
        headers=tutor["headers"],
    )
    assert link.status_code == 201, link.text
    link_id = link.json()["id"]

    listing = await client.get("/api/v1/classroom/links", headers=tutor["headers"])
    assert len(listing.json()) == 1
    assert listing.json()[0]["group_id"] == group["id"]

    deleted = await client.delete(f"/api/v1/classroom/links/{link_id}", headers=tutor["headers"])
    assert deleted.status_code == 204
    listing2 = await client.get("/api/v1/classroom/links", headers=tutor["headers"])
    assert listing2.json() == []


async def test_courses_requires_connection(client, tutor):
    resp = await client.get("/api/v1/classroom/courses", headers=tutor["headers"])
    assert resp.status_code == 404


async def test_sync_imports_coursework_and_submission_with_attachment(
    client, tutor, group, student, monkeypatch
):
    await _connect(client, tutor, monkeypatch)
    monkeypatch.setattr(
        "app.services.google_classroom.refresh_access_token", _fake_refresh_access_token
    )

    link = await client.post(
        "/api/v1/classroom/links",
        json={"group_id": group["id"], "classroom_course_id": "course-1", "classroom_course_name": "Period 3"},
        headers=tutor["headers"],
    )
    assert link.status_code == 201

    async def fake_list_coursework(access_token, course_id):
        assert course_id == "course-1"
        return [{"id": "cw-1", "title": "Worksheet 1", "description": "Atomic structure practice"}]

    async def fake_list_submissions(access_token, course_id, coursework_id):
        assert coursework_id == "cw-1"
        return [
            {
                "userId": "google-user-1",
                "state": "TURNED_IN",
                "assignmentSubmission": {
                    "attachments": [{"driveFile": {"id": "drive-file-1"}}]
                },
            }
        ]

    async def fake_student_profile(access_token, course_id, user_id):
        assert user_id == "google-user-1"
        return {"profile": {"emailAddress": "sara-classroom@example.com"}}

    async def fake_drive_metadata(access_token, file_id):
        assert file_id == "drive-file-1"
        return {"id": file_id, "name": "answers.pdf", "mimeType": "application/pdf"}

    async def fake_download(access_token, file_id):
        return PDF_BYTES

    monkeypatch.setattr("app.services.google_classroom.list_coursework", fake_list_coursework)
    monkeypatch.setattr("app.services.google_classroom.list_student_submissions", fake_list_submissions)
    monkeypatch.setattr("app.services.google_classroom.get_student_profile", fake_student_profile)
    monkeypatch.setattr("app.services.google_classroom.get_drive_file_metadata", fake_drive_metadata)
    monkeypatch.setattr("app.services.google_classroom.download_drive_file", fake_download)

    sync = await client.post("/api/v1/classroom/sync", headers=tutor["headers"])
    assert sync.status_code == 202
    assert await process_one_job() is True  # sync_classroom

    async with async_session() as session:
        assignment = await session.scalar(select(Assignment).where(Assignment.title == "Worksheet 1"))
        assert assignment is not None
        assert assignment.group_id == group["id"]

        work_link = await session.scalar(
            select(ClassroomWorkLink).where(ClassroomWorkLink.assignment_id == assignment.id)
        )
        assert work_link is not None
        assert work_link.classroom_coursework_id == "cw-1"

        student_user = await session.scalar(
            select(User).where(User.email == "sara-classroom@example.com")
        )
        submission = await session.scalar(
            select(Submission).where(
                Submission.assignment_id == assignment.id, Submission.student_id == student_user.id
            )
        )
        assert submission is not None
        files = (
            await session.scalars(
                select(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
            )
        ).all()
        assert len(files) == 1
        assert files[0].mime == "application/pdf"

        course_link = await session.scalar(select(ClassroomCourseLink))
        assert course_link.last_synced_at is not None

    # A mark_submission job was enqueued since a file was attached — running
    # it will fail gracefully (no ANTHROPIC_API_KEY in tests), same as any
    # other AI job, but it must not crash the pipeline.
    assert await process_one_job() is True

    # Re-syncing must not duplicate the assignment or the submission.
    sync2 = await client.post("/api/v1/classroom/sync", headers=tutor["headers"])
    assert sync2.status_code == 202
    assert await process_one_job() is True
    async with async_session() as session:
        assignments = (await session.scalars(select(Assignment))).all()
        submissions = (await session.scalars(select(Submission))).all()
        assert len(assignments) == 1
        assert len(submissions) == 1


async def test_sync_skips_submission_with_no_matching_student(client, tutor, group, monkeypatch):
    await _connect(client, tutor, monkeypatch)
    monkeypatch.setattr(
        "app.services.google_classroom.refresh_access_token", _fake_refresh_access_token
    )
    await client.post(
        "/api/v1/classroom/links",
        json={"group_id": group["id"], "classroom_course_id": "course-1", "classroom_course_name": "Period 3"},
        headers=tutor["headers"],
    )

    async def fake_list_coursework(access_token, course_id):
        return [{"id": "cw-1", "title": "Worksheet 1"}]

    async def fake_list_submissions(access_token, course_id, coursework_id):
        return [{"userId": "google-user-unknown", "state": "TURNED_IN", "assignmentSubmission": {}}]

    async def fake_student_profile(access_token, course_id, user_id):
        return {"profile": {"emailAddress": "not-a-manara-student@example.com"}}

    monkeypatch.setattr("app.services.google_classroom.list_coursework", fake_list_coursework)
    monkeypatch.setattr("app.services.google_classroom.list_student_submissions", fake_list_submissions)
    monkeypatch.setattr("app.services.google_classroom.get_student_profile", fake_student_profile)

    await client.post("/api/v1/classroom/sync", headers=tutor["headers"])
    assert await process_one_job() is True

    async with async_session() as session:
        assignment = await session.scalar(select(Assignment).where(Assignment.title == "Worksheet 1"))
        assert assignment is not None  # the draft assignment still gets created
        submissions = (await session.scalars(select(Submission))).all()
        assert submissions == []  # but no submission — no matching student account


async def test_classroom_forbidden_for_students(client, tutor, group, student):
    student_headers = {"Authorization": f"Bearer {student['tokens']['access_token']}"}
    resp = await client.get("/api/v1/classroom/status", headers=student_headers)
    assert resp.status_code == 403


async def test_classroom_access_control_across_tutors(client, tutor, group, monkeypatch):
    await _connect(client, tutor, monkeypatch)
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-classroom@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    resp = await client.get("/api/v1/classroom/status", headers=other_headers)
    assert resp.json()["connected"] is False

    resp2 = await client.post(
        "/api/v1/classroom/links",
        json={"group_id": group["id"], "classroom_course_id": "x", "classroom_course_name": "x"},
        headers=other_headers,
    )
    assert resp2.status_code == 404  # not connected
