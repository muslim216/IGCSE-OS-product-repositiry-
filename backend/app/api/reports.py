from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, require_role
from app.api.readiness import visible_subject_ids
from app.models import (
    Report,
    ReportAudience,
    ReportStatus,
    Subject,
    User,
    UserRole,
)
from app.schemas.reports import ReportDetail, ReportGenerate, ReportOut
from app.workers.jobs import enqueue

router = APIRouter(prefix="/reports", tags=["reports"])

#: Same gate as TutorUser, keeping this endpoint's own 403 message rather than
#: quietly restyling it — the generic require_role() exists for exactly this.
ReportAuthor = Annotated[
    User,
    require_role(UserRole.tutor, UserRole.admin, detail="Only tutors can generate reports"),
]

ALLOWED_AUDIENCES = {
    UserRole.student: {ReportAudience.student},
    UserRole.parent: {ReportAudience.parent},
    UserRole.tutor: {ReportAudience.student, ReportAudience.tutor, ReportAudience.parent},
    UserRole.admin: {ReportAudience.student, ReportAudience.tutor, ReportAudience.parent},
}


async def _check_can_view_student(db: AsyncSession, viewer: User, student_id: int) -> None:
    # Raises 403/404 if the viewer may not see this student's data.
    if viewer.role == UserRole.student and viewer.id != student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    await visible_subject_ids(db, viewer, student_id)


@router.post("/generate", response_model=ReportDetail, status_code=status.HTTP_201_CREATED)
async def generate(body: ReportGenerate, db: DbSession, user: ReportAuthor) -> ReportDetail:
    audience = ReportAudience(body.audience)
    if audience not in ALLOWED_AUDIENCES[user.role]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"You cannot generate {audience.value} reports"
        )
    student = await db.get(User, body.student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    await _check_can_view_student(db, user, body.student_id)

    subject_name = "All subjects"
    if body.subject_id is not None:
        subject = await db.get(Subject, body.subject_id)
        if subject is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
        subject_name = subject.name

    title = f"{subject_name} — {audience.value} report ({datetime.now(timezone.utc):%d %b %Y})"
    report = Report(
        student_id=body.student_id,
        subject_id=body.subject_id,
        generated_by_id=user.id,
        audience=audience,
        status=ReportStatus.generating,
        title=title,
    )
    db.add(report)
    await db.flush()
    await enqueue(db, "generate_report", {"report_id": report.id})
    await db.commit()
    return _detail(report)


@router.get("", response_model=list[ReportOut])
async def list_reports(
    student_id: int, db: DbSession, user: CurrentUser
) -> list[ReportOut]:
    await _check_can_view_student(db, user, student_id)
    allowed = ALLOWED_AUDIENCES[user.role]
    rows = (
        await db.scalars(
            select(Report)
            .where(
                Report.student_id == student_id,
                Report.audience.in_(list(allowed)),
            )
            .order_by(Report.created_at.desc())
        )
    ).all()
    return [_out(r) for r in rows]


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(report_id: int, db: DbSession, user: CurrentUser) -> ReportDetail:
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if report.audience not in ALLOWED_AUDIENCES[user.role]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    await _check_can_view_student(db, user, report.student_id)
    return _detail(report)


def _out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        student_id=r.student_id,
        subject_id=r.subject_id,
        audience=r.audience.value,
        status=r.status.value,
        title=r.title,
        created_at=r.created_at,
        generated_at=r.generated_at,
    )


def _detail(r: Report) -> ReportDetail:
    return ReportDetail(
        **_out(r).model_dump(),
        content=r.content,
        error=r.error,
    )
