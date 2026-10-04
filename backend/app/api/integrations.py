"""Zoom and Google Meet connections, and attendance import for online lessons
(task 7.3, AV-118).

OAuth callback shape: the provider redirects the browser to a *frontend* page
(`/tutor/settings/integrations/{provider}/callback`), which calls the callback
route here with the tutor's own session. The `state` is signed by this server and
bound to that tutor and provider, and it is verified here (`SEC-3` family): the
browser's own comparison is a second check, not the check. A callback the tutor
did not start would otherwise attach an attacker's account to their organization.
"""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, TutorUser
from app.api.lessons import _owned_lesson
from app.models import MeetingProvider
from app.schemas.integrations import (
    IntegrationAuthUrlOut,
    IntegrationStatusOut,
    LessonMeetingOut,
    MeetingImportOut,
    MeetingParticipantOut,
    ParticipantResolve,
)
from app.security import create_state_token, verify_state_token
from app.services import meeting_integrations as mi
from app.services.attendance import AttendanceConflict
from app.services.meeting_common import NOT_CONFIGURED, MeetingProviderError

router = APIRouter(prefix="/integrations", tags=["integrations"])
lesson_router = APIRouter(prefix="/lessons", tags=["integrations"])


async def _status(
    db: DbSession, user: TutorUser, provider: MeetingProvider
) -> IntegrationStatusOut:
    connection = await mi.get_connection(db, user.id, provider)
    return IntegrationStatusOut(
        provider=provider,
        configured=mi.is_configured(provider),
        connected=connection is not None,
        account_email=connection.account_email if connection else None,
        connected_at=connection.connected_at if connection else None,
        note=mi.PROVIDER_NOTES[provider],
    )


def _http(exc: MeetingProviderError) -> HTTPException:
    if exc.code == NOT_CONFIGURED:
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message)
    if exc.code == "auth_failed":
        return HTTPException(status.HTTP_400_BAD_REQUEST, exc.message)
    # 424, not 502: the message is written for the tutor and a 4xx is the class the
    # frontend passes through; a 5xx would be replaced by a generic sentence.
    return HTTPException(status.HTTP_424_FAILED_DEPENDENCY, exc.message)


@router.get("", response_model=list[IntegrationStatusOut])
async def list_integrations(db: DbSession, user: TutorUser) -> list[IntegrationStatusOut]:
    return [await _status(db, user, provider) for provider in MeetingProvider]


@router.get("/{provider}/authorize-url", response_model=IntegrationAuthUrlOut)
async def authorize_url(provider: MeetingProvider, user: TutorUser) -> IntegrationAuthUrlOut:
    try:
        state = create_state_token(user.id, mi.state_purpose(provider))
        return IntegrationAuthUrlOut(url=mi.build_auth_url(provider, state), state=state)
    except MeetingProviderError as exc:
        raise _http(exc) from exc


@router.get("/{provider}/callback", response_model=IntegrationStatusOut)
async def callback(
    provider: MeetingProvider,
    db: DbSession,
    user: TutorUser,
    code: str = Query(min_length=1, max_length=2048),
    state: str = Query(min_length=1, max_length=2048),
) -> IntegrationStatusOut:
    if not verify_state_token(state, user.id, mi.state_purpose(provider)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This connection attempt didn't start here, or it took too long. Try connecting again.",
        )
    try:
        await mi.connect(db, user, provider, code)
    except MeetingProviderError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    return await _status(db, user, provider)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(provider: MeetingProvider, db: DbSession, user: TutorUser) -> None:
    connection = await mi.get_connection(db, user.id, provider)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not connected")
    await mi.disconnect(db, connection)
    await db.commit()


# --- Per-lesson ----------------------------------------------------------------


@lesson_router.get("/{lesson_id}/meeting", response_model=LessonMeetingOut)
async def lesson_meeting(lesson_id: int, db: DbSession, user: TutorUser) -> LessonMeetingOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    last = await mi.lesson_import(db, lesson)
    participants = await mi.lesson_participants(db, lesson)
    return LessonMeetingOut(
        provider=lesson.meeting_provider,
        link=mi.lesson_link(lesson),
        last_import=(
            MeetingImportOut(
                status=last.status,
                error_code=last.error_code,
                message=last.message,
                finished_at=last.finished_at,
            )
            if last
            else None
        ),
        participants=[
            MeetingParticipantOut(
                id=p.id,
                display_name=p.display_name,
                email=p.email,
                duration_seconds=p.duration_seconds,
                matched_student_id=p.matched_student_id,
                suggested_student_id=p.suggested_student_id,
                resolved=p.resolved_by_id is not None,
            )
            for p in participants
        ],
    )


@lesson_router.post(
    "/{lesson_id}/attendance/import",
    response_model=MeetingImportOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_attendance(lesson_id: int, db: DbSession, user: TutorUser) -> MeetingImportOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    try:
        row = await mi.request_import(db, lesson, user)
    except mi.ImportUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    await db.commit()
    return MeetingImportOut(status=row.status, error_code=None, message=None, finished_at=None)


@lesson_router.post(
    "/{lesson_id}/participants/{participant_id}/resolve", response_model=MeetingParticipantOut
)
async def resolve_participant(
    lesson_id: int,
    participant_id: int,
    body: ParticipantResolve,
    db: DbSession,
    user: TutorUser,
) -> MeetingParticipantOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    try:
        p = await mi.resolve_participant(db, lesson, participant_id, body.student_id, user)
    except mi.ParticipantNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Participant not found") from exc
    except mi.StudentNotEnrolled as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in this class") from exc
    except AttendanceConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Attendance changed at the same moment. Try again."
        ) from exc
    return MeetingParticipantOut(
        id=p.id,
        display_name=p.display_name,
        email=p.email,
        duration_seconds=p.duration_seconds,
        matched_student_id=p.matched_student_id,
        resolved=True,
    )
