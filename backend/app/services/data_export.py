"""A child's data as a ZIP (launch audit P-3, part 2 of 3).

`data.json` holds every row Avora keeps about one student; `files/<submission_id>/`
holds every page they handed in. The ZIP is built on disk, never in memory
(`BE-13`), uploaded under a server-generated key (`SEC-16`), and deleted seven
days after it is ready.

What is collected is a list, not a scan, so a new table is a decision rather than
an accident: `EXPORTED` names every table that goes in and `NOT_EXPORTED` names
every table that holds a student key and stays out, each with its reason.
`tests/test_data_export.py` fails on a table with a student key in neither, which
is how the next one gets noticed.
"""

import asyncio
import enum
import json
import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import object_mapper

from app.models import (
    AiUsageEvent,
    AssessmentScore,
    AttemptRedo,
    ContactPoint,
    CustomCriterionScore,
    CustomCriterionScoreAudit,
    DataExport,
    DataExportStatus,
    DismissedPrompt,
    Evidence,
    FactorEvaluation,
    GroupMember,
    GroupRemoval,
    LessonAttendance,
    LessonObservation,
    MarkOverrideAudit,
    MeetingParticipant,
    Mistake,
    MistakeRevisionAudit,
    MistakeTopic,
    MockOpening,
    Narrative,
    Notification,
    NotificationPreference,
    ParentCommunication,
    ParentLink,
    ParentLinkRemoval,
    PastPaperAttempt,
    QuestionMark,
    ReadinessSnapshot,
    RemarkRequest,
    Report,
    ReportAudience,
    ReportStatus,
    StudentProfile,
    StudentSubject,
    Submission,
    SubmissionFile,
    TutorNote,
    TutorObservation,
    User,
    UserRole,
    WeeklySend,
)
from app.services import storage
from app.workers.jobs import enqueue

log = logging.getLogger(__name__)

EXPORT_JOB = "export_student_data"
EXPORT_TTL = timedelta(days=7)
FORMAT_VERSION = 1

#: A requester may start this many builds per child in a day, failed ones
#: included, so a build that keeps failing cannot be re-asked without end.
MAX_BUILDS_PER_DAY = 3

#: Ids per `IN (...)`: Postgres refuses a statement with more than 32767 bind
#: parameters, and years of marks on one child can pass that.
ID_CHUNK = 5000

#: What a parent's copy leaves out: the tutor's private working material. The
#: tutor's and an admin's copy hold everything.
PARENT_EXCLUDED: frozenset[str] = frozenset(
    {
        "tutor_notes",
        "parent_communications",
        "tutor_observations",
        "lesson_observations",
        "mark_override_audit",
        "mistake_revision_audit",
        "ai_usage_events",
    }
)

#: Columns left out of every copy. A storage key is an internal address; the
#: page itself is in files/. `suggested_student_id` names a *different*
#: student, a guess the tutor was shown.
DROP_COLUMNS: dict[str, tuple[str, ...]] = {
    "submission_files": ("path",),
    "meeting_participants": ("suggested_student_id",),
}

#: Tables kept to these columns only: other adults' ids and emails are not this
#: child's data, so only when and by which role remain.
ONLY_COLUMNS: dict[str, tuple[str, ...]] = {
    "parent_links": ("created_at",),
    "parent_link_removals": ("created_at", "removed_by_role"),
}

#: A storage key wherever one is nested in a stored record (a redo record keeps
#: the replaced pages' keys in JSON).
_KEY = re.compile(r"(?:org/\d+/)?(?:exports/)?[0-9a-f]{32}\.[a-z0-9]+")

#: Shown to whoever asks again, and stored on the row. Short and free of
#: internals; the traceback is in the log.
FAILED_MESSAGE = "The export could not be built. Please request it again."

