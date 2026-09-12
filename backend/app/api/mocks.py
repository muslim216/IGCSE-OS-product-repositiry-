"""Mocks: the tutor sets a paper, the group sits it, the AI marks it.

A mock rides the same pipeline as homework and past papers — extract questions,
AI-mark the student's answers, auto-finalize what is scheme-backed and
confident, queue the rest for the tutor — because a student's attempt *is* a
`Submission` (`PROD-9`, `ADR-0004`, E6). The review queue, the mark-override
audit and remark requests therefore all apply here with no extra code.

What differs from a past paper:
- **The mark scheme is optional.** A tutor's own paper often has no official
  scheme. Without one nothing auto-finalizes — every mark waits in the review
  queue, which is `AI-11` working as intended rather than a degraded mode.
- **A mock is set to one group.** A past paper is visible to everyone enrolled
  in the subject; a mock is an exam a particular class sits.
- **The mark scheme is tutor-only**, same as a past paper.
"""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CurrentUser,
    DbSession,
    StudentUser,
    TutorUser,
    form_typed_answer,
    owned_subject,
)
from app.api.file_responses import FILE_RESPONSES, signed_or_proxied_file
from app.models import (
    SETTLED_STATUSES,
    AssessmentType,
    Group,
    GroupMember,
    Mock,
    MockQuestion,
    MockStatus,
    QuestionMark,
    Subject,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.mock import MockDetail, MockOut, MockQuestionOut, MockSubmissionOut
from app.services import storage
from app.services.injection_scan import scan_typed_answer
from app.workers.jobs import enqueue

router = APIRouter(prefix="/mocks", tags=["mocks"])


async def _visible_mock(db, user: User, mock_id: int) -> Mock:
    """A tutor sees the mocks they set; a student sees a mock set to a group
    they are actually in.

    Group membership, not `(organization, subject)`: a mock is one class's exam,
    so subject-level scoping would show it to every student the tutor teaches
    that subject to, including ones who never sat it. `SEC-8`'s reason for
    scoping past papers on the pair applies here a step further in.
    """
    mock = await db.get(Mock, mock_id)
    if mock is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock not found")
    if user.role == UserRole.admin:
        return mock
    if user.role == UserRole.tutor:
        # 404, not 403: integer keys are enumerable, and "exists but not yours"
        # is itself information (`API-7`, `SEC-9`).
        if mock.tutor_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock not found")
        return mock
    if user.role == UserRole.student and mock.group_id is not None:
        member = await db.scalar(
            select(GroupMember.id).where(
                GroupMember.group_id == mock.group_id, GroupMember.student_id == user.id
            )
        )
        if member is not None:
            return mock
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock not found")


async def _question_counts(db, mock_ids: Sequence[int]) -> dict[int, int]:
    """Question counts for a page of mocks in one round trip, not one per row."""
    if not mock_ids:
        return {}
    rows = await db.execute(
        select(MockQuestion.mock_id, func.count(MockQuestion.id))
        .where(MockQuestion.mock_id.in_(mock_ids))
        .group_by(MockQuestion.mock_id)
    )
    return dict(rows.all())


def _out(mock: Mock, question_count: int, *, for_tutor: bool) -> MockOut:
    return MockOut(
        id=mock.id,
        subject_id=mock.subject_id,
        group_id=mock.group_id,
        title=mock.title,
        type=mock.type,
        sat_on=mock.sat_on,
        status=mock.status,
        total_marks=mock.total_marks,
        duration_minutes=mock.duration_minutes,
        paper_name=mock.paper_name,
        mark_scheme_name=mock.mark_scheme_name if for_tutor else None,
        extraction_error=mock.extraction_error if for_tutor else None,
        question_count=question_count,
    )


async def _owned_group(db, group_id: int, user: User) -> Group:
    group = await db.get(Group, group_id)
    if group is None or group.tutor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return group


@router.post("", response_model=MockOut, status_code=status.HTTP_201_CREATED)
async def create_mock(
    db: DbSession,
    user: TutorUser,
    subject_id: Annotated[int, Form()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    paper: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
    group_id: Annotated[int | None, Form()] = None,
    type: Annotated[AssessmentType, Form()] = AssessmentType.mock,
    sat_on: Annotated[date | None, Form()] = None,
    total_marks: Annotated[int | None, Form()] = None,
    duration_minutes: Annotated[int | None, Form()] = None,
) -> MockOut:
    subject = await owned_subject(db, subject_id, user)
    if group_id is not None:
        group = await _owned_group(db, group_id, user)
        if group.subject_id != subject.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That class doesn't study this subject",
            )
    if not paper.filename:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A mock needs its question paper — there is nothing to extract or mark without it.",
        )

    paper_path, paper_name, paper_mime = await storage.save_upload(
        paper, organization_id=user.organization_id
    )
    ms_path = ms_name = ms_mime = None
    if mark_scheme is not None and mark_scheme.filename:
        ms_path, ms_name, ms_mime = await storage.save_upload(
            mark_scheme, organization_id=user.organization_id
        )
    mock = Mock(
        organization_id=user.organization_id,
        tutor_id=user.id,
        subject_id=subject.id,
        group_id=group_id,
        title=title,
        type=type,
        sat_on=sat_on,
        total_marks=total_marks,
        duration_minutes=duration_minutes,
        paper_path=paper_path,
        paper_name=paper_name,
        paper_mime=paper_mime,
        mark_scheme_path=ms_path,
        mark_scheme_name=ms_name,
        mark_scheme_mime=ms_mime,
    )
    db.add(mock)
    await db.flush()
    await enqueue(db, "extract_mock", {"mock_id": mock.id})
    await db.commit()
    return _out(mock, 0, for_tutor=True)


