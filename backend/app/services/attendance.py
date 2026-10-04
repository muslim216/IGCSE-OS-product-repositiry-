"""Who was at a lesson (task 7.1, AV-44, AV-109).

Attendance is not a readiness factor (AV-33): nothing here touches `Evidence`,
`SOURCE_WEIGHTS` or queues a recompute. A student with no row was simply not
recorded, and is reported as such (`PROD-2`) — never defaulted to absent.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttendanceSource,
    AttendanceState,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    LessonMode,
    Organization,
    User,
)
from app.models.base import utcnow
from app.services.timezones import now_in

log = logging.getLogger(__name__)

#: How many of the latest lessons a class lists.
RECENT_LESSONS = 8


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
    # One try around the writes as well as the commit: an UPDATE below can
    # autoflush rows added earlier in the batch, and a lost race on the unique
    # (lesson, student) surfaces there rather than at commit.
    try:
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
            elif from_tutor:
                # Two tutors saving the same mark: last writer wins. Both are the
                # authoritative source, so neither save is lost data.
                row.state = entry.state
                row.source = source
                row.recorded_by_id = recorded_by.id if recorded_by else None
                row.recorded_at = now
            else:
                # Conditional in the database, not on the row read above: a tutor may
                # have marked this student since, and their mark must still win.
                updated = await session.execute(
                    update(LessonAttendance)
                    .where(
                        LessonAttendance.id == row.id,
                        LessonAttendance.source != AttendanceSource.tutor,
                    )
                    .values(state=entry.state, source=source, recorded_by_id=None, recorded_at=now)
                    .execution_options(synchronize_session=False)
                )
                if updated.rowcount != 1:  # type: ignore[attr-defined]
                    skipped.append(entry.student_id)
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


@dataclass(frozen=True)
class RecentLesson:
    lesson_id: int
    date: date
    start_time: time | None
    mode: LessonMode
    #: `None` means not taken — never absent (`PROD-2`).
    state: AttendanceState | None


@dataclass
class ClassAttendance:
    group_id: int
    group_name: str
    #: Lessons the class held that count for this student.
    lessons: int = 0
    present: int = 0
    absent: int = 0
    not_taken: int = 0
    recent: list[RecentLesson] = field(default_factory=list)

    @property
    def marked(self) -> int:
        return self.present + self.absent

    @property
    def rate(self) -> float | None:
        """present / (present + absent). Not-taken lessons are excluded, and
        `None` — not 0 — when nothing was marked (`PROD-2`)."""
        return self.present / self.marked if self.marked else None


@dataclass
class StudentAttendance:
    classes: list[ClassAttendance] = field(default_factory=list)

    @property
    def lessons(self) -> int:
        return sum(c.lessons for c in self.classes)

    @property
    def present(self) -> int:
        return sum(c.present for c in self.classes)

    @property
    def absent(self) -> int:
        return sum(c.absent for c in self.classes)

    @property
    def not_taken(self) -> int:
        return sum(c.not_taken for c in self.classes)

    @property
    def rate(self) -> float | None:
        marked = self.present + self.absent
        return self.present / marked if marked else None


def _local_date(moment: datetime, zone: str | None) -> date:
    """The calendar day `moment` falls on in the organization's zone. A naive
    datetime (SQLite) is UTC; an unusable zone degrades to UTC like `now_in`."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if zone:
        try:
            return moment.astimezone(ZoneInfo(zone)).date()
        except Exception:  # noqa: BLE001 - same degrade-to-UTC rule as now_in
            pass
    return moment.astimezone(timezone.utc).date()


async def student_attendance(
    session: AsyncSession,
    *,
    student_id: int,
    organization_id: int,
    group_id: int | None = None,
    tutor_id: int | None = None,
) -> StudentAttendance:
    """One student's attendance per class, inside one organization. This is the
    single read reports (task 8.6) will call; do not write a second query.

    Counts lessons dated on or before the organization's today. A class the
    student sits in contributes every such lesson; one they have left
    contributes only lessons that carry a mark for them. Lessons held before
    the student joined are not "not taken": `GroupMember.created_at` is the
    join moment (a row is added at enrolment), and a marked lesson always
    counts whatever the date. The join moment is converted to the
    organization's timezone before comparing with the lesson date.

    `tutor_id` limits the read to classes that tutor teaches; a tutor must not
    see a shared student's classes taught by someone else. Admin, parent and
    student pass `None` for the full view. A student enrolled in another
    organization's class is not shown (cross-org enrolment is a backlog item).
    """
    org = await session.get(Organization, organization_id)
    if org is None:
        log.warning("organization %s not found; attendance falls back to UTC", organization_id)
    zone = org.timezone if org else None
    today = now_in(zone).date()

    member_q = (
        select(GroupMember.group_id, GroupMember.created_at)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.organization_id == organization_id)
    )
    if group_id is not None:
        member_q = member_q.where(GroupMember.group_id == group_id)
    if tutor_id is not None:
        member_q = member_q.where(Group.tutor_id == tutor_id)
    joined = {
        gid: _local_date(created, zone) for gid, created in (await session.execute(member_q)).all()
    }

    lesson_q = (
        select(Lesson, LessonAttendance.state)
        .join(Group, Group.id == Lesson.group_id)
        .outerjoin(
            LessonAttendance,
            (LessonAttendance.lesson_id == Lesson.id) & (LessonAttendance.student_id == student_id),
        )
        .where(
            Lesson.organization_id == organization_id,
            Lesson.date <= today,
            Lesson.group_id.in_(joined) | LessonAttendance.id.is_not(None),
        )
        .order_by(Lesson.date.desc(), Lesson.id.desc())
    )
    if group_id is not None:
        lesson_q = lesson_q.where(Lesson.group_id == group_id)
    if tutor_id is not None:
        lesson_q = lesson_q.where(Group.tutor_id == tutor_id)

    per_group: dict[int, ClassAttendance] = {}
    for lesson, state in (await session.execute(lesson_q)).all():
        joined_on = joined.get(lesson.group_id)
        if state is None and joined_on is not None and lesson.date < joined_on:
            continue
        entry = per_group.setdefault(lesson.group_id, ClassAttendance(lesson.group_id, ""))
        entry.lessons += 1
        if state == AttendanceState.present:
            entry.present += 1
        elif state == AttendanceState.absent:
            entry.absent += 1
        else:
            entry.not_taken += 1
        if len(entry.recent) < RECENT_LESSONS:
            entry.recent.append(
                RecentLesson(lesson.id, lesson.date, lesson.start_time, lesson.mode, state)
            )
    if not per_group:
        return StudentAttendance()
    name_rows = await session.execute(select(Group.id, Group.name).where(Group.id.in_(per_group)))
    for gid, name in name_rows.all():
        per_group[gid].group_name = name
    return StudentAttendance(classes=sorted(per_group.values(), key=lambda c: c.group_name.lower()))