#: Fields the student (or their parent) types in and Avora cannot check
#: (`PROD-8`). They are grouped under `self_declared` rather than sitting beside
#: measured values, so a reader of the file cannot mistake one for the other.
SELF_DECLARED: dict[str, tuple[str, ...]] = {
    "submissions": ("timed", "time_taken_minutes", "attempted_at"),
    "past_paper_attempts": ("timed", "time_taken_minutes", "attempted_at"),
}

#: (model, the column holding the student). Rows are read as they are stored.
_BY_STUDENT: tuple[tuple[type, str], ...] = (
    (StudentProfile, "student_id"),
    (StudentSubject, "student_id"),
    (TutorNote, "student_id"),
    (ParentCommunication, "student_id"),
    (LessonAttendance, "student_id"),
    (LessonObservation, "student_id"),
    (TutorObservation, "student_id"),
    (Submission, "student_id"),
    (Evidence, "student_id"),
    (AssessmentScore, "student_id"),
    (Mistake, "student_id"),
    (PastPaperAttempt, "student_id"),
    (FactorEvaluation, "student_id"),
    (ReadinessSnapshot, "student_id"),
    (Report, "student_id"),
    (Narrative, "student_id"),
    (CustomCriterionScore, "student_id"),
    (CustomCriterionScoreAudit, "student_id"),
    (MockOpening, "student_id"),
    (AttemptRedo, "student_id"),
    (GroupMember, "student_id"),
    (ParentLink, "student_id"),
    (ParentLinkRemoval, "student_id"),
    (MeetingParticipant, "matched_student_id"),
    (AiUsageEvent, "student_id"),
    # Keyed by the student as a person rather than as a pupil.
    (GroupRemoval, "user_id"),
    (Notification, "recipient_user_id"),
    (ContactPoint, "user_id"),
    (NotificationPreference, "user_id"),
    (DismissedPrompt, "user_id"),
    (WeeklySend, "recipient_user_id"),
)

#: Tables read through a parent row's id, not a student column of their own.
_CHILD_TABLES = (
    "submission_files",
    "question_marks",
    "remark_requests",
    "mark_override_audit",
    "mistake_revision_audit",
    "mistake_topics",
)

EXPORTED: frozenset[str] = frozenset(
    {model.__tablename__ for model, _ in _BY_STUDENT}  # type: ignore[attr-defined]
    | set(_CHILD_TABLES)
    | {"users"}
)

#: Tables that hold a student or user key and are left out, and why.
NOT_EXPORTED: dict[str, str] = {
    "invites": "a join code is a credential for the next person, not data about this child",
    "refresh_sessions": "sign-in credentials",
    "jobs": "queue plumbing; the work it did is in the tables above",
}


@dataclass
class PageFile:
    submission_id: int
    position: int
    name: str
    key: str


