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
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, update
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


def _row(obj: object) -> dict:
    mapper = object_mapper(obj)
    row = {attr.key: _plain(getattr(obj, attr.key)) for attr in mapper.column_attrs}
    declared = SELF_DECLARED.get(str(mapper.persist_selectable.description))
    if declared:
        row["self_declared"] = {name: row.pop(name) for name in declared}
    return row


async def _rows(session: AsyncSession, model: type, column: str, value: object) -> list[object]:
    col = getattr(model, column)
    key = model.id if hasattr(model, "id") else col  # type: ignore[attr-defined]
    return list((await session.scalars(select(model).where(col == value).order_by(key))).all())


async def _rows_in(session: AsyncSession, model: type, column: str, ids: list[int]) -> list[object]:
    if not ids:
        return []
    col = getattr(model, column)
    return list(
        (await session.scalars(select(model).where(col.in_(ids)).order_by(model.id))).all()  # type: ignore[attr-defined]
    )


async def collect(session: AsyncSession, student: User) -> tuple[dict, list[PageFile]]:
    """Every row about `student`, as plain JSON-able dicts, and the page files.

    The student comes from the caller, who has already established that the
    requester may have them (`SEC-7`); nothing here takes an id from a request.
    """
    tables: dict[str, list[dict]] = {}
    objects: dict[str, list[object]] = {}
    for model, column in _BY_STUDENT:
        found = await _rows(session, model, column, student.id)
        objects[model.__tablename__] = found  # type: ignore[attr-defined]
        tables[model.__tablename__] = [_row(o) for o in found]  # type: ignore[attr-defined]

    submission_ids = [s.id for s in objects["submissions"]]  # type: ignore[attr-defined]
    files = await _rows_in(session, SubmissionFile, "submission_id", submission_ids)
    marks = await _rows_in(session, QuestionMark, "submission_id", submission_ids)
    mark_ids = [m.id for m in marks]  # type: ignore[attr-defined]
    mistake_ids = [m.id for m in objects["mistakes"]]  # type: ignore[attr-defined]
    for model, found in (
        (SubmissionFile, files),
        (QuestionMark, marks),
        (RemarkRequest, await _rows_in(session, RemarkRequest, "question_mark_id", mark_ids)),
        (
            MarkOverrideAudit,
            await _rows_in(session, MarkOverrideAudit, "question_mark_id", mark_ids),
        ),
        (
            MistakeRevisionAudit,
            await _rows_in(session, MistakeRevisionAudit, "mistake_id", mistake_ids),
        ),
    ):
        tables[model.__tablename__] = [_row(o) for o in found]  # type: ignore[attr-defined]

    profile = {
        key: _plain(getattr(student, key))
        for key in ("id", "name", "email", "username", "role", "time_zone", "created_at")
    }
    pages = [
        PageFile(f.submission_id, f.position, f.name, f.path)  # type: ignore[attr-defined]
        for f in files
    ]
    data = {
        "export": {
            "format_version": FORMAT_VERSION,
            "student_id": student.id,
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


async def build_zip(session: AsyncSession, student: User, workdir: Path) -> Path:
    """Write the export to `workdir` and return its path. Blocking zip work runs
    on a thread (`BE-13`); each page is read through storage and written before
    the next is fetched, so no more than one page is ever in memory."""
    data, pages = await collect(session, student)
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
        body = json.dumps(data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(archive.writestr, "data.json", body)
    finally:
        await asyncio.to_thread(archive.close)
    return path


async def _fail(session: AsyncSession, export_id: int, key: str | None) -> None:
    if key:
        try:
            await storage.delete_file(key)
        except Exception:  # noqa: BLE001 — the row still has to say failed
            log.warning("could not remove a failed export's file %s", key, exc_info=True)
    await session.execute(
        update(DataExport)
        .where(
            DataExport.id == export_id,
            DataExport.status.in_((DataExportStatus.pending, DataExportStatus.running)),
        )
        .values(status=DataExportStatus.failed, error=FAILED_MESSAGE)
    )
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
    await session.commit()

    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="avora-export-"))
    try:
        student = await session.get(User, student_id)
        if student is None or student.role != UserRole.student:
            raise LookupError("export names no student")
        zip_path = await build_zip(session, student, workdir)
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
        await _fail(session, export_id, key)
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


async def export_given_up(session: AsyncSession, payload: dict, error: str) -> None:
    """The `on_give_up` hook (see `register_handler`): a build the worker
    stopped at its time limit, or lost, leaves the row `running` for ever. Only
    an unfinished row is touched."""
    await session.execute(
        update(DataExport)
        .where(
            DataExport.id == payload["export_id"],
            DataExport.status.in_((DataExportStatus.pending, DataExportStatus.running)),
        )
        .values(status=DataExportStatus.failed, error=FAILED_MESSAGE)
    )


async def expire_data_exports(session: AsyncSession, now: datetime) -> int:
    """Delete the file of every export past its `expires_at` and mark it
    expired. Safe to re-run: an expired row is not picked again, and a file
    already gone is not an error. Returns how many were expired."""
    due = (
        await session.scalars(
            select(DataExport).where(
                DataExport.status == DataExportStatus.ready, DataExport.expires_at <= now
            )
        )
    ).all()
    expired = 0
    for export in due:
        if export.storage_key:
            try:
                await storage.delete_file(export.storage_key)
            except Exception:  # noqa: BLE001 — try again tomorrow; the file must really go
                log.warning("could not delete export file %s", export.storage_key, exc_info=True)
                continue
        export.status = DataExportStatus.expired
        export.storage_key = None
        await session.commit()
        expired += 1
    return expired


async def request_export(session: AsyncSession, student: User, requester: User) -> DataExport:
    """The requester's export of `student` that is already being built, or a new
    one queued. One in flight per (child, requester): asking twice while the
    first is working returns the first instead of queuing a second ZIP.

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
