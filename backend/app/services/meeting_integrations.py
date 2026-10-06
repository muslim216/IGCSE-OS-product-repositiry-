"""Zoom and Google Meet attendance for online lessons (task 7.3, AV-118).

A tutor connects a provider, pastes the meeting link on an online lesson and asks
for the attendance. A job (`BE-2`) fetches the participants with the tutor's own
connection and writes the register:

* a participant is matched to a student ONLY by exact, case-insensitive email
  against the lesson's own class. Everyone else is stored in
  `meeting_participants` and shown to the tutor to resolve. Nothing is guessed
  from a name (`PROD-1`).
* matched students are marked present and enrolled students nobody matched are
  marked absent — both with the provider as source, and neither ever overwrites
  a mark a tutor made (`set_attendance`).
* an import that cannot tell the truth (not connected, token refused, nothing
  returned) writes nothing and says why on the lesson (`PROD-2`): an empty answer
  is never read as "everyone was absent".

Safe to re-run (`BE-6`): provider rows are replaced except those a tutor
resolved, and a tutor-decided student is never marked absent by a later import.
Job payloads carry ids only (`BE-9`).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta, timezone
from types import ModuleType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttendanceSource,
    AttendanceState,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    LessonMeetingImport,
    LessonMode,
    MeetingConnection,
    MeetingImportStatus,
    MeetingParticipant,
    MeetingProvider,
    User,
)
from app.models.base import utcnow
from app.services import attendance, google_meet, zoom
from app.services.attendance import AttendanceEntry
from app.services.google_classroom import decrypt_token, encrypt_token
from app.services.meeting_common import (
    AUTH_FAILED,
    NO_DATA,
    NOT_CONFIGURED,
    NOT_CONNECTED,
    PROVIDER_ERROR,
    PROVIDER_LABEL,
    MeetingProviderError,
    canonical_link,
    lesson_moment,
    parse_meeting_link,
)
from app.services.plan_start_times import class_zone
from app.services.timezones import is_valid_timezone

logger = logging.getLogger(__name__)

#: A `queued` import older than this is presumed lost (a worker died) and may be re-asked.
STALE_AFTER = timedelta(minutes=15)

IMPORT_JOB = "import_meeting_attendance"

#: Said on the connect screen and the status, up front (spec: at connect time).
PROVIDER_NOTES: dict[MeetingProvider, str] = {
    MeetingProvider.zoom: (
        "Zoom's participant report needs a paid Zoom plan. Only meetings hosted by the "
        "account you connect can be read."
    ),
    MeetingProvider.google_meet: (
        google_meet.NO_ATTENDANCE_HINT + " " + google_meet.DIRECTORY_NOTE
    ),
}


class ImportUnavailable(Exception):
    """An import cannot even be queued. `code` is one of the meeting_common reasons."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ParticipantNotFound(LookupError):
    """No such participant on this lesson. The router turns it into a 404 (`API-7`)."""


class ParticipantAlreadyResolved(RuntimeError):
    """Someone (maybe a concurrent request) already decided who this participant is.
    The router turns it into a 409."""


class StudentNotEnrolled(LookupError):
    """The chosen student is not in the lesson's class. The router turns it into a 404."""


def _module(provider: MeetingProvider) -> ModuleType:
    return zoom if provider == MeetingProvider.zoom else google_meet


def is_configured(provider: MeetingProvider) -> bool:
    return bool(_module(provider).is_configured())


def state_purpose(provider: MeetingProvider) -> str:
    """Per provider, so a state minted for Zoom cannot complete a Google connection."""
    return f"meeting_{provider.value}"


def build_auth_url(provider: MeetingProvider, state: str) -> str:
    return str(_module(provider).build_auth_url(state))


async def get_connection(
    session: AsyncSession, tutor_id: int, provider: MeetingProvider
) -> MeetingConnection | None:
    return await session.scalar(
        select(MeetingConnection).where(
            MeetingConnection.tutor_id == tutor_id, MeetingConnection.provider == provider
        )
    )


