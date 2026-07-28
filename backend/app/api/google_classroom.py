"""Google Classroom: connect an account, link a course, import submissions."""

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.db import async_session
from app.models import (
    Assignment,
    AssignmentStatus,
    GoogleAccount,
    GoogleAccountStatus,
    GoogleCourseLink,
    GoogleCourseworkLink,
    GoogleImportRun,
    GoogleStudentLink,
    GoogleSubmissionImport,
    Group,
    GroupMember,
    ImportRunStatus,
    User,
    UserRole,
)
from app.schemas.google import (
    AuthorizeUrl,
    CourseLinkCreate,
    CourseLinkOut,
    GoogleAccountOut,
    GoogleCourse,
    GoogleCoursework,
    ImportRequest,
    ImportResultRow,
    ImportRunOut,
    RosterEntry,
    RosterMapping,
    RosterOut,
    UnmatchedStudent,
)
from app.services import google_api, google_oauth
from app.services.google_matching import suggest_matches
from app.workers.jobs import enqueue

router = APIRouter(prefix="/google", tags=["google"])


def _require_tutor(user: User) -> None:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


async def _account(db, user: User) -> GoogleAccount:
    account = await db.scalar(select(GoogleAccount).where(GoogleAccount.tutor_id == user.id))
    if account is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Connect your Google account first"
        )
    return account


async def _owned_course_link(db, user: User, link_id: int) -> GoogleCourseLink:
    link = await db.get(GoogleCourseLink, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    account = await db.get(GoogleAccount, link.account_id)
    if account.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    return link


@router.get("/account", response_model=GoogleAccountOut)
async def google_account(db: DbSession, user: CurrentUser) -> GoogleAccountOut:
    _require_tutor(user)
    configured = get_settings().google_enabled
    account = await db.scalar(select(GoogleAccount).where(GoogleAccount.tutor_id == user.id))
    if account is None:
        return GoogleAccountOut(connected=False, configured=configured)
    return GoogleAccountOut(
        connected=True,
        configured=configured,
        google_email=account.google_email,
        status=account.status.value,
        missing_scopes=google_oauth.missing_scopes(account.scopes),
        last_error=account.last_error,
        connected_at=account.created_at,
    )


@router.post("/oauth/start", response_model=AuthorizeUrl)
async def oauth_start(user: CurrentUser) -> AuthorizeUrl:
    _require_tutor(user)
    return AuthorizeUrl(authorize_url=google_oauth.authorize_url(user.id))


@router.get("/oauth/callback")
async def oauth_callback(state: str, code: str | None = None, error: str | None = None):
    """Google redirects the browser here — no auth header, so identity is in `state`."""
    frontend = get_settings().frontend_url
    if error:
        return RedirectResponse(f"{frontend}/tutor/integrations?google=error&reason={error}")

    tutor_id = google_oauth.read_state(state)
    if not code:
        return RedirectResponse(f"{frontend}/tutor/integrations?google=error&reason=no_code")

    tokens = await google_oauth.exchange_code(code)
    claims = google_oauth.id_token_claims(tokens["id_token"]) if tokens.get("id_token") else {}
    granted = tokens.get("scope", "")
    missing = google_oauth.missing_scopes(granted)

    async with async_session() as session:
        account = await session.scalar(
            select(GoogleAccount).where(GoogleAccount.tutor_id == tutor_id)
        )
        if account is None:
            account = GoogleAccount(tutor_id=tutor_id, google_sub=claims.get("sub", ""))
            session.add(account)
        account.google_sub = claims.get("sub", account.google_sub)
        account.google_email = claims.get("email")
        account.access_token = google_oauth.encrypt_token(tokens["access_token"])
        if tokens.get("refresh_token"):
            account.refresh_token = google_oauth.encrypt_token(tokens["refresh_token"])
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(tokens.get("expires_in", 3600))
        )
        account.scopes = granted
        if missing:
            account.status = GoogleAccountStatus.needs_reauth
            account.last_error = "Missing permissions: " + ", ".join(s.split("/")[-1] for s in missing)
        else:
            account.status = GoogleAccountStatus.connected
            account.last_error = None
        await session.commit()

    outcome = "missing_scopes" if missing else "connected"
    return RedirectResponse(f"{frontend}/tutor/integrations?google={outcome}")


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(db: DbSession, user: CurrentUser) -> None:
    _require_tutor(user)
    account = await _account(db, user)
    await google_oauth.revoke(account)
    links = (
        await db.scalars(select(GoogleCourseLink).where(GoogleCourseLink.account_id == account.id))
    ).all()
    for link in links:
        works = (
            await db.scalars(
                select(GoogleCourseworkLink).where(GoogleCourseworkLink.course_link_id == link.id)
            )
        ).all()
        for work in works:
            for row in (
                await db.scalars(
                    select(GoogleSubmissionImport).where(
                        GoogleSubmissionImport.coursework_link_id == work.id
                    )
                )
            ).all():
                await db.delete(row)
            for run in (
                await db.scalars(
                    select(GoogleImportRun).where(GoogleImportRun.coursework_link_id == work.id)
                )
            ).all():
                await db.delete(run)
            await db.delete(work)
        await db.delete(link)
    for row in (
        await db.scalars(select(GoogleStudentLink).where(GoogleStudentLink.account_id == account.id))
    ).all():
        await db.delete(row)
    await db.delete(account)
    await db.commit()


