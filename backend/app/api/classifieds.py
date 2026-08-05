from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.models import (
    Assignment,
    AssignmentStatus,
    Classified,
    Group,
    GroupMember,
    Subject,
    User,
    UserRole,
)
from app.schemas.homework import ClassifiedOut
from app.services import storage

router = APIRouter(prefix="/classifieds", tags=["classifieds"])


@router.post("", response_model=ClassifiedOut, status_code=status.HTTP_201_CREATED)
async def upload_classified(
    db: DbSession,
    user: TutorUser,
    title: Annotated[str, Form(min_length=1, max_length=255)],
    subject_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> ClassifiedOut:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    path, name, mime = await storage.save_upload(file)
    classified = Classified(
        organization_id=user.organization_id,
        tutor_id=user.id,
        subject_id=subject.id,
        title=title,
        file_path=path,
        file_name=name,
        file_mime=mime,
    )
    if mark_scheme is not None:
        ms_path, ms_name, ms_mime = await storage.save_upload(mark_scheme)
        classified.mark_scheme_path = ms_path
        classified.mark_scheme_name = ms_name
        classified.mark_scheme_mime = ms_mime
    db.add(classified)
    await db.commit()
    return ClassifiedOut.model_validate(classified)


@router.get("", response_model=list[ClassifiedOut])
async def list_classifieds(
    db: DbSession, user: TutorUser, subject_id: int | None = None
) -> list[ClassifiedOut]:
    query = select(Classified).where(Classified.tutor_id == user.id).order_by(Classified.created_at.desc())
    if subject_id is not None:
        query = query.where(Classified.subject_id == subject_id)
    rows = (await db.scalars(query)).all()
    return [ClassifiedOut.model_validate(c) for c in rows]


async def _can_view_classified(db, user: User, classified: Classified) -> bool:
    if user.id == classified.tutor_id or user.role == UserRole.admin:
        return True
    # Students may view classifieds used by a published assignment in their groups.
    row = await db.scalar(
        select(Assignment.id)
        .join(GroupMember, GroupMember.group_id == Assignment.group_id)
        .where(
            Assignment.classified_id == classified.id,
            Assignment.status.in_([AssignmentStatus.published, AssignmentStatus.closed]),
            GroupMember.student_id == user.id,
        )
        .limit(1)
    )
    return row is not None


@router.get("/{classified_id}/file")
async def download_classified(classified_id: int, db: DbSession, user: CurrentUser) -> FileResponse:
    classified = await db.get(Classified, classified_id)
    if classified is None or not await _can_view_classified(db, user, classified):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(
        storage.absolute_path(classified.file_path),
        media_type=classified.file_mime,
        filename=classified.file_name,
    )


@router.get("/{classified_id}/mark-scheme")
async def download_mark_scheme(classified_id: int, db: DbSession, user: CurrentUser) -> FileResponse:
    classified = await db.get(Classified, classified_id)
    if classified is None or classified.mark_scheme_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # Mark schemes are tutor-only: students should not download the answers.
    if classified.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(
        storage.absolute_path(classified.mark_scheme_path),
        media_type=classified.mark_scheme_mime,
        filename=classified.mark_scheme_name,
    )