async def connect(
    session: AsyncSession, user: User, provider: MeetingProvider, code: str
) -> MeetingConnection:
    """Exchange the authorization code and upsert the tutor's connection. Flushes;
    the caller commits."""
    module = _module(provider)
    grant = await module.exchange_code(code)
    # Google lets the user untick individual permissions on the consent screen.
    if provider == MeetingProvider.google_meet:
        # An empty or missing `scope` is a refusal too, not a pass: both
        # permissions must be positively shown to have been granted.
        granted = grant.scopes.split()
        if google_meet.MEET_SCOPE not in granted:
            raise MeetingProviderError(
                AUTH_FAILED,
                "Avora needs permission to see Meet attendance. Connect again and leave "
                "every permission ticked.",
            )
        if google_meet.DIRECTORY_SCOPE not in granted:
            raise MeetingProviderError(
                AUTH_FAILED,
                "Avora also needs the directory permission, to read participants' names and "
                "emails so they can be matched to your students — without it nobody can be "
                "identified. Connect again and leave every permission ticked.",
            )
    email = await module.fetch_account_email(grant.access_token)
    existing = await get_connection(session, user.id, provider)
    refresh_token = grant.refresh_token
    if refresh_token is None and existing is not None:
        refresh_token = decrypt_token(existing.encrypted_refresh_token)
    if refresh_token is None:
        raise MeetingProviderError(
            AUTH_FAILED,
            f"{PROVIDER_LABEL[provider]} didn't allow Avora to stay connected. Try connecting again.",
        )
    encrypted = encrypt_token(refresh_token)
    if existing is None:
        existing = MeetingConnection(
            organization_id=user.organization_id,
            tutor_id=user.id,
            provider=provider,
            encrypted_refresh_token=encrypted,
            account_email=email,
            scopes=grant.scopes,
            connected_at=utcnow(),
        )
        session.add(existing)
    else:
        existing.encrypted_refresh_token = encrypted
        existing.account_email = email
        existing.scopes = grant.scopes
        existing.connected_at = utcnow()
    await session.flush()
    return existing


async def access_token_for(session: AsyncSession, connection: MeetingConnection) -> str:
    """A fresh access token. Zoom rotates the refresh token on every refresh, so
    the new one is committed straight away: losing it would disconnect the tutor."""
    grant = await _module(connection.provider).refresh(
        decrypt_token(connection.encrypted_refresh_token)
    )
    if grant.refresh_token:
        connection.encrypted_refresh_token = encrypt_token(grant.refresh_token)
        await session.commit()
    return str(grant.access_token)


# --- A lesson's meeting link ---------------------------------------------------


async def disconnect(session: AsyncSession, connection: MeetingConnection) -> None:
    """Revoke at the provider (best effort), then delete the stored token. A revoke
    that fails is logged and the connection is deleted anyway: the tutor asked to
    disconnect, and a provider outage must not keep Avora holding their token.
    Does not commit."""
    try:
        await _module(connection.provider).revoke(decrypt_token(connection.encrypted_refresh_token))
    except Exception as exc:  # noqa: BLE001 - best effort by design; never logs the token
        logger.warning(
            "could not revoke %s connection %s at the provider (%s)",
            connection.provider.value,
            connection.id,
            type(exc).__name__,
        )
    await session.delete(connection)


async def delete_for_lesson(session: AsyncSession, lesson_id: int) -> None:
    """Remove a lesson's provider rows. Does not commit. The FK cascades in
    Postgres; SQLite (the test database) has foreign keys off."""
    for participant in await session.scalars(
        select(MeetingParticipant).where(MeetingParticipant.lesson_id == lesson_id)
    ):
        await session.delete(participant)
    for row in await session.scalars(
        select(LessonMeetingImport).where(LessonMeetingImport.lesson_id == lesson_id)
    ):
        await session.delete(row)
    await session.flush()


async def set_lesson_meeting(session: AsyncSession, lesson: Lesson, link: str | None) -> None:
    """Set (or, with None, clear) the lesson's meeting from a pasted link. Raises
    `MeetingLinkError` for anything that is not a Zoom or Meet link. A different
    meeting drops what was imported from the old one. Does not commit."""
    if link is None:
        provider, ref = None, None
    else:
        provider, ref = parse_meeting_link(link)
    if (lesson.meeting_provider, lesson.meeting_ref) != (provider, ref):
        if lesson.id is not None:
            await delete_for_lesson(session, lesson.id)
            # Marks the old meeting wrote are about a different meeting now. A
            # tutor's own marks are theirs and stay.
            for mark in await session.scalars(
                select(LessonAttendance).where(
                    LessonAttendance.lesson_id == lesson.id,
                    LessonAttendance.source.in_(
                        [AttendanceSource.zoom, AttendanceSource.google_meet]
                    ),
                )
            ):
                await session.delete(mark)
        lesson.meeting_provider = provider
        lesson.meeting_ref = ref


