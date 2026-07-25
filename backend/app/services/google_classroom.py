"""Google Classroom integration: per-tutor OAuth + a polling sync job that
imports courseWork (as draft Assignments) and turned-in student submissions
into the standard marking pipeline (see services/marking.py). Classroom
reduces friction for a tutor who already teaches through it — it never
replaces direct upload, which remains fully supported either way.

Every Google API call goes through the small, individually-mockable
functions below (mirroring services/ai.py's get_client() choke point), so
the OAuth flow and sync job are fully testable without real Google
credentials. The feature degrades gracefully when GOOGLE_CLIENT_ID /
GOOGLE_CLIENT_SECRET aren't set — see GoogleClassroomUnavailableError.
"""

import base64
import hashlib
from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Assignment,
    AssignmentStatus,
    ClassroomCourseLink,
    ClassroomWorkLink,
    GoogleAccount,
    Group,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
    UserRole,
)
from app.services import storage
from app.workers.jobs import enqueue

AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
CLASSROOM_API_BASE = "https://classroom.googleapis.com/v1"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
HTTP_TIMEOUT = 20.0

# Read-only throughout: MANARA only ever imports from Classroom, it never
# writes back to a tutor's Google account.
SCOPES = (
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
)

# States a student submission must be in on Classroom's side before it's
# worth importing — anything else has nothing to mark yet.
_TURNED_IN_STATES = ("TURNED_IN", "RETURNED")


class GoogleClassroomUnavailableError(RuntimeError):
    """Raised when Classroom features are used without Google OAuth
    configured — mirrors services/ai.py's AIUnavailableError. The app runs
    fine without it; Classroom features just report a clear error."""


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def _oauth_config() -> tuple[str, str, str]:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleClassroomUnavailableError(
            "Google Classroom is not configured: set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in the backend environment"
        )
    return settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri


def _fernet() -> Fernet:
    settings = get_settings()
    material = (settings.google_token_encryption_key or settings.jwt_secret).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def build_auth_url(state: str) -> str:
    client_id, _, redirect_uri = _oauth_config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return str(httpx.URL(AUTH_BASE_URL, params=params))


# --- Thin, individually-mockable wrappers around Google's REST APIs -------


