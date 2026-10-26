"""Downloading and erasing a child's data (launch audit P-3, parts 2 and 3 of 3).

Who may ask: the child's tutor (a student they teach), a linked parent (their own
child) and a workspace admin (their own organization). Never the student. Anyone
else, and any export that is not the caller's own, is a 404 (`API-7`, `SEC-9`);
the role gates are in the signatures (`SEC-11`, `BE-17`). The ZIP is built by a
background job (`services/data_export.py`) and kept seven days.

Erasure is asked by the same three, with the child's full name typed to confirm,
and waits out a 14-day undo window before the retention sweep wipes the child
(`services/erasure.py`). The student cannot ask, and a child already wiped is a
404 like any child the caller may not know exists.
"""

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.background import BackgroundTask

from app.api.deps import DbSession, ParentUser, TutorUser
from app.api.students import _tutor_student
from app.models import DataExport, DataExportStatus, ErasureRequest, ParentLink, User, UserRole
from app.schemas.erasure import DataExportOut, ErasureRequestIn, ErasureRequestOut
from app.services import data_export, erasure, storage

log = logging.getLogger("api")

router = APIRouter(tags=["erasure"])

_ZIP_RESPONSES: dict[int | str, dict] = {
    200: {
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The ZIP.",
    },
    410: {"description": "The export has expired; request a new one."},
}


def _out(export: DataExport) -> DataExportOut:
    return DataExportOut(
        id=export.id, status=export.status.value, expires_at=export.expires_at, error=export.error
    )


async def _linked_child(db: DbSession, parent: User, student_id: int) -> User:
    """The caller's own linked child, or 404 (the link is looked up on every
    request, so ending it revokes this at once)."""
    link = await db.scalar(
        select(ParentLink.id).where(
            ParentLink.parent_id == parent.id, ParentLink.student_id == student_id
        )
    )
    student = await db.get(User, student_id) if link is not None else None
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


_EXPORT_NOT_FOUND = "Export not found"


async def _own_export(db: DbSession, student: User, user: User, export_id: int) -> DataExport:
    export = await data_export.requested_export(db, student, user, export_id)
    if export is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _EXPORT_NOT_FOUND)
    return export


async def _zip_response(export: DataExport) -> Response:
    if data_export.is_expired(export, datetime.now(timezone.utc)):
        raise HTTPException(status.HTTP_410_GONE, "This export has expired. Request a new one.")
    if export.status != DataExportStatus.ready or not export.storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _EXPORT_NOT_FOUND)
    # Copied to a temp file and streamed from there: the ZIP can be large, and
    # the API must not hold it in memory (`BE-13`).
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="avora-download-"))
    try:
        await storage.get_storage().download_to_path(export.storage_key, workdir / "export.zip")
    except storage.ObjectNotFoundError:
        await asyncio.to_thread(shutil.rmtree, workdir, True)
        raise HTTPException(status.HTTP_404_NOT_FOUND, _EXPORT_NOT_FOUND) from None
    except Exception:
        await asyncio.to_thread(shutil.rmtree, workdir, True)
        log.exception("could not read export %s", export.id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Storage is temporarily unavailable"
        ) from None
    return FileResponse(
        workdir / "export.zip",
        media_type="application/zip",
        headers={
            "Content-Disposition": storage.content_disposition(
                f"avora-student-{export.student_id}-data.zip"
            ),
            "Cache-Control": "no-store, private",
        },
        background=BackgroundTask(shutil.rmtree, workdir, True),
    )


async def _queue(db: DbSession, student: User, user: User) -> DataExportOut:
    try:
        return _out(await data_export.request_export(db, student, user))
    except data_export.ExportLimitReached:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, data_export.LIMIT_MESSAGE) from None