def lesson_link(lesson: Lesson) -> str | None:
    if lesson.meeting_provider is None or lesson.meeting_ref is None:
        return None
    return canonical_link(lesson.meeting_provider, lesson.meeting_ref)


# --- Importing attendance ------------------------------------------------------


async def request_import(session: AsyncSession, lesson: Lesson, user: User) -> LessonMeetingImport:
    """Validate and queue an import. Raises `ImportUnavailable` with a message the
    tutor can act on. Flushes; the caller commits."""
    from app.workers.jobs import enqueue

    provider = lesson.meeting_provider
    if lesson.mode != LessonMode.online or provider is None or lesson.meeting_ref is None:
        raise ImportUnavailable(
            "no_link", "Add this lesson's Zoom or Google Meet link first, and set it to Online."
        )
    label = PROVIDER_LABEL[provider]
    if not is_configured(provider):
        raise ImportUnavailable(NOT_CONFIGURED, f"{label} attendance isn't set up for Avora yet.")
    if await get_connection(session, user.id, provider) is None:
        raise ImportUnavailable(NOT_CONNECTED, f"Connect {label} in Settings first.")

    row = await session.scalar(
        select(LessonMeetingImport).where(LessonMeetingImport.lesson_id == lesson.id)
    )
    now = utcnow()
    if row is not None and row.status == MeetingImportStatus.queued:
        asked = row.requested_at
        asked = asked.replace(tzinfo=timezone.utc) if asked.tzinfo is None else asked
        if now - asked < STALE_AFTER:
            return row  # one is already queued or running: don't start a second
    if row is None:
        row = LessonMeetingImport(
            organization_id=lesson.organization_id,
            lesson_id=lesson.id,
            status=MeetingImportStatus.queued,
            requested_by_id=user.id,
            requested_at=now,
        )
        session.add(row)
    row.status = MeetingImportStatus.queued
    row.error_code = None
    row.message = None
    row.requested_by_id = user.id
    row.requested_at = now
    row.finished_at = None
    row.attempt = (row.attempt or 0) + 1
    await session.flush()
    await enqueue(
        session,
        IMPORT_JOB,
        {"lesson_id": lesson.id, "user_id": user.id, "attempt": row.attempt},
    )
    return row


def _key(email: str | None, name: str) -> str:
    return f"email:{email.strip().lower()}" if email else f"name:{name.strip().lower()}"


@dataclass(frozen=True)
class _Outcome:
    present: int
    absent: int
    unmatched: int
    kept: int
    #: Absence was NOT written because someone could not be identified (`PROD-2`).
    absence_withheld: bool
    warning: str | None


