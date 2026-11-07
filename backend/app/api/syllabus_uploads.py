from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor
from app.models import (
    Chapter,
    Job,
    JobStatus,
    Organization,
    Subject,
    SyllabusUpload,
    SyllabusUploadStatus,
    Topic,
    User,
    UserRole,
)
from app.schemas.syllabus import (
    GRADE_SCALE_MAX,
    SyllabusDraft,
    SyllabusUploadDetail,
    SyllabusUploadOut,
)
from app.services import storage
from app.services.plan_reflow import enqueue_reflow_for_subject
from app.services.syllabus_extraction import DraftNotValid, SyllabusDraftChecked, check_draft
from app.workers.jobs import enqueue

router = APIRouter(prefix="/syllabus-uploads", tags=["syllabus"])

SYLLABUS_BEING_READ_MESSAGE = "A syllabus is already being read. Try again when it finishes."
CHOOSE_GRADE_SCALE_MESSAGE = "Choose the grade scale before applying"
EXTRACT_SYLLABUS_JOB = "extract_syllabus"


async def _refuse_while_a_read_is_running(db: AsyncSession, organization_id: int) -> None:
    """409 while a read job for any upload in this organization is still live.

    A read may run for 45 minutes on the model's whole answer length (T-028),
    so a workspace reads one syllabus at a time.

    Live means an `extract_syllabus` job that is `pending` or `running`, not an
    upload whose status says `extracting`. The two differ both ways. An upload
    whose job is over but whose give-up step never ran stays `extracting` for
    good, and blocking on that would lock the workspace out with nothing the
    tutor could do. And a read that failed in a way the worker retries shows
    `extraction_failed` while its job waits out the backoff; a retry then would
    queue a second job for the same upload beside it.

    The organization row is locked first and held until the caller commits, so
    two requests arriving together cannot both find nothing live and both start
    a read: the second waits here for the first to commit, then sees its job.
    FOR NO KEY UPDATE rather than FOR UPDATE, which is enough to make two of
    these wait for each other but does not hold up inserts into tables that
    point at the organization. That holds on Postgres; SQLite drops the clause,
    which is why the test that sends two requests at once runs only on Postgres.

    Called before anything is stored or queued, so a refused request costs no
    upload allowance and leaves no file behind. The organization comes from the
    signed-in user (`SEC-7`); an upload row has none of its own, so the check
    reaches it through the uploading tutor, as `list_syllabus_uploads` does."""
    await db.execute(
        select(Organization.id)
        .where(Organization.id == organization_id)
        .with_for_update(key_share=True)
    )
    # Payloads are read here, not compared in SQL: Postgres has no equality
    # operator for `json`, and the live read jobs are a handful of rows.
    payloads = await db.scalars(
        select(Job.payload).where(
            Job.type == EXTRACT_SYLLABUS_JOB,
            Job.status.in_((JobStatus.pending, JobStatus.running)),
        )
    )
    live_ids = {
        upload_id
        for payload in payloads
        if isinstance(payload, dict)
        and isinstance(upload_id := payload.get("syllabus_upload_id"), int)
    }
    if not live_ids:
        return
    running = await db.scalar(
        select(SyllabusUpload.id)
        .join(User, User.id == SyllabusUpload.tutor_id)
        .where(User.organization_id == organization_id, SyllabusUpload.id.in_(live_ids))
        .limit(1)
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, SYLLABUS_BEING_READ_MESSAGE)