async def exchange_code(code: str) -> dict:
    client_id, client_secret, redirect_uri = _oauth_config()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> str:
    client_id, client_secret, _ = _oauth_config()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def fetch_google_email(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()["email"]


async def list_courses(access_token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(
            f"{CLASSROOM_API_BASE}/courses",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"courseStates": "ACTIVE", "teacherId": "me"},
        )
        resp.raise_for_status()
        return resp.json().get("courses", [])


async def list_coursework(access_token: str, course_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(
            f"{CLASSROOM_API_BASE}/courses/{course_id}/courseWork",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json().get("courseWork", [])


async def list_student_submissions(access_token: str, course_id: str, coursework_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(
            f"{CLASSROOM_API_BASE}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json().get("studentSubmissions", [])


async def get_student_profile(access_token: str, course_id: str, user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(
            f"{CLASSROOM_API_BASE}/courses/{course_id}/students/{user_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_drive_file_metadata(access_token: str, file_id: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        resp = await http.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,name,mimeType"},
        )
        resp.raise_for_status()
        return resp.json()


async def download_drive_file(access_token: str, file_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT * 2) as http:
        resp = await http.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"alt": "media"},
        )
        resp.raise_for_status()
        return resp.content


# --- Account connection -----------------------------------------------------


async def get_valid_access_token(account: GoogleAccount) -> str:
    return await refresh_access_token(decrypt_token(account.encrypted_refresh_token))


async def connect_account(
    session: AsyncSession, *, organization_id: int, tutor_id: int, code: str
) -> GoogleAccount:
    """Exchange an OAuth authorization code for tokens and upsert this
    tutor's GoogleAccount. Google only returns a refresh_token on the first
    consent (or when prompt=consent forces re-consent, which build_auth_url
    always requests) — an existing connection's refresh token is kept if a
    later exchange doesn't return a new one."""
    tokens = await exchange_code(code)
    access_token = tokens["access_token"]
    email = await fetch_google_email(access_token)
    refresh_token = tokens.get("refresh_token")

    account = await session.scalar(select(GoogleAccount).where(GoogleAccount.tutor_id == tutor_id))
    if account is None:
        if not refresh_token:
            raise GoogleClassroomUnavailableError(
                "Google did not return a refresh token — reconnect and approve offline access"
            )
        account = GoogleAccount(
            organization_id=organization_id,
            tutor_id=tutor_id,
            google_email=email,
            encrypted_refresh_token=encrypt_token(refresh_token),
            scopes=tokens.get("scope", ""),
            connected_at=datetime.now(timezone.utc),
        )
        session.add(account)
    else:
        if refresh_token:
            account.encrypted_refresh_token = encrypt_token(refresh_token)
        account.google_email = email
        account.scopes = tokens.get("scope", "")
        account.connected_at = datetime.now(timezone.utc)
    await session.flush()
    return account


# --- Sync job ----------------------------------------------------------------


async def sync_classroom(session: AsyncSession, payload: dict) -> None:
    """Poll every course a tutor has linked: import new courseWork as draft
    Assignments and new turned-in submissions into the standard marking
    pipeline. Enqueued on demand today (see api/classroom.py's POST /sync);
    a scheduler could call the same job type periodically without any
    handler changes."""
    account = await session.get(GoogleAccount, payload["google_account_id"])
    if account is None:
        return
    access_token = await get_valid_access_token(account)

    links = (
        await session.scalars(
            select(ClassroomCourseLink).where(ClassroomCourseLink.google_account_id == account.id)
        )
    ).all()
    for link in links:
        await _sync_course(session, access_token, link)


async def _sync_course(session: AsyncSession, access_token: str, link: ClassroomCourseLink) -> None:
    group = await session.get(Group, link.group_id)
    for cw in await list_coursework(access_token, link.classroom_course_id):
        work_link = await session.scalar(
            select(ClassroomWorkLink).where(
                ClassroomWorkLink.course_link_id == link.id,
                ClassroomWorkLink.classroom_coursework_id == cw["id"],
            )
        )
        if work_link is None:
            assignment = Assignment(
                group_id=group.id,
                title=cw.get("title", "Classroom assignment")[:255],
                instructions=cw.get("description"),
                status=AssignmentStatus.review,
            )
            session.add(assignment)
            await session.flush()
            work_link = ClassroomWorkLink(
                course_link_id=link.id,
                assignment_id=assignment.id,
                classroom_coursework_id=cw["id"],
            )
            session.add(work_link)
            await session.flush()
        else:
            assignment = await session.get(Assignment, work_link.assignment_id)

        await _sync_submissions(session, access_token, link, work_link, assignment)

    link.last_synced_at = datetime.now(timezone.utc)


async def _sync_submissions(
    session: AsyncSession,
    access_token: str,
    link: ClassroomCourseLink,
    work_link: ClassroomWorkLink,
    assignment: Assignment,
) -> None:
    submissions = await list_student_submissions(
        access_token, link.classroom_course_id, work_link.classroom_coursework_id
    )
    for sub in submissions:
        if sub.get("state") not in _TURNED_IN_STATES:
            continue

        profile = await get_student_profile(access_token, link.classroom_course_id, sub["userId"])
        student_email = profile.get("profile", {}).get("emailAddress")
        if not student_email:
            continue
        student = await session.scalar(
            select(User).where(User.email == student_email, User.role == UserRole.student)
        )
        if student is None:
            continue  # no MANARA student account matches this Classroom roster email yet

        existing = await session.scalar(
            select(Submission).where(
                Submission.assignment_id == assignment.id, Submission.student_id == student.id
            )
        )
        if existing is not None:
            continue  # already imported — re-polling is idempotent

        files = await _download_attachments(access_token, sub)
        submission = Submission(
            assignment_id=assignment.id, student_id=student.id, status=SubmissionStatus.submitted
        )
        session.add(submission)
        await session.flush()
        for position, (path, name, mime) in enumerate(files):
            session.add(
                SubmissionFile(
                    submission_id=submission.id, position=position, path=path, name=name, mime=mime
                )
            )
        if files:
            await enqueue(session, "mark_submission", {"submission_id": submission.id})


async def _download_attachments(access_token: str, sub: dict) -> list[tuple[str, str, str]]:
    files: list[tuple[str, str, str]] = []
    attachments = sub.get("assignmentSubmission", {}).get("attachments", [])
    for attachment in attachments:
        drive_file = attachment.get("driveFile")
        if drive_file is None:
            continue  # links, Docs, etc. — not something we can hand to the marker as-is
        meta = await get_drive_file_metadata(access_token, drive_file["id"])
        mime = meta.get("mimeType", "")
        if mime not in storage.ALLOWED_MIMES:
            continue  # e.g. a native Google Doc — the tutor uploads it directly instead
        data = await download_drive_file(access_token, drive_file["id"])
        try:
            files.append(storage.save_bytes(data, mime, meta.get("name", drive_file["id"])))
        except ValueError:
            continue  # e.g. over the 20MB cap
    return files
