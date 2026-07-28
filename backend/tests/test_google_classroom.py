"""Google Classroom import, against a fake Google.

Every Classroom/Drive call goes through httpx, so an httpx.MockTransport gives
full coverage of the import logic without touching the network.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import ImportOutcome, ImportRunStatus
from app.services.google_matching import suggest_matches
from app.workers.jobs import process_one_job

# The homework fixtures build the class/student/assignment chain.
from tests.test_homework import (  # noqa: F401
    PNG_BYTES,
    classified,
    fake_marking,
    group,
    published_assignment,
    student,
    subject,
)

COURSE_ID = "course-1"
COURSEWORK_ID = "cw-1"
GOOGLE_USER = "gstudent-1"
PNG = b"\x89PNG\r\n\x1a\n fake drive image"


@pytest.fixture(autouse=True)
def google_settings(monkeypatch):
    """Configure the integration and reset the cached Settings."""
    from cryptography.fernet import Fernet

    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def fake_google(
    *,
    submissions: list[dict] | None = None,
    roster: list[dict] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/studentSubmissions"):
            return httpx.Response(200, json={"studentSubmissions": submissions or []})
        if path.endswith("/students"):
            return httpx.Response(200, json={"students": roster or []})
        if path.endswith("/courses"):
            return httpx.Response(
                200, json={"courses": [{"id": COURSE_ID, "name": "Chemistry 10A"}]}
            )
        if path.endswith("/courseWork"):
            return httpx.Response(
                200, json={"courseWork": [{"id": COURSEWORK_ID, "title": "Worksheet 3"}]}
            )
        if "/drive/v3/files/" in path:
            if request.url.params.get("alt") == "media" or path.endswith("/export"):
                return httpx.Response(200, content=PNG)
            return httpx.Response(
                200,
                json={
                    "id": "drive-1",
                    "name": "answers.png",
                    "mimeType": "image/png",
                    "size": str(len(PNG)),
                },
            )
        return httpx.Response(404, json={"error": f"unexpected {path}"})

    return httpx.MockTransport(handler)


# Captured once, before any patching, so re-installing a transport mid-test
# replaces the previous one instead of wrapping it (which would let the earlier
# transport win).
_REAL_ASYNC_CLIENT_INIT = httpx.AsyncClient.__init__


@pytest.fixture
def patch_google(monkeypatch):
    """Route every httpx.AsyncClient in the app at the fake Google."""

    def install(transport: httpx.MockTransport):
        def patched(self, *args, **kwargs):
            kwargs["transport"] = transport
            _REAL_ASYNC_CLIENT_INIT(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    return install


async def connect_google(tutor_id: int) -> int:
    """Insert a connected account directly; the OAuth dance is Google's side."""
    from app.db import async_session
    from app.models import GoogleAccount
    from app.services.google_oauth import SCOPES, encrypt_token

    async with async_session() as session:
        account = GoogleAccount(
            tutor_id=tutor_id,
            google_sub="sub-1",
            google_email="tutor@school.org",
            access_token=encrypt_token("access-token"),
            refresh_token=encrypt_token("refresh-token"),
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=" ".join(SCOPES),
        )
        session.add(account)
        await session.commit()
        return account.id


def gc_submission(state="TURNED_IN", *, user=GOOGLE_USER, attachments=None, updated=None):
    return {
        "id": f"gcs-{user}",
        "userId": user,
        "state": state,
        "updateTime": updated or "2026-07-20T10:00:00Z",
        "assignmentSubmission": {
            "attachments": attachments
            if attachments is not None
            else [{"driveFile": {"id": "drive-1", "title": "answers.png"}}]
        },
    }


async def link_course_and_student(client, tutor, group, student, patch_google):
    patch_google(fake_google(roster=[
        {
            "userId": GOOGLE_USER,
            "profile": {"name": {"fullName": "Sara"}, "emailAddress": "sara@example.com"},
        }
    ]))
    await connect_google(tutor["user"]["id"])
    link = await client.post(
        "/api/v1/google/course-links",
        json={"course_id": COURSE_ID, "group_id": group["id"]},
        headers=tutor["headers"],
    )
    assert link.status_code == 201, link.text
    link_id = link.json()["id"]

    roster = await client.get(
        f"/api/v1/google/course-links/{link_id}/roster", headers=tutor["headers"]
    )
    entry = roster.json()["classroom_students"][0]
    # Matching suggests, but never commits on its own.
    assert entry["suggested_student_id"] == student["user"]["id"]
    assert entry["mapped_student_id"] is None

    saved = await client.put(
        f"/api/v1/google/course-links/{link_id}/roster",
        json=[{"google_user_id": GOOGLE_USER, "student_id": student["user"]["id"]}],
        headers=tutor["headers"],
    )
    assert saved.status_code == 200
    assert saved.json()["classroom_students"][0]["mapped_student_id"] == student["user"]["id"]
    return link_id