async def _owned_upload(db, user: User, upload_id: int) -> SyllabusUpload:
    assert_tutor(user)
    upload = await db.get(SyllabusUpload, upload_id)
    if upload is None or (upload.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus upload not found")
    if upload.tutor_id != user.id:
        # An admin reaching a colleague's upload. The row carries no
        # organization of its own, so the tenant is the uploading tutor's: wider
        # reach inside the organization, not across organizations (`SEC-7`).
        owner = await db.get(User, upload.tutor_id)
        if owner is None or owner.organization_id != user.organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus upload not found")
    return upload


def _checked(draft: object) -> SyllabusDraftChecked:
    """The draft held to its columns, or a 422 in plain words naming the field
    (T-033). Without this a value too long for its column reached the database
    and came back as a 500."""
    try:
        return check_draft(draft)
    except DraftNotValid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


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
    # The lock taken here is held through the save below until the commit. A
    # save to the local disk is quick; the cost is that this workspace's next
    # syllabus request waits for it, which is the point. Look at this again
    # when STORAGE_BACKEND=s3: the save becomes a network call, and the lock
    # (and a pooled connection) is then held for as long as it takes.
    await _refuse_while_a_read_is_running(db, user.organization_id)
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
    await enqueue(db, EXTRACT_SYLLABUS_JOB, {"syllabus_upload_id": upload.id})
    await db.commit()
    return _detail(upload)


@router.get("", response_model=list[SyllabusUploadOut])
async def list_syllabus_uploads(db: DbSession, user: TutorUser) -> list[SyllabusUploadOut]:
    query = select(SyllabusUpload).order_by(SyllabusUpload.created_at.desc())
    if user.role != UserRole.admin:
        query = query.where(SyllabusUpload.tutor_id == user.id)
    else:
        # Every upload in the admin's own organization, never another's
        # (`SEC-7`). The tenant is the uploading tutor's — the row has none.
        query = query.join(User, User.id == SyllabusUpload.tutor_id).where(
            User.organization_id == user.organization_id
        )
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
    # The body is declared as the lenient `SyllabusDraft`, the shape the review
    # page reads and sends back, and is held to the strict one here. Declaring
    # the strict model instead would rename the draft's generated types.
    upload.draft = _checked(body.model_dump()).model_dump()
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
    # The tenant is the uploading tutor's, which `_owned_upload` has already
    # held to the caller's own organization.
    await _refuse_while_a_read_is_running(db, user.organization_id)
    upload.status = SyllabusUploadStatus.extracting
    upload.error = None
    await enqueue(db, EXTRACT_SYLLABUS_JOB, {"syllabus_upload_id": upload.id})
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
    # Re-checked here, not trusted from the PUT: a draft stored by the AI, or
    # before T-033, never went through it.
    draft = _checked(upload.draft)

    if draft.level is None:
        # AV-7: nothing may assume an IGCSE-shaped world, and PROD-2 forbids
        # inventing a value to fill a gap. The tutor reviews the draft before
        # applying it, so asking is cheap; guessing is a wrong label on every
        # screen that shows the subject.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Choose a level (IGCSE, O Level or A Level) before applying this syllabus",
        )
    if not draft.grade_scale or len(draft.grade_scale) > GRADE_SCALE_MAX:
        # Only an empty scale or one too long to store. An unknown one that
        # fits applies as it always has, with no default boundaries; refusing
        # it would block every A*-G subject.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, CHOOSE_GRADE_SCALE_MESSAGE)

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
    # Nothing here writes grade boundaries. The draft stopped carrying them in
    # 2.3 (a syllabus document publishes a specification, not a series'
    # boundaries), and 2.4 made the tutor-entered `GradeBoundary` table the only
    # source: the editor offers the published split for this scale pre-filled and
    # it counts once the tutor saves it. Seeding it here instead would make a
    # guess indistinguishable from their own figures (AV-11, PROD-2, PROD-8).
    await db.flush()

    chapters = {
        c.code: c
        for c in (await db.scalars(select(Chapter).where(Chapter.subject_id == subject.id))).all()
    }
    # What the plans' schedules depend on: which chapters exist, their titles and
    # their teaching order. A topic-only edit changes none of it.
    chapters_before = {code: (c.title, c.position) for code, c in chapters.items()}
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

    # A later draft may omit a chapter an earlier one created, and nothing here
    # deletes it. Left alone it would keep a position the new draft has just
    # reassigned, and two chapters sharing a position make `order_by(position)`
    # arbitrary (Gitar). They sort after everything the tutor just approved, in
    # their previous relative order.
    drafted_codes = {c.code for c in draft.chapters}
    stale = sorted(
        (c for code, c in chapters.items() if code not in drafted_codes),
        key=lambda c: (c.position, c.code),
    )
    for offset, chapter in enumerate(stale, start=len(draft.chapters) + 1):
        chapter.position = offset

    upload.status = SyllabusUploadStatus.applied
    upload.subject_id = subject.id
    # Chapters are only ever added, renamed and re-ordered here; nothing deletes
    # one, so `plan_slots.chapter_id ON DELETE RESTRICT` cannot be hit from this
    # path. A chapter the draft omitted survives (sorted last) and keeps its slots.
    # Any future path that deletes a chapter must clear its slots first (task 6.8).
    # Reflow is a job, never request work (`BE-13`). Enqueued before the single
    # commit so the new chapters and the job rows become visible together: the
    # worker can never claim a reflow that predates the chapters it must read, and
    # a failed enqueue rolls the whole apply back rather than leaving a half state.
    # Only when the chapter list actually changed: re-applying the same syllabus
    # or a topic-only edit leaves every plan as it is.
    chapters_after = {code: (c.title, c.position) for code, c in chapters.items()}
    if chapters_after != chapters_before:
        await enqueue_reflow_for_subject(db, subject.id)
    await db.commit()
    return _detail(upload)