@router.get("", response_model=list[MockOut])
async def list_mocks(
    db: DbSession, user: TutorUser, subject_id: int | None = None
) -> list[MockOut]:
    query = select(Mock).where(Mock.tutor_id == user.id)
    if subject_id is not None:
        query = query.where(Mock.subject_id == subject_id)
    mocks = (await db.scalars(query.order_by(Mock.id.desc()))).all()
    counts = await _question_counts(db, [m.id for m in mocks])
    return [_out(m, counts.get(m.id, 0), for_tutor=True) for m in mocks]


@router.get("/mine", response_model=list[MockOut])
async def my_mocks(db: DbSession, user: StudentUser) -> list[MockOut]:
    """Every published mock set to a group this student is in."""
    mocks = (
        await db.scalars(
            select(Mock)
            .join(GroupMember, GroupMember.group_id == Mock.group_id)
            .where(
                GroupMember.student_id == user.id,
                Mock.status == MockStatus.published,
            )
            .order_by(Mock.id.desc())
        )
    ).all()
    counts = await _question_counts(db, [m.id for m in mocks])
    return [_out(m, counts.get(m.id, 0), for_tutor=False) for m in mocks]


@router.get("/{mock_id}", response_model=MockDetail)
async def get_mock(mock_id: int, db: DbSession, user: CurrentUser) -> MockDetail:
    mock = await _visible_mock(db, user, mock_id)
    for_tutor = user.role in (UserRole.tutor, UserRole.admin)
    questions = (
        await db.scalars(
            select(MockQuestion)
            .where(MockQuestion.mock_id == mock.id)
            .order_by(MockQuestion.position)
        )
    ).all()
    base = _out(mock, len(questions), for_tutor=for_tutor)
    return MockDetail(
        **base.model_dump(),
        questions=[
            MockQuestionOut(
                id=q.id,
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                has_mark_scheme=q.has_mark_scheme,
            )
            for q in questions
        ],
    )


@router.get("/{mock_id}/paper", response_class=Response, responses=FILE_RESPONSES)
async def mock_paper(mock_id: int, db: DbSession, user: CurrentUser) -> Response:
    """The question paper — readable by the students sitting it."""
    mock = await _visible_mock(db, user, mock_id)
    if mock.status != MockStatus.published and user.role not in (UserRole.tutor, UserRole.admin):
        # `sit_mock` already refuses an unpublished mock; without the same gate
        # here a student in the group could pull the paper while it was still
        # extracting, or after the extraction failed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock not found")
    return await signed_or_proxied_file(
        mock.paper_path, mime=mock.paper_mime, filename=mock.paper_name
    )


