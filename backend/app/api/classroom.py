"""HIDDEN FROM THE PRODUCT (AV-58) — code kept, router not mounted.

This module is intact and correct. It is simply not registered in main.py, so
none of its routes exist at runtime. Google Classroom sync is hidden rather than
deleted, so **do not remove this file as dead code**.

Re-mounting the router restores the API and nothing more. Unlike the knowledge
base, Classroom's frontend was genuinely deleted, not hidden: api/classroom.ts,
ClassroomSettingsPage.tsx and ClassroomCallbackPage.tsx are gone, and
/settings/classroom/callback is no longer a route. So bringing the feature back
means re-mounting this router AND rebuilding the tutor surface that drives it.
Do not plan a re-activation on the assumption that the mount is the whole job.

Hiding this surface also lifts the single-origin deployment constraint:
GOOGLE_REDIRECT_URI had to match exactly one origin, which is why Render
deliberately served no second copy of the frontend. Phase 1 depends on
that constraint being gone (see §08).
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, TutorUser
from app.models import ClassroomCourseLink, GoogleAccount, Group, User
from app.schemas.classroom import (
    ClassroomAuthUrl,
    ClassroomConnect,
    ClassroomCourseOut,
    ClassroomLinkCreate,
    ClassroomLinkOut,
    ClassroomStatus,
)
from app.security import create_state_token, verify_state_token
from app.services import google_classroom as gc
from app.workers.jobs import enqueue

router = APIRouter(prefix="/classroom", tags=["classroom"])

OAUTH_PURPOSE = "classroom_connect"


async def _own_account(db: DbSession, user: User) -> GoogleAccount:
    account = await db.scalar(select(GoogleAccount).where(GoogleAccount.tutor_id == user.id))
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google Classroom is not connected")
    return account


@router.get("/status", response_model=ClassroomStatus)
async def classroom_status(db: DbSession, user: TutorUser) -> ClassroomStatus:
    account = await db.scalar(select(GoogleAccount).where(GoogleAccount.tutor_id == user.id))
    return ClassroomStatus(
        configured=gc.is_configured(),
        connected=account is not None,
        google_email=account.google_email if account else None,
        connected_at=account.connected_at if account else None,
    )


@router.get("/auth-url", response_model=ClassroomAuthUrl)
async def auth_url(user: TutorUser) -> ClassroomAuthUrl:
    try:
        state = create_state_token(user.id, OAUTH_PURPOSE)
        return ClassroomAuthUrl(url=gc.build_auth_url(state), state=state)
    except gc.GoogleClassroomUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/connect", response_model=ClassroomStatus, status_code=status.HTTP_201_CREATED)
async def connect(body: ClassroomConnect, db: DbSession, user: TutorUser) -> ClassroomStatus:
    # Rejects a callback this tutor did not start: without it, a link crafted by
    # an attacker could attach the attacker's Google account to this tutor's
    # organization, and every subsequent sync would import their coursework.
    if not verify_state_token(body.state, user.id, OAUTH_PURPOSE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This connection attempt didn't start here, or it took too long. Try connecting again.",
        )
    try:
        account = await gc.connect_account(
            db, organization_id=user.organization_id, tutor_id=user.id, code=body.code
        )
    except gc.GoogleClassroomUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()
    return ClassroomStatus(
        configured=True,
        connected=True,
        google_email=account.google_email,
        connected_at=account.connected_at,
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(db: DbSession, user: TutorUser) -> None:
    account = await _own_account(db, user)
    await db.delete(account)
    await db.commit()


@router.get("/courses", response_model=list[ClassroomCourseOut])
async def list_courses(db: DbSession, user: TutorUser) -> list[ClassroomCourseOut]:
    account = await _own_account(db, user)
    try:
        access_token = await gc.get_valid_access_token(account)
        courses = await gc.list_courses(access_token)
    except gc.GoogleClassroomUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return [ClassroomCourseOut(id=c["id"], name=c.get("name", c["id"])) for c in courses]


@router.get("/links", response_model=list[ClassroomLinkOut])
async def list_links(db: DbSession, user: TutorUser) -> list[ClassroomLinkOut]:
    account = await _own_account(db, user)
    rows = (
        await db.execute(
            select(ClassroomCourseLink, Group)
            .join(Group, Group.id == ClassroomCourseLink.group_id)
            .where(ClassroomCourseLink.google_account_id == account.id)
        )
    ).all()
    return [
        ClassroomLinkOut(
            id=link.id,
            group_id=group.id,
            group_name=group.name,
            classroom_course_id=link.classroom_course_id,
            classroom_course_name=link.classroom_course_name,
            last_synced_at=link.last_synced_at,
        )
        for link, group in rows
    ]


@router.post("/links", response_model=ClassroomLinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(
    body: ClassroomLinkCreate, db: DbSession, user: TutorUser
) -> ClassroomLinkOut:
    account = await _own_account(db, user)
    group = await db.get(Group, body.group_id)
    if group is None or group.tutor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    link = await db.scalar(
        select(ClassroomCourseLink).where(ClassroomCourseLink.group_id == body.group_id)
    )
    if link is None:
        link = ClassroomCourseLink(
            organization_id=user.organization_id,
            google_account_id=account.id,
            group_id=group.id,
            classroom_course_id=body.classroom_course_id,
            classroom_course_name=body.classroom_course_name,
        )
        db.add(link)
    else:
        link.classroom_course_id = body.classroom_course_id
        link.classroom_course_name = body.classroom_course_name
    await db.commit()
    await db.refresh(link)
    return ClassroomLinkOut(
        id=link.id,
        group_id=group.id,
        group_name=group.name,
        classroom_course_id=link.classroom_course_id,
        classroom_course_name=link.classroom_course_name,
        last_synced_at=link.last_synced_at,
    )


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: int, db: DbSession, user: TutorUser) -> None:
    account = await _own_account(db, user)
    link = await db.get(ClassroomCourseLink, link_id)
    if link is None or link.google_account_id != account.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    await db.delete(link)
    await db.commit()


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(db: DbSession, user: TutorUser) -> dict:
    account = await _own_account(db, user)
    await enqueue(db, "sync_classroom", {"google_account_id": account.id})
    await db.commit()
    return {"queued": True}