def _plain(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    return value


def _scrub(value: object) -> object:
    if isinstance(value, str):
        return "[stored file]" if _KEY.fullmatch(value) else value
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _row(obj: object) -> dict:
    mapper = object_mapper(obj)
    table = str(mapper.persist_selectable.description)
    row = {attr.key: _plain(getattr(obj, attr.key)) for attr in mapper.column_attrs}
    if table in ONLY_COLUMNS:
        row = {k: row[k] for k in ONLY_COLUMNS[table]}
    for name in DROP_COLUMNS.get(table, ()):
        row.pop(name, None)
    declared = SELF_DECLARED.get(table)
    if declared:
        row["self_declared"] = {name: row.pop(name) for name in declared}
    return _scrub(row)  # type: ignore[return-value]


def _convert(objects: dict[str, list[object]]) -> dict[str, list[dict]]:
    """Plain dicts from loaded rows. Pure CPU, so it runs on a thread; every
    attribute read is already loaded, nothing here touches the database."""
    return {name: [_row(o) for o in found] for name, found in objects.items()}


async def _rows(
    session: AsyncSession, model: type, column: str, value: object, *extra: object
) -> list[object]:
    col = getattr(model, column)
    key = model.id if hasattr(model, "id") else col  # type: ignore[attr-defined]
    query = select(model).where(col == value, *extra).order_by(key)  # type: ignore[arg-type,var-annotated]
    return list((await session.scalars(query)).all())


async def _rows_in(session: AsyncSession, model: type, column: str, ids: list[int]) -> list[object]:
    found: list[object] = []
    col = getattr(model, column)
    for start in range(0, len(ids), ID_CHUNK):
        chunk = ids[start : start + ID_CHUNK]
        found.extend((await session.scalars(select(model).where(col.in_(chunk)))).all())
    found.sort(key=lambda o: o.id)  # type: ignore[attr-defined]
    return found


def audience_for(requester: User | None) -> str:
    """`parent` for a parent (or an account since removed, the safe default),
    `full` for a tutor or admin."""
    return "full" if requester is not None and requester.role != UserRole.parent else "parent"


async def collect(
    session: AsyncSession, student: User, audience: str = "full"
) -> tuple[dict, list[PageFile]]:
    """Every row about `student` that `audience` may have, as plain JSON-able
    dicts, and the page files.

    The student comes from the caller, who has already established that the
    requester may have them (`SEC-7`); nothing here takes an id from a request.
    """
    parent = audience == "parent"
    objects: dict[str, list[object]] = {}
    for model, column in _BY_STUDENT:
        name = model.__tablename__  # type: ignore[attr-defined]
        if parent and name in PARENT_EXCLUDED:
            continue
        # A parent sees only the reports written for parents and finished.
        extra = (
            (Report.audience == ReportAudience.parent, Report.status == ReportStatus.ready)
            if parent and model is Report
            else ()
        )
        objects[name] = await _rows(session, model, column, student.id, *extra)

    submission_ids = [s.id for s in objects["submissions"]]  # type: ignore[attr-defined]
    files = await _rows_in(session, SubmissionFile, "submission_id", submission_ids)
    marks = await _rows_in(session, QuestionMark, "submission_id", submission_ids)
    mark_ids = [m.id for m in marks]  # type: ignore[attr-defined]
    mistake_ids = [m.id for m in objects["mistakes"]]  # type: ignore[attr-defined]
    objects["submission_files"] = files
    objects["question_marks"] = marks
    objects["remark_requests"] = await _rows_in(
        session, RemarkRequest, "question_mark_id", mark_ids
    )
    objects["mistake_topics"] = await _rows_in(session, MistakeTopic, "mistake_id", mistake_ids)
    if not parent:
        objects["mark_override_audit"] = await _rows_in(
            session, MarkOverrideAudit, "question_mark_id", mark_ids
        )
        objects["mistake_revision_audit"] = await _rows_in(
            session, MistakeRevisionAudit, "mistake_id", mistake_ids
        )

    pages = [
        PageFile(f.submission_id, f.position, f.name, f.path)  # type: ignore[attr-defined]
        for f in files
    ]
    tables = await asyncio.to_thread(_convert, objects)
    profile = {
        key: _plain(getattr(student, key))
        for key in ("id", "name", "email", "username", "role", "time_zone", "created_at")
    }
    data = {
        "export": {
            "format_version": FORMAT_VERSION,
            "student_id": student.id,
            "audience": audience,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "notes": [
                "Rows are as Avora stores them. Fields under `self_declared` were typed in "
                "by the student or their parent and Avora cannot check them.",
                "Pages handed in are in the files/ folder, under the submission they belong to.",
            ],
        },
        "profile": profile,
        "tables": tables,
    }
    return data, pages


def _page_name(page: PageFile) -> str:
    # The client's filename is metadata only (`SEC-16`): it never becomes a
    # path. The position leads so the pages stay in order, and the separators
    # go so a name cannot climb out of its folder.
    clean = storage.safe_filename(page.name).replace("/", "_").replace("\\", "_")
    return f"files/{page.submission_id}/{page.position:02d}-{clean.lstrip('.')}"


def _open_zip(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)


async def build_zip(
    session: AsyncSession, student: User, workdir: Path, audience: str = "full"
) -> Path:
    """Write the export to `workdir` and return its path. Blocking zip work runs
    on a thread (`BE-13`); each page is read through storage and written before
    the next is fetched, so no more than one page is ever in memory."""
    data, pages = await collect(session, student, audience)
    # Nothing was written; hand the connection back before the slow part.
    await session.commit()
    path = workdir / "export.zip"
    archive = await asyncio.to_thread(_open_zip, path)
    missing: list[dict] = []
    listed: list[dict] = []
    try:
        for page in pages:
            entry = _page_name(page)
            try:
                content = await storage.read_file(page.key)
            except storage.ObjectNotFoundError:
                # Gone from storage already; say so rather than fail the lot.
                missing.append({"submission_id": page.submission_id, "name": page.name})
                continue
            await asyncio.to_thread(archive.writestr, entry, content)
            listed.append({"submission_id": page.submission_id, "name": page.name, "file": entry})
        data["files"] = listed
        data["files_missing"] = missing
        body = await asyncio.to_thread(json.dumps, data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(archive.writestr, "data.json", body)
    finally:
        await asyncio.to_thread(archive.close)
    return path


async def _discard_file(key: str | None) -> bool:
    """Delete an export's stored file. True when it is gone (or never was)."""
    if not key:
        return True
    try:
        await storage.delete_file(key)
    except Exception:  # noqa: BLE001 — the caller decides what a leftover means
        log.warning("could not remove export file %s", key, exc_info=True)
        return False
    return True


async def _mark_failed(session: AsyncSession, export_id: int) -> None:
    """End an unfinished export as failed and take its file with it, so a failed
    build leaves nothing behind. Only a pending or running row is touched."""
    export = await session.get(DataExport, export_id)
    if export is None or export.status not in (
        DataExportStatus.pending,
        DataExportStatus.running,
    ):
        return
    # A file that would not delete keeps its key: the expiry sweep retries it.
    if await _discard_file(export.storage_key):
        export.storage_key = None
    export.status = DataExportStatus.failed
    export.error = FAILED_MESSAGE


async def _fail(session: AsyncSession, export_id: int) -> None:
    await _mark_failed(session, export_id)
    await session.commit()


async def export_student_data(session: AsyncSession, payload: dict) -> None:
    """Job handler. The payload is the export's id and nothing else (`BE-9`).

    Safe to re-run (`BE-6`): a finished, failed or expired export is left alone,
    and a run that died part-way starts again from the row and rewrites the same
    key, so a retry leaves one file, not two.

    A failure is recorded on the row and the job ends normally: a retry of a
    build that failed for a reason of its own would fail the same way, and the
    requester can simply ask again. The row is never left `running`."""
    export = await session.get(DataExport, payload["export_id"])
    if export is None or export.status not in (DataExportStatus.pending, DataExportStatus.running):
        return
    export_id = export.id
    export.status = DataExportStatus.running
    export.error = None
    if export.storage_key is None:
        export.storage_key = storage.new_export_key(export.organization_id)
    key = export.storage_key
    student_id = export.student_id
    requester_id = export.requested_by_id
    await session.commit()

    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="avora-export-"))
    try:
        student = await session.get(User, student_id)
        if student is None or student.role != UserRole.student:
            raise LookupError("export names no student")
        requester = await session.get(User, requester_id) if requester_id is not None else None
        zip_path = await build_zip(session, student, workdir, audience_for(requester))
        await storage.get_storage().upload_path(key, zip_path, "application/zip")
        await session.execute(
            update(DataExport)
            .where(DataExport.id == export_id)
            .values(
                status=DataExportStatus.ready,
                expires_at=datetime.now(timezone.utc) + EXPORT_TTL,
            )
        )
        await session.commit()
    except Exception:
        log.exception("data export %s failed", export_id)
        await session.rollback()
        await _fail(session, export_id)
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


