"""Past papers: tutor uploads the paper once, students self-log their attempts.

A past paper rides the same pipeline as homework — extract questions, AI-mark
the student's pages, auto-finalize what's confident, queue the rest for the
tutor — because a student's attempt *is* a Submission (see models/homework.py).
That means the review queue, mark-override audit and remark requests all apply
here with no extra code.

Two rules specific to past papers:
- **The official mark scheme is required at upload.** Past-paper marks feed the
  Past Paper Performance factor and a predicted grade; they may not rest on the
  AI's own judgement.
- **The mark scheme is tutor-only.** Students can read the question booklet.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, StudentUser, TutorUser
from app.models import (
    Group,
    GroupMember,
    PastPaper,
    PastPaperAttempt,
    PastPaperQuestion,
    Subject,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.past_paper import (
    PastPaperAttemptOut,
    PastPaperDetail,
    PastPaperOut,
    PastPaperQuestionOut,
)
from app.services import storage
from app.workers.jobs import enqueue

router = APIRouter(prefix="/past-papers", tags=["past-papers"])

SETTLED = (SubmissionStatus.auto_finalized, SubmissionStatus.finalized)


async def _enrolled_scope(db, student_id: int) -> set[tuple[int, int]]:
    """The (organization_id, subject_id) pairs a student is actually taught in.

    Subjects are global — every organization shares the same five built-in
    syllabuses — so enrollment alone does not bound what a student may see.
    Scoping on the pair keeps one tutor's uploads inside that tutor's
    organization; matching on subject alone would show a student every past
    paper any tutor anywhere had uploaded for their subject.

    The pair comes from the groups the student is in rather than from
    `user.organization_id`, so a student who joined a second tutor's group with
    an invite (which does not move their organization) still sees that tutor's
    papers, and only that tutor's.
    """
    rows = (
        await db.execute(
            select(Group.organization_id, Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == student_id)
        )
    ).all()
    return {(org_id, subject_id) for org_id, subject_id in rows}


async def _visible_paper(db, user: User, past_paper_id: int) -> PastPaper:
    """A tutor sees their organization's papers; a student sees papers uploaded
    in an organization that teaches them, for a subject they're enrolled in."""
    paper = await db.get(PastPaper, past_paper_id)
    if paper is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")
    if user.role in (UserRole.tutor, UserRole.admin):
        if paper.organization_id != user.organization_id and user.role != UserRole.admin:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")
        return paper
    if user.role == UserRole.student:
        if (paper.organization_id, paper.subject_id) in await _enrolled_scope(db, user.id):
            return paper
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")


async def _out(db, paper: PastPaper, *, for_tutor: bool) -> PastPaperOut:
    count = (
        await db.scalar(
            select(func.count(PastPaperQuestion.id)).where(
                PastPaperQuestion.past_paper_id == paper.id
            )
        )
    ) or 0
    return PastPaperOut(
        id=paper.id,
        subject_id=paper.subject_id,
        session_label=paper.session_label,
        paper_number=paper.paper_number,
        total_marks=paper.total_marks,
        duration_minutes=paper.duration_minutes,
        booklet_name=paper.booklet_name,
        mark_scheme_name=paper.mark_scheme_name if for_tutor else None,
        extraction_error=paper.extraction_error if for_tutor else None,
        question_count=count,
    )


@router.post("", response_model=PastPaperOut, status_code=status.HTTP_201_CREATED)
async def upload_past_paper(
    db: DbSession,
    user: TutorUser,
    subject_id: Annotated[int, Form()],
    session_label: Annotated[str, Form(min_length=1, max_length=64)],
    paper_number: Annotated[str, Form(min_length=1, max_length=32)],
    booklet: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile, File()],
    total_marks: Annotated[int | None, Form()] = None,
    duration_minutes: Annotated[int | None, Form()] = None,
) -> PastPaperOut:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    # The mark scheme is a required part of the form, so FastAPI rejects a
    # missing file before we get here — this catches an empty upload.
    if not mark_scheme.filename:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A past paper needs its official mark scheme — marks from a full "
            "paper can't rest on the AI's judgement alone.",
        )

    booklet_path, booklet_name, booklet_mime = await storage.save_upload(booklet)
    ms_path, ms_name, ms_mime = await storage.save_upload(mark_scheme)
    paper = PastPaper(
        organization_id=user.organization_id,
        tutor_id=user.id,
        subject_id=subject.id,
        session_label=session_label,
        paper_number=paper_number,
        total_marks=total_marks,
        duration_minutes=duration_minutes,
        booklet_path=booklet_path,
        booklet_name=booklet_name,
        booklet_mime=booklet_mime,
        mark_scheme_path=ms_path,
        mark_scheme_name=ms_name,
        mark_scheme_mime=ms_mime,
    )
    db.add(paper)
    await db.flush()
    await enqueue(db, "extract_past_paper", {"past_paper_id": paper.id})
    await db.commit()
    return await _out(db, paper, for_tutor=True)


@router.get("", response_model=list[PastPaperOut])
async def list_past_papers(
    db: DbSession, user: CurrentUser, subject_id: int | None = None
) -> list[PastPaperOut]:
    query = select(PastPaper)
    if user.role in (UserRole.tutor, UserRole.admin):
        query = query.where(PastPaper.organization_id == user.organization_id)
        for_tutor = True
    elif user.role == UserRole.student:
        # One OR'd (organization, subject) pair per group the student is in.
        # Filtering the two columns independently would let a student in
        # org A + Chemistry see org B's Chemistry papers the moment they were
        # also in any org B group. `false()` keeps a student with no groups
        # seeing nothing rather than everything.
        pairs = [
            and_(PastPaper.organization_id == org_id, PastPaper.subject_id == subj_id)
            for org_id, subj_id in await _enrolled_scope(db, user.id)
        ]
        query = query.where(or_(*pairs) if pairs else false())
        for_tutor = False
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    if subject_id is not None:
        query = query.where(PastPaper.subject_id == subject_id)
    papers = (await db.scalars(query.order_by(PastPaper.id.desc()))).all()
    return [await _out(db, p, for_tutor=for_tutor) for p in papers]