@router.get("/courses", response_model=list[GoogleCourse])
async def list_courses(db: DbSession, user: CurrentUser) -> list[GoogleCourse]:
    _require_tutor(user)
    account = await _account(db, user)
    token = await google_oauth.ensure_access_token(db, account)
    async with httpx.AsyncClient(timeout=30) as http:
        courses = await google_api.list_courses(http, token)
    linked = {
        row.course_id: row.group_id
        for row in (
            await db.scalars(
                select(GoogleCourseLink).where(GoogleCourseLink.account_id == account.id)
            )
        ).all()
    }
    return [
        GoogleCourse(
            course_id=c["id"],
            name=c.get("name", "Untitled course"),
            section=c.get("section"),
            linked_group_id=linked.get(c["id"]),
        )
        for c in courses
    ]


@router.get("/courses/{course_id}/coursework", response_model=list[GoogleCoursework])
async def list_coursework(course_id: str, db: DbSession, user: CurrentUser) -> list[GoogleCoursework]:
    _require_tutor(user)
    account = await _account(db, user)
    token = await google_oauth.ensure_access_token(db, account)
    async with httpx.AsyncClient(timeout=30) as http:
        items = await google_api.list_coursework(http, token, course_id)

    link = await db.scalar(
        select(GoogleCourseLink).where(
            GoogleCourseLink.account_id == account.id, GoogleCourseLink.course_id == course_id
        )
    )
    linked: dict[str, int] = {}
    if link is not None:
        linked = {
            row.coursework_id: row.assignment_id
            for row in (
                await db.scalars(
                    select(GoogleCourseworkLink).where(
                        GoogleCourseworkLink.course_link_id == link.id
                    )
                )
            ).all()
        }
    return [
        GoogleCoursework(
            coursework_id=i["id"],
            title=i.get("title", "Untitled"),
            linked_assignment_id=linked.get(i["id"]),
        )
        for i in items
    ]