async def export_given_up(session: AsyncSession, payload: dict, error: str) -> None:
    """The `on_give_up` hook (see `register_handler`): a build the worker
    stopped at its time limit, or lost, leaves the row `running` for ever and
    may have left a half-built file. Only an unfinished row is touched."""
    await _mark_failed(session, payload["export_id"])


async def expire_data_exports(session: AsyncSession, now: datetime) -> int:
    """Delete the file of every export past its `expires_at` and mark it
    expired; also clear a file still held by a failed export. Safe to re-run: an
    expired row is not picked again, and a file already gone is not an error. A
    file that will not delete leaves its row as it was, for the next pass.
    Returns how many were expired."""
    due = (
        await session.scalars(
            select(DataExport).where(
                DataExport.status == DataExportStatus.ready, DataExport.expires_at <= now
            )
        )
    ).all()
    expired = 0
    for export in due:
        if not await _discard_file(export.storage_key):
            continue
        export.status = DataExportStatus.expired
        export.storage_key = None
        await session.commit()
        expired += 1
    leftovers = (
        await session.scalars(
            select(DataExport).where(
                DataExport.status == DataExportStatus.failed, DataExport.storage_key.is_not(None)
            )
        )
    ).all()
    for export in leftovers:
        if await _discard_file(export.storage_key):
            export.storage_key = None
            await session.commit()
    return expired