@router.get("/{past_paper_id}", response_model=PastPaperDetail)
async def past_paper_detail(
    past_paper_id: int, db: DbSession, user: CurrentUser
) -> PastPaperDetail:
    paper = await _visible_paper(db, user, past_paper_id)
    for_tutor = user.role in (UserRole.tutor, UserRole.admin)
    base = await _out(db, paper, for_tutor=for_tutor)
    questions = (
        await db.scalars(
            select(PastPaperQuestion)
            .where(PastPaperQuestion.past_paper_id == paper.id)
            .order_by(PastPaperQuestion.position)
        )
    ).all()
    return PastPaperDetail(
        **base.model_dump(),
        questions=[
            PastPaperQuestionOut(
                id=q.id,
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                has_mark_scheme=q.has_mark_scheme,
            )
            for q in questions
        ],
    )


@router.get("/{past_paper_id}/booklet")
async def past_paper_booklet(
    past_paper_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    """The question paper — readable by enrolled students so they can sit it."""
    paper = await _visible_paper(db, user, past_paper_id)
    if paper.booklet_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No booklet uploaded")
    return FileResponse(
        storage.absolute_path(paper.booklet_path),
        media_type=paper.booklet_mime,
        filename=paper.booklet_name,
    )


@router.get("/{past_paper_id}/mark-scheme")
async def past_paper_mark_scheme(
    past_paper_id: int, db: DbSession, user: TutorUser
) -> FileResponse:
    """Tutor-only — handing this to a student would defeat the exercise."""
    paper = await _visible_paper(db, user, past_paper_id)
    if paper.mark_scheme_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mark scheme uploaded")
    return FileResponse(
        storage.absolute_path(paper.mark_scheme_path),
        media_type=paper.mark_scheme_mime,
        filename=paper.mark_scheme_name,
    )


async def _attempt_out(db, submission: Submission) -> PastPaperAttemptOut:
    paper = await db.get(PastPaper, submission.past_paper_id)
    subject = await db.get(Subject, paper.subject_id)
    attempt = await db.scalar(
        select(PastPaperAttempt).where(
            PastPaperAttempt.past_paper_id == paper.id,
            PastPaperAttempt.student_id == submission.student_id,
        )
    )
    return PastPaperAttemptOut(
        submission_id=submission.id,
        past_paper_id=paper.id,
        session_label=paper.session_label,
        paper_number=paper.paper_number,
        subject_name=subject.name if subject else "",
        status="marked" if submission.status in SETTLED else "being_marked",
        timed=submission.timed,
        time_taken_minutes=submission.time_taken_minutes,
        attempted_at=submission.attempted_at,
        submitted_at=submission.submitted_at,
        raw_marks=attempt.raw_marks if attempt else None,
        max_marks=attempt.max_marks if attempt else paper.total_marks,
    )


@router.post(
    "/{past_paper_id}/attempts",
    response_model=PastPaperAttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def log_attempt(
    past_paper_id: int,
    db: DbSession,
    user: StudentUser,
    files: Annotated[list[UploadFile], File()],
    attempted_at: Annotated[date, Form()],
    timed: Annotated[bool, Form()] = False,
    time_taken_minutes: Annotated[int | None, Form()] = None,
) -> PastPaperAttemptOut:
    """A student logging a paper they sat. Creates a Submission, so marking,
    review and evidence all work exactly as they do for homework."""
    paper = await _visible_paper(db, user, past_paper_id)
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload at least one file")

    submission = await db.scalar(
        select(Submission)
        .where(Submission.past_paper_id == paper.id, Submission.student_id == user.id)
        .options(selectinload(Submission.files), selectinload(Submission.marks))
    )
    if submission is not None and submission.status in SETTLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You've already logged this paper and it's been marked"
        )
    if submission is None:
        submission = Submission(past_paper_id=paper.id, student_id=user.id)
        db.add(submission)
        await db.flush()
    else:
        # Re-logging before it settled: replace the pages and re-mark.
        for f in list(submission.files):
            await db.delete(f)
        for m in list(submission.marks):
            await db.delete(m)
        submission.status = SubmissionStatus.submitted
        submission.ai_error = None
        await db.flush()

    submission.timed = timed
    submission.time_taken_minutes = time_taken_minutes
    submission.attempted_at = attempted_at
    for position, upload in enumerate(files):
        path, name, mime = await storage.save_upload(upload)
        db.add(
            SubmissionFile(
                submission_id=submission.id, position=position, path=path, name=name, mime=mime
            )
        )
    await enqueue(db, "mark_submission", {"submission_id": submission.id})
    await db.commit()
    return await _attempt_out(db, submission)


@router.get("/{past_paper_id}/my-attempt", response_model=PastPaperAttemptOut | None)
async def my_attempt(
    past_paper_id: int, db: DbSession, user: StudentUser
) -> PastPaperAttemptOut | None:
    paper = await _visible_paper(db, user, past_paper_id)
    submission = await db.scalar(
        select(Submission).where(
            Submission.past_paper_id == paper.id, Submission.student_id == user.id
        )
    )
    return await _attempt_out(db, submission) if submission else None
