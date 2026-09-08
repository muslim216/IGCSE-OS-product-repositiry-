from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor
from app.models import (
    Chapter,
    Subject,
    SyllabusUpload,
    SyllabusUploadStatus,
    Topic,
    User,
    UserRole,
)
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
    path, name, mime = await storage.save_upload(file, organization_id=user.organization_id)
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
    """Let the tutor correct the AI's draft (chapter and topic names, codes,
    weights, the level) before it's applied as a real subject."""
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
    """Create (or update) the real Subject + Chapter + Topic tree from the reviewed draft.

    Idempotent on (organization, exam_board, code) — the tenant is part of a
    subject's identity since task 2.2, so re-applying updates *this* tutor's
    subject and never another tenant's.
    """
    upload = await _owned_upload(db, user, upload_id)
    if upload.status == SyllabusUploadStatus.applied:
        raise HTTPException(status.HTTP_409_CONFLICT, "This syllabus has already been applied")
    if not upload.draft:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No syllabus draft to apply yet")
    draft = SyllabusDraft.model_validate(upload.draft)

    if draft.level is None:
        # AV-7: nothing may assume an IGCSE-shaped world, and PROD-2 forbids
        # inventing a value to fill a gap. The tutor reviews the draft before
        # applying it, so asking is cheap; guessing is a wrong label on every
        # screen that shows the subject.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Choose a level (IGCSE, O Level or A Level) before applying this syllabus",
        )

    subject = await db.scalar(
        select(Subject).where(
            Subject.organization_id == user.organization_id,
            Subject.exam_board == draft.exam_board,
            Subject.code == draft.code,
        )
    )
    if subject is None:
        subject = Subject(
            organization_id=user.organization_id,
            exam_board=draft.exam_board,
            code=draft.code,
        )
        db.add(subject)
    subject.level = draft.level
    subject.name = draft.name
    subject.grade_scale = draft.grade_scale
    # The draft no longer carries grade boundaries (task 2.3): a syllabus document
    # publishes a specification, not a series' boundaries, so asking a model for
    # them was asking it to guess. Task 2.4 makes the tutor-entered table the only
    # source; until then a *new* subject still needs a working predicted grade, so
    # it is seeded with the scale's standard split. An existing subject is never
    # touched — a tutor who entered real boundaries must not lose them by
    # re-uploading the document.
    if not subject.grade_boundaries:
        subject.grade_boundaries = defaults_for_scale(draft.grade_scale)
    await db.flush()

    chapters = {
        c.code: c
        for c in (await db.scalars(select(Chapter).where(Chapter.subject_id == subject.id))).all()
    }
    existing = {
        t.code: t
        for t in (await db.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
    }

    async def upsert(node, chapter_id: int, parent_id: int | None) -> None:
        topic = existing.get(node.code)
        if topic is None:
            topic = Topic(subject_id=subject.id, code=node.code)
            db.add(topic)
            existing[node.code] = topic
        topic.title = node.title
        topic.chapter_id = chapter_id
        topic.parent_id = parent_id
        topic.weight = node.weight
        await db.flush()
        for child in node.children:
            await upsert(child, chapter_id, topic.id)

    for position, drafted in enumerate(draft.chapters, start=1):
        chapter = chapters.get(drafted.code)
        if chapter is None:
            chapter = Chapter(subject_id=subject.id, code=drafted.code)
            db.add(chapter)
        # Registered by code so a draft that repeats one — the codes are
        # tutor-editable free text — merges into that chapter, exactly as a
        # repeated topic code does, instead of a second INSERT tripping the
        # (subject_id, code) unique constraint with a 500.
        chapters[drafted.code] = chapter
        chapter.title = drafted.title
        # Teaching order comes from the draft's order, which the tutor can
        # rearrange during review — not from `code`, since a tutor may teach
        # chapter 4 before chapter 3.
        chapter.position = position
        await db.flush()
        for node in drafted.topics:
            await upsert(node, chapter.id, None)

    upload.status = SyllabusUploadStatus.applied
    upload.subject_id = subject.id
    await db.commit()
    return _detail(upload)