async def request_export(session: AsyncSession, student: User, requester: User) -> DataExport:
    """The requester's export of `student` that is already being built, or a new
    one queued. One in flight per (child, requester): asking twice while the
    first is working returns the first instead of queuing a second ZIP, and a
    finished one that has not expired is handed back rather than rebuilt. At
    most `MAX_BUILDS_PER_DAY` builds per requester per child per day (429).

    The caller has already established that `requester` may have this child.
    The child's row is locked for the check (a no-op on SQLite) so two clicks at
    once cannot both find nothing and both queue."""
    await session.execute(select(User.id).where(User.id == student.id).with_for_update())
    live = await session.scalar(
        select(DataExport)
        .where(
            DataExport.student_id == student.id,
            DataExport.requested_by_id == requester.id,
            DataExport.status.in_((DataExportStatus.pending, DataExportStatus.running)),
        )
        .order_by(DataExport.id.desc())
        .limit(1)
    )
    if live is not None:
        return live
    now = datetime.now(timezone.utc)
    mine = [DataExport.student_id == student.id, DataExport.requested_by_id == requester.id]
    for ready in (
        await session.scalars(
            select(DataExport)
            .where(*mine, DataExport.status == DataExportStatus.ready)
            .order_by(DataExport.id.desc())
        )
    ).all():
        if not is_expired(ready, now):
            return ready
    today = await session.scalar(
        select(func.count(DataExport.id)).where(
            *mine, DataExport.created_at > now - timedelta(days=1)
        )
    )
    if (today or 0) >= MAX_BUILDS_PER_DAY:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You have asked for this data several times today. Try again tomorrow.",
        )
    export = DataExport(
        organization_id=student.organization_id,
        student_id=student.id,
        requested_by_id=requester.id,
    )
    session.add(export)
    await session.flush()
    await enqueue(session, EXPORT_JOB, {"export_id": export.id})
    await session.commit()
    return export


async def requested_export(
    session: AsyncSession, student: User, requester: User, export_id: int
) -> DataExport | None:
    """An export of `student` that `requester` asked for, or None. Only the
    person who asked can read it: the ZIP is the child's whole record, and a
    second adult with access to the child is not thereby entitled to a copy
    someone else requested (`SEC-9`)."""
    return await session.scalar(
        select(DataExport).where(
            DataExport.id == export_id,
            DataExport.student_id == student.id,
            DataExport.organization_id == student.organization_id,
            DataExport.requested_by_id == requester.id,
        )
    )


def is_expired(export: DataExport, now: datetime) -> bool:
    if export.status == DataExportStatus.expired:
        return True
    if export.status != DataExportStatus.ready or export.expires_at is None:
        return False
    when = export.expires_at
    if when.tzinfo is None:  # SQLite hands back naive datetimes
        when = when.replace(tzinfo=timezone.utc)
    return when <= now