@router.post(
    "/students/{student_id}/export",
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_student_export(student_id: int, db: DbSession, user: TutorUser) -> DataExportOut:
    """Ask for a student's data as a ZIP. Returns the export already being built,
    if the caller has one."""
    student = await _tutor_student(db, user, student_id)
    return await _queue(db, student, user)


@router.get("/students/{student_id}/export/{export_id}")
async def student_export_status(
    student_id: int, export_id: int, db: DbSession, user: TutorUser
) -> DataExportOut:
    student = await _tutor_student(db, user, student_id)
    return _out(await _own_export(db, student, user, export_id))


@router.get(
    "/students/{student_id}/export/{export_id}/file",
    response_class=Response,
    responses=_ZIP_RESPONSES,
)
async def student_export_file(
    student_id: int, export_id: int, db: DbSession, user: TutorUser
) -> Response:
    student = await _tutor_student(db, user, student_id)
    return await _zip_response(await _own_export(db, student, user, export_id))


@router.post(
    "/me/children/{student_id}/export",
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_child_export(student_id: int, db: DbSession, user: ParentUser) -> DataExportOut:
    student = await _linked_child(db, user, student_id)
    return await _queue(db, student, user)


@router.get("/me/children/{student_id}/export/{export_id}")
async def child_export_status(
    student_id: int, export_id: int, db: DbSession, user: ParentUser
) -> DataExportOut:
    student = await _linked_child(db, user, student_id)
    return _out(await _own_export(db, student, user, export_id))


@router.get(
    "/me/children/{student_id}/export/{export_id}/file",
    response_class=Response,
    responses=_ZIP_RESPONSES,
)
async def child_export_file(
    student_id: int, export_id: int, db: DbSession, user: ParentUser
) -> Response:
    student = await _linked_child(db, user, student_id)
    return await _zip_response(await _own_export(db, student, user, export_id))


# ------------------------------------------------------------------- erasure


def _erasure_out(request: ErasureRequest) -> ErasureRequestOut:
    return ErasureRequestOut(
        id=request.id,
        status=request.status.value,
        scheduled_for=request.scheduled_for,
        requested_role=request.requested_role.value,
        created_at=request.created_at,
    )


def _live(student: User) -> User:
    """A child already wiped is the blank placeholder: nothing to ask about."""
    if student.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


async def _ask(db: DbSession, student: User, user: User, body: ErasureRequestIn):
    try:
        return _erasure_out(await erasure.request_erasure(db, student, user, body.confirm_name))
    except erasure.NameMismatch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, erasure.NAME_MISMATCH) from None


async def _waiting(db: DbSession, student: User) -> ErasureRequestOut | None:
    request = await erasure.pending_request(db, student.id)
    return _erasure_out(request) if request is not None else None


async def _undo(db: DbSession, student: User, user: User) -> None:
    if not await erasure.cancel_erasure(db, student, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No deletion is scheduled for this student")


@router.post("/students/{student_id}/erasure", status_code=status.HTTP_202_ACCEPTED)
async def request_student_erasure(
    student_id: int, body: ErasureRequestIn, db: DbSession, user: TutorUser
) -> ErasureRequestOut:
    """Schedule a student's deletion in 14 days; they cannot sign in meanwhile.
    Returns the request already waiting, if there is one."""
    return await _ask(db, _live(await _tutor_student(db, user, student_id)), user, body)


@router.get("/students/{student_id}/erasure")
async def student_erasure_status(
    student_id: int, db: DbSession, user: TutorUser
) -> ErasureRequestOut | None:
    return await _waiting(db, _live(await _tutor_student(db, user, student_id)))


@router.delete("/students/{student_id}/erasure", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_student_erasure(student_id: int, db: DbSession, user: TutorUser) -> None:
    await _undo(db, _live(await _tutor_student(db, user, student_id)), user)


@router.post("/me/children/{student_id}/erasure", status_code=status.HTTP_202_ACCEPTED)
async def request_child_erasure(
    student_id: int, body: ErasureRequestIn, db: DbSession, user: ParentUser
) -> ErasureRequestOut:
    return await _ask(db, _live(await _linked_child(db, user, student_id)), user, body)


@router.get("/me/children/{student_id}/erasure")
async def child_erasure_status(
    student_id: int, db: DbSession, user: ParentUser
) -> ErasureRequestOut | None:
    return await _waiting(db, _live(await _linked_child(db, user, student_id)))


@router.delete("/me/children/{student_id}/erasure", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_child_erasure(student_id: int, db: DbSession, user: ParentUser) -> None:
    await _undo(db, _live(await _linked_child(db, user, student_id)), user)