async def _current(
    session: AsyncSession, row_id: int, attempt: int, *, lock: bool = False
) -> LessonMeetingImport | None:
    """The import row, if this job's attempt is still the current one; else None.
    Always read fresh. `lock` holds the row (`FOR UPDATE`) so a re-request cannot
    slip in between this check and the register being written."""
    query = (
        select(LessonMeetingImport)
        .where(LessonMeetingImport.id == row_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    return row if row is not None and row.attempt == attempt else None


async def _finish(
    session: AsyncSession,
    row_id: int,
    attempt: int,
    status: MeetingImportStatus,
    code: str | None,
    message: str | None,
) -> None:
    """Record the outcome — unless a newer request has superseded this attempt, in
    which case this worker says nothing."""
    row = await _current(session, row_id, attempt)
    if row is None:
        await session.rollback()
        return
    row.status = status
    row.error_code = code
    row.message = message
    row.finished_at = utcnow()
    await session.commit()


async def import_meeting_attendance(session: AsyncSession, payload: dict) -> None:
    """Job handler for `import_meeting_attendance`."""
    lesson = await session.get(Lesson, payload["lesson_id"])
    user = await session.get(User, payload["user_id"])
    if lesson is None or user is None or lesson.organization_id != user.organization_id:
        return  # the lesson went away, or this was never the requester's: nothing to say to anyone
    if await session.scalar(select(Group.deleted_at).where(Group.id == lesson.group_id)):
        return  # its class was deleted: nothing acts on it
    attempt = int(payload.get("attempt", 0))
    row = await session.scalar(
        select(LessonMeetingImport).where(LessonMeetingImport.lesson_id == lesson.id)
    )
    if row is None:
        row = LessonMeetingImport(
            organization_id=lesson.organization_id,
            lesson_id=lesson.id,
            status=MeetingImportStatus.queued,
            requested_by_id=user.id,
            requested_at=utcnow(),
            attempt=attempt,
        )
        session.add(row)
        await session.flush()
    if row.attempt != attempt:
        return  # a newer request owns this lesson's import now
    row_id = row.id
    failed = MeetingImportStatus.failed
    provider, ref = lesson.meeting_provider, lesson.meeting_ref
    if provider is None or ref is None:
        await _finish(
            session, row_id, attempt, failed, "no_link", "This lesson has no Zoom or Meet link."
        )
        return
    connection = await get_connection(session, user.id, provider)
    if connection is None:
        await _finish(
            session,
            row_id,
            attempt,
            failed,
            NOT_CONNECTED,
            f"{PROVIDER_LABEL[provider]} isn't connected any more.",
        )
        return

    try:
        # The lesson's wall clock is its class's (tutor override, else organization).
        class_zone_name = await class_zone(session, lesson.group_id)
        zone = class_zone_name if class_zone_name and is_valid_timezone(class_zone_name) else None
        moment = lesson_moment(lesson.date, lesson.start_time, zone)
        token = await access_token_for(session, connection)
        result = await _module(provider).fetch_participants(token, ref, moment)
        if not result.participants:
            hint = (
                google_meet.NO_ATTENDANCE_HINT
                if provider == MeetingProvider.google_meet
                else "Zoom reported nobody in that meeting."
            )
            raise MeetingProviderError(
                NO_DATA, f"{PROVIDER_LABEL[provider]} returned no attendance. {hint}"
            )
        # The fetch is the slow part: re-check, and hold the row, before writing.
        if await _current(session, row_id, attempt, lock=True) is None:
            await session.rollback()
            return
        outcome = await _apply(
            session, lesson, user, connection, provider, result.participants, result.warning
        )
    except MeetingProviderError as exc:
        # Nothing has been written that a rollback would not undo, so a failure
        # leaves the register as it was.
        await session.rollback()
        await _finish(session, row_id, attempt, failed, exc.code, exc.message)
        return
    except Exception:
        # Anything unforeseen (a malformed answer, a lost race): the tutor still
        # sees a failed import rather than one stuck on "queued", and the job is
        # failed too so it is visible to operations.
        logger.exception("meeting attendance import failed for lesson %s", payload["lesson_id"])
        await session.rollback()
        await _finish(
            session,
            row_id,
            attempt,
            failed,
            PROVIDER_ERROR,
            "Something went wrong while reading the attendance. Try again, or mark the "
            "register by hand.",
        )
        raise

    present = f"{outcome.present} present"
    message = present + (f", {outcome.absent} absent." if not outcome.absence_withheld else ".")
    if outcome.unmatched:
        noun = "participant" if outcome.unmatched == 1 else "participants"
        message += (
            f" {outcome.unmatched} {noun} couldn't be identified — match them or mark the "
            "register; nobody was marked absent."
        )
    if outcome.kept:
        message += f" {outcome.kept} kept as you marked them."
    if outcome.warning:
        message += " " + outcome.warning
    await _finish(session, row_id, attempt, MeetingImportStatus.succeeded, None, message)


async def _apply(
    session: AsyncSession,
    lesson: Lesson,
    user: User,
    connection: MeetingConnection,
    provider: MeetingProvider,
    records: list,
    warning: str | None,
) -> _Outcome:
    enrolled = {
        sid: (email or "").strip().lower()
        for sid, email in (
            await session.execute(
                select(User.id, User.email)
                .join(GroupMember, GroupMember.student_id == User.id)
                .where(GroupMember.group_id == lesson.group_id)
            )
        ).all()
    }
    by_email = {email: sid for sid, email in enrolled.items() if email}
    # The host is in the participant list too; they are not a student to match or resolve.
    hosts = {e.strip().lower() for e in (user.email, connection.account_email) if e}

    existing = list(
        await session.scalars(
            select(MeetingParticipant).where(
                MeetingParticipant.lesson_id == lesson.id,
                MeetingParticipant.organization_id == lesson.organization_id,
            )
        )
    )
    # A tutor's decision is kept across re-imports.
    resolved = [p for p in existing if p.resolved_by_id is not None]
    resolved_keys = {_key(p.email, p.display_name) for p in resolved}
    decided_students = {p.matched_student_id for p in resolved if p.matched_student_id}
    for stale in existing:
        if stale.resolved_by_id is None:
            await session.delete(stale)
    await session.flush()

    matched: set[int] = set()
    unmatched = 0
    for rec in records:
        email = rec.email.strip().lower() if rec.email else None
        if email and email in hosts:
            continue
        if _key(rec.email, rec.display_name) in resolved_keys:
            continue
        candidate = by_email.get(email) if email else None
        # Only a provider-verified email is acted on. An unverified one (a Zoom
        # guest typed it) is a suggestion: anyone can type a classmate's address.
        student_id = candidate if rec.verified else None
        suggested = candidate if not rec.verified else None
        if student_id is None:
            unmatched += 1
        else:
            matched.add(student_id)
        session.add(
            MeetingParticipant(
                organization_id=lesson.organization_id,
                lesson_id=lesson.id,
                provider=provider,
                display_name=rec.display_name[:255],
                email=(rec.email or None) and rec.email[:255],
                duration_seconds=rec.duration_seconds,
                matched_student_id=student_id,
                suggested_student_id=suggested,
            )
        )

    # PROD-2: absence is only ever inferred when EVERY participant was identified.
    # If anyone could not be (no email, a guest, a failed lookup, an unverified
    # match), a student with no match may simply be that person.
    withhold_absence = unmatched > 0
    entries = [
        AttendanceEntry(sid, AttendanceState.present) for sid in sorted(matched - decided_students)
    ]
    if not withhold_absence:
        entries += [
            AttendanceEntry(sid, AttendanceState.absent)
            for sid in sorted(set(enrolled) - matched - decided_students)
        ]
    skipped = await attendance.set_attendance(
        session,
        lesson,
        entries,
        recorded_by=None,
        source=AttendanceSource(provider.value),
    )
    skipped_set = set(skipped)
    return _Outcome(
        present=len(matched - decided_students - skipped_set),
        absent=0
        if withhold_absence
        else len(set(enrolled) - matched - decided_students - skipped_set),
        unmatched=unmatched,
        kept=len(skipped_set),
        absence_withheld=withhold_absence,
        warning=warning,
    )


async def resolve_participant(
    session: AsyncSession, lesson: Lesson, participant_id: int, student_id: int, user: User
) -> MeetingParticipant:
    """A tutor says who an unmatched participant is. A human decided, so the mark
    is the tutor's (source `tutor`) and a later import will not overwrite it."""
    participant = await session.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.id == participant_id,
            MeetingParticipant.lesson_id == lesson.id,
            MeetingParticipant.organization_id == lesson.organization_id,
        )
    )
    if participant is None:
        raise ParticipantNotFound
    enrolled = await session.scalar(
        select(GroupMember.id).where(
            GroupMember.group_id == lesson.group_id, GroupMember.student_id == student_id
        )
    )
    if enrolled is None:
        raise StudentNotEnrolled
    # Conditional update: of two concurrent resolves only one can win, and a
    # participant already decided is not silently re-attributed (the earlier
    # present mark would be left behind on the wrong student).
    won = await session.execute(
        update(MeetingParticipant)
        .where(
            MeetingParticipant.id == participant.id,
            MeetingParticipant.resolved_by_id.is_(None),
        )
        .values(matched_student_id=student_id, resolved_by_id=user.id)
    )
    if won.rowcount != 1:  # type: ignore[attr-defined]
        await session.rollback()
        raise ParticipantAlreadyResolved
    await session.refresh(participant)
    # Committed together with the mark by `set_attendance`.
    await attendance.set_attendance(
        session,
        lesson,
        [AttendanceEntry(student_id, AttendanceState.present)],
        recorded_by=user,
        source=AttendanceSource.tutor,
    )
    return participant


async def lesson_participants(session: AsyncSession, lesson: Lesson) -> list[MeetingParticipant]:
    return list(
        await session.scalars(
            select(MeetingParticipant)
            .where(
                MeetingParticipant.lesson_id == lesson.id,
                MeetingParticipant.organization_id == lesson.organization_id,
            )
            .order_by(MeetingParticipant.display_name, MeetingParticipant.id)
        )
    )


async def lesson_import(session: AsyncSession, lesson: Lesson) -> LessonMeetingImport | None:
    return await session.scalar(
        select(LessonMeetingImport).where(
            LessonMeetingImport.lesson_id == lesson.id,
            LessonMeetingImport.organization_id == lesson.organization_id,
        )
    )
