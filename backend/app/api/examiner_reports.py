"""Examiner reports: the board's published report for one paper sitting.

A shared library. Every other past-paper artifact is scoped to (organization,
subject) so one tutor's upload cannot reach another tutor's students, but an
examiner report is a public board document rather than a tutor's own
compilation, and the collection is meant to be built up once for everybody. So
these rows carry no organization_id and any tutor's past paper matches them on
(subject, paper number, session).

The cost of sharing is that a wrong upload changes marking for every
organization at once. Two things bound it: one report per paper, so the first
upload wins rather than being silently overwritten, and only the tutor who
uploaded it (or an admin) may replace or delete it. Anyone may add a paper
nobody has covered yet.

Tutor-only throughout, download included — examiner reports discuss the answers
the board expected, the same reason a mark scheme is tutor-only.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import ExaminerReport, Subject, User, UserRole
from app.schemas.past_paper import ExaminerReportOut
from app.services import storage

router = APIRouter(prefix="/examiner-reports", tags=["examiner-reports"])


def _require_tutor(user: User) -> None:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


def _can_manage(report: ExaminerReport, user: User) -> bool:
    """Who may replace or delete a shared row: whoever put it there, or an
    admin. A row whose uploader is gone is admin-only."""
    return user.role is UserRole.admin or (
        report.uploaded_by_tutor_id is not None
        and report.uploaded_by_tutor_id == user.id
    )


def _out(report: ExaminerReport, user: User) -> ExaminerReportOut:
    return ExaminerReportOut(
        id=report.id,
        subject_id=report.subject_id,
        paper_number=report.paper_number,
        session_label=report.session_label,
        file_name=report.file_name,
        can_manage=_can_manage(report, user),
    )


@router.post("", response_model=ExaminerReportOut, status_code=status.HTTP_201_CREATED)
async def upload_examiner_report(
    db: DbSession,
    user: CurrentUser,
    subject_id: Annotated[int, Form()],
    paper_number: Annotated[str, Form(min_length=1, max_length=32)],
    session_label: Annotated[str, Form(min_length=1, max_length=64)],
    file: Annotated[UploadFile, File()],
) -> ExaminerReportOut:
    _require_tutor(user)
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    existing = await db.scalar(
        select(ExaminerReport).where(
            ExaminerReport.subject_id == subject_id,
            ExaminerReport.paper_number == paper_number,
            ExaminerReport.session_label == session_label,
        )
    )
    if existing is not None:
        # Shared row: replacing it changes marking for every organization, so
        # only whoever uploaded it may. Everyone else gets told it exists
        # rather than silently overwriting another tutor's upload.
        if not _can_manage(existing, user):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "An examiner report for this paper is already in the shared library. "
                "Only the tutor who uploaded it can replace it.",
            )
        old_path = existing.file_path
        path, name, mime = await storage.save_upload(file)
        existing.file_path, existing.file_name, existing.file_mime = path, name, mime
        existing.uploaded_by_tutor_id = user.id
        await db.commit()
        storage.delete_file(old_path)
        return _out(existing, user)

    path, name, mime = await storage.save_upload(file)
    report = ExaminerReport(
        subject_id=subject_id,
        paper_number=paper_number,
        session_label=session_label,
        file_path=path,
        file_name=name,
        file_mime=mime,
        uploaded_by_tutor_id=user.id,
    )
    db.add(report)
    await db.flush()
    await db.commit()
    return _out(report, user)


@router.get("", response_model=list[ExaminerReportOut])
async def list_examiner_reports(
    db: DbSession, user: CurrentUser, subject_id: int | None = None
) -> list[ExaminerReportOut]:
    """What the shared library already covers, so a tutor can see the gaps."""
    _require_tutor(user)
    query = select(ExaminerReport)
    if subject_id is not None:
        query = query.where(ExaminerReport.subject_id == subject_id)
    reports = (
        await db.scalars(
            query.order_by(
                ExaminerReport.subject_id,
                ExaminerReport.paper_number,
                ExaminerReport.session_label,
            )
        )
    ).all()
    return [_out(r, user) for r in reports]


@router.get("/{report_id}/file")
async def download_examiner_report(report_id: int, db: DbSession, user: CurrentUser):
    _require_tutor(user)
    report = await db.get(ExaminerReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examiner report not found")
    return FileResponse(
        storage.absolute_path(report.file_path),
        media_type=report.file_mime,
        filename=report.file_name,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_examiner_report(report_id: int, db: DbSession, user: CurrentUser) -> None:
    _require_tutor(user)
    report = await db.get(ExaminerReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examiner report not found")
    if not _can_manage(report, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the tutor who uploaded this examiner report can remove it.",
        )
    path = report.file_path
    await db.delete(report)
    await db.commit()
    storage.delete_file(path)
