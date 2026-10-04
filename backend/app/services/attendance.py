"""Who was at a lesson (task 7.1, AV-44, AV-109).

Attendance is not a readiness factor (AV-33): nothing here touches `Evidence`,
`SOURCE_WEIGHTS` or queues a recompute. A student with no row was simply not
recorded, and is reported as such (`PROD-2`) — never defaulted to absent.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttendanceSource,
    AttendanceState,
    GroupMember,
    Lesson,
    LessonAttendance,
    User,
)
from app.models.base import utcnow


class AttendanceConflict(RuntimeError):
    """Someone else wrote the same mark at the same moment. The router turns it into a 409."""


class AttendanceStudentNotFound(LookupError):
    """A student who is not in the lesson's class. The router turns it into a 404 (`API-7`)."""


@dataclass(frozen=True)
class AttendanceEntry:
    student_id: int
    #: `None` clears the mark, so a tutor can undo one.
    state: AttendanceState | None


@dataclass(frozen=True)
class RegisterRow:
    student_id: int
    name: str
    state: AttendanceState | None
    source: AttendanceSource | None
    recorded_at: datetime | None


async def _enrolled_ids(session: AsyncSession, lesson: Lesson) -> set[int]:
    return set(
        await session.scalars(
            select(GroupMember.student_id).where(GroupMember.group_id == lesson.group_id)
        )
    )


async def lesson_register(session: AsyncSession, lesson: Lesson) -> list[RegisterRow]:
    """Everyone currently in the class plus anyone with a mark who has since left.
    `state is None` means not taken."""
    marks = {
        row.student_id: row
        for row in await session.scalars(
            select(LessonAttendance).where(
                LessonAttendance.lesson_id == lesson.id,
                LessonAttendance.organization_id == lesson.organization_id,
            )
        )
    }
    ids = (await _enrolled_ids(session, lesson)) | set(marks)
    if not ids:
        return []
    users = (await session.scalars(select(User).where(User.id.in_(ids)))).all()
    rows = []
    for user in sorted(users, key=lambda u: (u.name.lower(), u.id)):
        mark = marks.get(user.id)
        rows.append(
            RegisterRow(
                student_id=user.id,
                name=user.name,
                state=mark.state if mark else None,
                source=mark.source if mark else None,
                recorded_at=mark.recorded_at if mark else None,
            )
        )
    return rows


async def set_attendance(
    session: AsyncSession,
    lesson: Lesson,
    entries: list[AttendanceEntry],
    *,
    recorded_by: User | None,
    source: AttendanceSource = AttendanceSource.tutor,
) -> list[int]:
    """Upsert one row per (lesson, student) and commit. Returns the student ids
    skipped because a tutor's mark wins (always empty for a tutor write).

    Every student must be enrolled in the lesson's class, validated before any
    write; a tutor may also change or clear the mark of someone who has since
    left. Duplicate ids in one call collapse, last wins. A tutor write always
    wins. An integration write (`source != tutor`) never overwrites a tutor's
    mark and is recorded with no `recorded_by_id`.
    """
    from_tutor = source == AttendanceSource.tutor
    existing = {
        row.student_id: row
        for row in await session.scalars(
            select(LessonAttendance).where(LessonAttendance.lesson_id == lesson.id)
        )
    }
    allowed = await _enrolled_ids(session, lesson)
    if from_tutor:
        allowed |= set(existing)
    if any(e.student_id not in allowed for e in entries):
        raise AttendanceStudentNotFound
    entries = list({e.student_id: e for e in entries}.values())
    skipped: list[int] = []
    now = utcnow()
    for entry in entries:
        row = existing.get(entry.student_id)
        if not from_tutor and row is not None and row.source == AttendanceSource.tutor:
            skipped.append(entry.student_id)
            continue
        if entry.state is None:
            # An integration cannot "not take" what it never saw; only a tutor clears.
            if row is not None and from_tutor:
                await session.delete(row)
                existing.pop(entry.student_id)
            continue
        if row is None:
            row = LessonAttendance(
                organization_id=lesson.organization_id,
                lesson_id=lesson.id,
                student_id=entry.student_id,
                state=entry.state,
                source=source,
                recorded_by_id=recorded_by.id if from_tutor and recorded_by else None,
                recorded_at=now,
            )
            session.add(row)
            existing[entry.student_id] = row
        else:
            row.state = entry.state
            row.source = source
            row.recorded_by_id = recorded_by.id if from_tutor and recorded_by else None
            row.recorded_at = now
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race on UNIQUE (lesson, student)
        await session.rollback()
        raise AttendanceConflict from exc
    return skipped


async def delete_for_lesson(session: AsyncSession, lesson_id: int) -> None:
    """Remove a lesson's marks before the lesson goes. The FK cascades in
    Postgres; SQLite (the test database) has foreign keys off. Does not commit."""
    for row in await session.scalars(
        select(LessonAttendance).where(LessonAttendance.lesson_id == lesson_id)
    ):
        await session.delete(row)
    await session.flush()