async def test_import_lands_in_the_normal_marking_pipeline(
    client, tutor, student, group, published_assignment, patch_google, monkeypatch
):
    link_id = await link_course_and_student(client, tutor, group, student, patch_google)
    patch_google(fake_google(submissions=[gc_submission()]))

    start = await client.post(
        f"/api/v1/google/course-links/{link_id}/coursework/{COURSEWORK_ID}/import",
        json={"assignment_id": published_assignment["id"]},
        headers=tutor["headers"],
    )
    assert start.status_code == 201, start.text
    run_id = start.json()["id"]

    assert await process_one_job() is True  # the import
    run = await client.get(f"/api/v1/google/import-runs/{run_id}", headers=tutor["headers"])
    assert run.json()["status"] == ImportRunStatus.done.value
    assert run.json()["imported"] == 1
    assert run.json()["results"][0]["outcome"] == ImportOutcome.imported.value

    # It became an ordinary submission, queued for the same AI marking.
    subs = await client.get(
        f"/api/v1/assignments/{published_assignment['id']}/submissions", headers=tutor["headers"]
    )
    assert len(subs.json()) == 1
    assert subs.json()[0]["student_name"] == "Sara"

    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    assert await process_one_job() is True  # the marking job the import queued
    subs = await client.get(
        f"/api/v1/assignments/{published_assignment['id']}/submissions", headers=tutor["headers"]
    )
    assert subs.json()[0]["status"] == "ai_marked"


async def test_reimport_does_not_duplicate(
    client, tutor, student, group, published_assignment, patch_google
):
    link_id = await link_course_and_student(client, tutor, group, student, patch_google)
    patch_google(fake_google(submissions=[gc_submission()]))
    url = f"/api/v1/google/course-links/{link_id}/coursework/{COURSEWORK_ID}/import"

    for _ in range(2):
        resp = await client.post(
            url, json={"assignment_id": published_assignment["id"]}, headers=tutor["headers"]
        )
        assert resp.status_code == 201, resp.text
        assert await process_one_job() is True

    subs = await client.get(
        f"/api/v1/assignments/{published_assignment['id']}/submissions", headers=tutor["headers"]
    )
    assert len(subs.json()) == 1, "re-running the import must not duplicate the submission"


async def test_unmapped_and_not_turned_in_are_reported_not_guessed(
    client, tutor, student, group, published_assignment, patch_google
):
    link_id = await link_course_and_student(client, tutor, group, student, patch_google)
    patch_google(
        fake_google(
            submissions=[
                gc_submission(state="CREATED"),
                gc_submission(user="gstudent-unknown"),
            ]
        )
    )
    start = await client.post(
        f"/api/v1/google/course-links/{link_id}/coursework/{COURSEWORK_ID}/import",
        json={"assignment_id": published_assignment["id"]},
        headers=tutor["headers"],
    )
    assert await process_one_job() is True
    run = await client.get(
        f"/api/v1/google/import-runs/{start.json()['id']}", headers=tutor["headers"]
    )
    outcomes = {r["outcome"] for r in run.json()["results"]}
    assert outcomes == {
        ImportOutcome.skipped_not_turned_in.value,
        ImportOutcome.skipped_unmapped.value,
    }
    assert run.json()["imported"] == 0


async def test_import_requires_a_published_assignment(
    client, tutor, student, group, classified, subject, patch_google, monkeypatch
):
    """Marking against an assignment with no questions would produce nothing."""
    monkeypatch.setattr(
        "app.services.extraction._run_extraction", lambda session, assignment: _noop()
    )
    link_id = await link_course_and_student(client, tutor, group, student, patch_google)
    draft = await client.post(
        "/api/v1/assignments",
        json={
            "group_id": group["id"],
            "classified_id": classified["id"],
            "title": "Not published",
        },
        headers=tutor["headers"],
    )
    resp = await client.post(
        f"/api/v1/google/course-links/{link_id}/coursework/{COURSEWORK_ID}/import",
        json={"assignment_id": draft.json()["id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 409


async def _noop():
    return None


async def test_import_needs_a_connected_account(client, tutor, group, published_assignment):
    resp = await client.get("/api/v1/google/courses", headers=tutor["headers"])
    assert resp.status_code == 409
    assert "Connect your Google account" in resp.json()["detail"]


async def test_account_reports_missing_permissions(client, tutor):
    """Google's consent screen lets users untick scopes; that must surface."""
    from app.db import async_session
    from app.models import GoogleAccount, GoogleAccountStatus
    from app.services.google_oauth import encrypt_token

    async with async_session() as session:
        session.add(
            GoogleAccount(
                tutor_id=tutor["user"]["id"],
                google_sub="sub-1",
                google_email="tutor@school.org",
                access_token=encrypt_token("access-token"),
                refresh_token=encrypt_token("refresh-token"),
                scopes="https://www.googleapis.com/auth/classroom.courses.readonly",
                status=GoogleAccountStatus.needs_reauth,
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/google/account", headers=tutor["headers"])
    body = resp.json()
    assert body["connected"] is True
    assert any("drive.readonly" in s for s in body["missing_scopes"])


def test_matching_never_guesses_between_two_similar_names():
    from app.models import User

    members = [
        User(id=1, name="Ahmed Ali", email=None, role="student"),
        User(id=2, name="Ahmed Ali", email=None, role="student"),
    ]
    assert suggest_matches([{"id": "g1", "name": "Ahmed Ali", "email": None}], members) == {}


def test_matching_handles_reordered_names_and_prefers_email():
    from app.models import User

    members = [
        User(id=1, name="Ahmed Hassan Ali", email=None, role="student"),
        User(id=2, name="Sara Khan", email="sara@example.com", role="student"),
    ]
    google = [
        {"id": "g1", "name": "Ali, Ahmed", "email": None},
        {"id": "g2", "name": "Totally Different", "email": "sara@example.com"},
    ]
    assert suggest_matches(google, members) == {"g2": 2, "g1": 1}
