from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor
from app.models import Subject, SyllabusUpload, SyllabusUploadStatus, Topic, User, UserRole
from app.schemas.syllabus import SyllabusDraft, SyllabusUploadDetail, SyllabusUploadOut
from app.services import storage
from app.services.grade_boundaries import defaults_for_scale
from app.workers.jobs import enqueue

router = APIRouter(prefix="/syllabus-uploads", tags=["syllabus"])


async def _owned_upload(db, user: User, upload_id: int) -> SyllabusUpload:
    assert_tutor(user)
    upload = await db.get(SyllabusUpload, upload_id)
    if upload is None or (upload.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus upload not found")
    return upload


def _detail(upload: SyllabusUpload) -> SyllabusUploadDetail:
    return SyllabusUploadDetail(
        id=upload.id,
        title=upload.title,
        file_name=upload.file_name,
        status=upload.status.value,
        error=upload.error,
        subject_id=upload.subject_id,
        created_at=upload.created_at,
        draft=SyllabusDraft.model_validate(upload.draft) if upload.draft else None,
    )


@router.post("", response_model=SyllabusUploadDetail, status_code=status.HTTP_201_CREATED)
async def upload_syllabus(
    db: DbSession,
    user: TutorUser,
    title: Annotated[str, Form(min_length=1, max_length=255)],
    file: Annotated[UploadFile, File()],
) -> SyllabusUploadDetail:
    path, name, mime = await storage.save_upload(file)
    upload = SyllabusUpload(
        tutor_id=user.id,
        title=title,
        file_path=path,
        file_name=name,
        file_mime=mime,
        status=SyllabusUploadStatus.extracting,
    )
    db.add(upload)
    await db.flush()
    await enqueue(db, "extract_syllabus", {"syllabus_upload_id": upload.id})
    await db.commit()
    return _detail(upload)


@router.get("", response_model=list[SyllabusUploadOut])
async def list_syllabus_uploads(db: DbSession, user: TutorUser) -> list[SyllabusUploadOut]:
    query = select(SyllabusUpload).order_by(SyllabusUpload.created_at.desc())
    if user.role != UserRole.admin:
        query = query.where(SyllabusUpload.tutor_id == user.id)
    rows = (await db.scalars(query)).all()
    return [
        SyllabusUploadOut(
            id=u.id,
            title=u.title,
            file_name=u.file_name,
            status=u.status.value,
            error=u.error,
            subject_id=u.subject_id,
            created_at=u.created_at,
        )
        for u in rows
    ]


@router.get("/{upload_id}", response_model=SyllabusUploadDetail)
async def get_syllabus_upload(
    upload_id: int, db: DbSession, user: CurrentUser
) -> SyllabusUploadDetail:
    upload = await _owned_upload(db, user, upload_id)
    return _detail(upload)


@router.put("/{upload_id}/draft", response_model=SyllabusUploadDetail)
async def edit_draft(
    upload_id: int, body: SyllabusDraft, db: DbSession, user: CurrentUser
) -> SyllabusUploadDetail:
    """Let the tutor correct the AI's draft (topic names, codes, weights, grade
    boundaries) before it's applied as a real subject."""
    upload = await _owned_upload(db, user, upload_id)
    if upload.status == SyllabusUploadStatus.applied:
        raise HTTPException(status.HTTP_409_CONFLICT, "This syllabus has already been applied")
    upload.draft = body.model_dump()
    if upload.status == SyllabusUploadStatus.extraction_failed:
        upload.status = SyllabusUploadStatus.review
    await db.commit()
    return _detail(upload)


@router.post("/{upload_id}/retry", response_model=SyllabusUploadDetail)
async def retry_syllabus_extraction(
    upload_id: int, db: DbSession, user: CurrentUser
) -> SyllabusUploadDetail:
    upload = await _owned_upload(db, user, upload_id)
    if upload.status != SyllabusUploadStatus.extraction_failed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a failed extraction can be retried")
    upload.status = SyllabusUploadStatus.extracting
    upload.error = None
    await enqueue(db, "extract_syllabus", {"syllabus_upload_id": upload.id})
    await db.commit()
    return _detail(upload)


@router.post("/{upload_id}/apply", response_model=SyllabusUploadDetail)
async def apply_syllabus(upload_id: int, db: DbSession, user: CurrentUser) -> SyllabusUploadDetail:
    """Create (or update) the real Subject + Topic tree from the reviewed
    draft. Idempotent on (exam_board, code), same as the seed loader."""
    upload = await _owned_upload(db, user, upload_id)
    if upload.status == SyllabusUploadStatus.applied:
        raise HTTPException(status.HTTP_409_CONFLICT, "This syllabus has already been applied")
    if not upload.draft:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No syllabus draft to apply yet")
    draft = SyllabusDraft.model_validate(upload.draft)

    subject = await db.scalar(
        select(Subject).where(Subject.exam_board == draft.exam_board, Subject.code == draft.code)
    )
    if subject is None:
        subject = Subject(exam_board=draft.exam_board, code=draft.code)
        db.add(subject)
    subject.name = draft.name
    subject.grade_scale = draft.grade_scale
    # A syllabus document usually does not print its grade boundaries — they are
    # published per series, not per specification — so the extraction commonly
    # returns none. Falling back to the standard split for the scale means a
    # tutor who uploads a syllabus gets working predicted grades on day one
    # rather than "no grade boundaries set" on every surface (spec §7.1). It is
    # a starting point, labelled as unconfirmed and editable; where the document
    # did state boundaries, those win.
    subject.grade_boundaries = [
        b.model_dump() for b in draft.grade_boundaries
    ] or defaults_for_scale(draft.grade_scale)
    await db.flush()

    existing = {
        t.code: t
        for t in (await db.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
    }

    async def upsert(node, parent_id: int | None) -> None:
        topic = existing.get(node.code)
        if topic is None:
            topic = Topic(subject_id=subject.id, code=node.code)
            db.add(topic)
        topic.title = node.title
        topic.parent_id = parent_id
        topic.weight = node.weight
        await db.flush()
        for child in node.children:
            await upsert(child, topic.id)

    for node in draft.topics:
        await upsert(node, None)

    upload.status = SyllabusUploadStatus.applied
    upload.subject_id = subject.id
    await db.commit()
    return _detail(upload)