@router.get("/{mock_id}/mark-scheme", response_class=Response, responses=FILE_RESPONSES)
async def mock_mark_scheme(mock_id: int, db: DbSession, user: TutorUser) -> Response:
    """Tutor-only — handing this to a student would defeat the exercise."""
    mock = await _visible_mock(db, user, mock_id)
    if mock.mark_scheme_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mark scheme uploaded")
    return await signed_or_proxied_file(
        mock.mark_scheme_path,
        mime=mock.mark_scheme_mime or "application/octet-stream",
        filename=mock.mark_scheme_name or "mark-scheme",
    )


async def _submission_out(db, mock: Mock, submission: Submission) -> MockSubmissionOut:
    subject = await db.get(Subject, mock.subject_id)
    raw = mx = None
    if submission.status in SETTLED_STATUSES:
        # Totalled over the questions that actually carry a final mark, not over
        # the whole paper: a mark the tutor has not ruled on yet is absent, and
        # scoring it out of the full paper would render missing data as a low
        # score (`PROD-2`). One query, so the tutor's list is not N+1.
        row = (
            await db.execute(
                select(
                    func.sum(QuestionMark.final_marks),
                    func.sum(MockQuestion.max_marks),
                )
                .select_from(QuestionMark)
                .join(MockQuestion, MockQuestion.id == QuestionMark.mock_question_id)
                .where(
                    QuestionMark.submission_id == submission.id,
                    QuestionMark.final_marks.is_not(None),
                )
            )
        ).one()
        raw, mx = row[0], row[1]
    return MockSubmissionOut(
        submission_id=submission.id,
        mock_id=mock.id,
        title=mock.title,
        subject_name=subject.name if subject else "",
        status=submission.status.value,
        submitted_at=submission.submitted_at,
        raw_marks=raw,
        max_marks=mx,
    )


@router.post(
    "/{mock_id}/submissions",
    response_model=MockSubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def sit_mock(
    mock_id: int,
    db: DbSession,
    user: StudentUser,
    files: Annotated[list[UploadFile] | None, File()] = None,
    typed_answer: Annotated[str | None, Form()] = None,
) -> MockSubmissionOut:
    mock = await _visible_mock(db, user, mock_id)
    if mock.status != MockStatus.published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock not found")
    # Either channel, or both — the same rule homework follows since AV-73.
    typed = form_typed_answer(typed_answer)
    if not files and typed is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Add your answers — upload a photo or type them in",
        )

    submission = await db.scalar(
        select(Submission)
        .where(Submission.mock_id == mock.id, Submission.student_id == user.id)
        .options(selectinload(Submission.files), selectinload(Submission.marks))
    )
    if submission is not None and submission.status in SETTLED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This mock has already been marked")
    if submission is None:
        submission = Submission(mock_id=mock.id, student_id=user.id)
        db.add(submission)
        await db.flush()
    else:
        for f in submission.files:
            await db.delete(f)
        for m in submission.marks:
            await db.delete(m)
        submission.status = SubmissionStatus.submitted
        submission.ai_error = None
        # The review queue orders by this, so a resit that kept its first
        # attempt's timestamp would sort as though it never happened.
        submission.submitted_at = datetime.now(timezone.utc)
        await db.flush()

    submission.typed_answer = typed
    # The deterministic scan (AV-93), run at submission so the verdict is stored
    # before anything is queued and no marking run can start unscanned.
    submission.typed_flag_reason = scan_typed_answer(typed).reason

    for position, upload in enumerate(files or []):
        path, name, mime = await storage.save_upload(upload, organization_id=user.organization_id)
        db.add(
            SubmissionFile(
                submission_id=submission.id,
                path=path,
                name=name,
                mime=mime,
                position=position,
            )
        )
    await enqueue(db, "mark_submission", {"submission_id": submission.id})
    await db.commit()
    await db.refresh(submission)
    return await _submission_out(db, mock, submission)


@router.get("/{mock_id}/my-submission", response_model=MockSubmissionOut | None)
async def my_mock_submission(
    mock_id: int, db: DbSession, user: StudentUser
) -> MockSubmissionOut | None:
    mock = await _visible_mock(db, user, mock_id)
    submission = await db.scalar(
        select(Submission).where(Submission.mock_id == mock.id, Submission.student_id == user.id)
    )
    if submission is None:
        return None
    return await _submission_out(db, mock, submission)