@router.post("/course-links", response_model=CourseLinkOut, status_code=status.HTTP_201_CREATED)
async def link_course(body: CourseLinkCreate, db: DbSession, user: CurrentUser) -> CourseLinkOut:
    _require_tutor(user)
    account = await _account(db, user)
    group = await db.get(Group, body.group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    existing = await db.scalar(
        select(GoogleCourseLink).where(GoogleCourseLink.group_id == group.id)
    )
    link = existing or GoogleCourseLink(account_id=account.id, group_id=group.id, course_id="")
    link.account_id = account.id
    link.course_id = body.course_id

    token = await google_oauth.ensure_access_token(db, account)
    async with httpx.AsyncClient(timeout=30) as http:
        courses = await google_api.list_courses(http, token)
    match = next((c for c in courses if c["id"] == body.course_id), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found in Google Classroom")
    link.course_name = match.get("name")

    if existing is None:
        db.add(link)
    await db.commit()
    return CourseLinkOut(
        id=link.id, course_id=link.course_id, course_name=link.course_name, group_id=link.group_id
    )


@router.delete("/course-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_course(link_id: int, db: DbSession, user: CurrentUser) -> None:
    _require_tutor(user)
    link = await _owned_course_link(db, user, link_id)
    await db.delete(link)
    await db.commit()


@router.get("/course-links/{link_id}/roster", response_model=RosterOut)
async def course_roster(link_id: int, db: DbSession, user: CurrentUser) -> RosterOut:
    _require_tutor(user)
    link = await _owned_course_link(db, user, link_id)
    account = await db.get(GoogleAccount, link.account_id)
    token = await google_oauth.ensure_access_token(db, account)
    async with httpx.AsyncClient(timeout=30) as http:
        roster = await google_api.list_students(http, token, link.course_id)

    google_students = [
        {
            "id": s["userId"],
            "name": (s.get("profile") or {}).get("name", {}).get("fullName"),
            "email": (s.get("profile") or {}).get("emailAddress"),
        }
        for s in roster
    ]

    members = (
        await db.scalars(
            select(User)
            .join(GroupMember, GroupMember.student_id == User.id)
            .where(GroupMember.group_id == link.group_id)
            .order_by(User.name)
        )
    ).all()
    mapped = {
        row.google_user_id: row.student_id
        for row in (
            await db.scalars(
                select(GoogleStudentLink).where(GoogleStudentLink.account_id == account.id)
            )
        ).all()
    }
    unmapped_members = [m for m in members if m.id not in set(mapped.values())]
    suggestions = suggest_matches(
        [g for g in google_students if g["id"] not in mapped], unmapped_members
    )

    entries = [
        RosterEntry(
            google_user_id=g["id"],
            google_name=g["name"],
            google_email=g["email"],
            mapped_student_id=mapped.get(g["id"]),
            suggested_student_id=suggestions.get(g["id"]),
        )
        for g in google_students
    ]
    claimed = set(mapped.values()) | set(suggestions.values())
    return RosterOut(
        classroom_students=entries,
        app_students_not_in_classroom=[
            UnmatchedStudent(student_id=m.id, name=m.name) for m in members if m.id not in claimed
        ],
    )


@router.put("/course-links/{link_id}/roster", response_model=RosterOut)
async def save_roster(
    link_id: int, body: list[RosterMapping], db: DbSession, user: CurrentUser
) -> RosterOut:
    _require_tutor(user)
    link = await _owned_course_link(db, user, link_id)
    account = await db.get(GoogleAccount, link.account_id)

    member_ids = set(
        (
            await db.scalars(
                select(GroupMember.student_id).where(GroupMember.group_id == link.group_id)
            )
        ).all()
    )
    for mapping in body:
        row = await db.scalar(
            select(GoogleStudentLink).where(
                GoogleStudentLink.account_id == account.id,
                GoogleStudentLink.google_user_id == mapping.google_user_id,
            )
        )
        if mapping.student_id is None:
            if row is not None:
                await db.delete(row)
            continue
        if mapping.student_id not in member_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That student isn't in this class"
            )
        if row is None:
            row = GoogleStudentLink(
                account_id=account.id,
                google_user_id=mapping.google_user_id,
                student_id=mapping.student_id,
            )
            db.add(row)
        else:
            row.student_id = mapping.student_id
    await db.commit()
    return await course_roster(link_id, db, user)


def _run_out(run: GoogleImportRun, rows: list[GoogleSubmissionImport]) -> ImportRunOut:
    return ImportRunOut(
        id=run.id,
        status=run.status.value,
        total=run.total,
        imported=run.imported,
        skipped=run.skipped,
        failed=run.failed,
        error=run.error,
        finished_at=run.finished_at,
        results=[
            ImportResultRow(
                google_user_id=r.google_user_id,
                outcome=r.outcome.value,
                detail=r.detail,
                imported_file_count=r.imported_file_count,
            )
            for r in rows
        ],
    )


@router.post(
    "/course-links/{link_id}/coursework/{coursework_id}/import",
    response_model=ImportRunOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_import(
    link_id: int,
    coursework_id: str,
    body: ImportRequest,
    db: DbSession,
    user: CurrentUser,
) -> ImportRunOut:
    _require_tutor(user)
    link = await _owned_course_link(db, user, link_id)

    assignment = await db.get(Assignment, body.assignment_id)
    if assignment is None or assignment.group_id != link.group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Homework not found in this class")
    # Marking needs an extracted question list to mark against.
    if assignment.status != AssignmentStatus.published:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This homework isn't published yet, so there's nothing to mark against",
        )

    work = await db.scalar(
        select(GoogleCourseworkLink).where(
            GoogleCourseworkLink.course_link_id == link.id,
            GoogleCourseworkLink.coursework_id == coursework_id,
        )
    )
    if work is None:
        work = GoogleCourseworkLink(
            course_link_id=link.id, assignment_id=assignment.id, coursework_id=coursework_id
        )
        db.add(work)
        await db.flush()
    elif work.assignment_id != assignment.id:
        work.assignment_id = assignment.id
        await db.flush()

    active = await db.scalar(
        select(GoogleImportRun).where(
            GoogleImportRun.coursework_link_id == work.id,
            GoogleImportRun.status.in_([ImportRunStatus.pending, ImportRunStatus.running]),
        )
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An import is already running")

    run = GoogleImportRun(coursework_link_id=work.id, started_by_id=user.id)
    db.add(run)
    await db.flush()
    await enqueue(db, "import_google_coursework", {"run_id": run.id})
    await db.commit()
    return _run_out(run, [])


@router.get("/import-runs/{run_id}", response_model=ImportRunOut)
async def import_run(run_id: int, db: DbSession, user: CurrentUser) -> ImportRunOut:
    _require_tutor(user)
    run = await db.get(GoogleImportRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    work = await db.get(GoogleCourseworkLink, run.coursework_link_id)
    await _owned_course_link(db, user, work.course_link_id)
    rows = (
        await db.scalars(
            select(GoogleSubmissionImport)
            .where(GoogleSubmissionImport.coursework_link_id == work.id)
            .order_by(GoogleSubmissionImport.id)
        )
    ).all()
    return _run_out(run, list(rows))
