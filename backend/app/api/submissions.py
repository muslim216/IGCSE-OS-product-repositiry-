from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Group,
    GroupMember,
    QuestionMark,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.homework import (
    MarkRow,
    MarkUpdate,
    StudentAssignment,
    StudentMarkRow,
    StudentSubmissionView,
    SubmissionDetail,
    SubmissionFileOut,
    SubmissionSummary,
)
from app.services import storage
from app.workers.jobs import enqueue

router = APIRouter(tags=["submissions"])


async def _tutor_submission(db, user: User, submission_id: int) -> Submission:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    submission = await db.get(
        Submission, submission_id, options=[selectinload(Submission.files)]
    )
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    assignment = await db.get(Assignment, submission.assignment_id)
    group = await db.get(Group, assignment.group_id)
    if group.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    return submission


@router.post(
    "/assignments/{assignment_id}/submissions",
    response_model=StudentSubmissionView,
    status_code=status.HTTP_201_CREATED,
)
async def submit_work(
    assignment_id: int,
    db: DbSession,
    user: CurrentUser,
    files: Annotated[list[UploadFile], File()],
) -> StudentSubmissionView:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None or assignment.status != AssignmentStatus.published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    member = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == assignment.group_id, GroupMember.student_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload at least one file")

    submission = await db.scalar(
        select(Submission)
        .where(Submission.assignment_id == assignment_id, Submission.student_id == user.id)
        .options(selectinload(Submission.files), selectinload(Submission.marks))
    )
    if submission is not None and submission.status == SubmissionStatus.finalized:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This homework has already been marked and finalized"
        )
    if submission is None:
        submission = Submission(assignment_id=assignment_id, student_id=user.id)
        db.add(submission)
        await db.flush()
    else:
        # Resubmission before finalize: replace the files and restart marking.
        for f in submission.files:
            await db.delete(f)
        for m in submission.marks:
            await db.delete(m)
        submission.status = SubmissionStatus.submitted
        submission.ai_error = None
        submission.submitted_at = datetime.now(timezone.utc)
        await db.flush()

    for position, upload in enumerate(files):
        path, name, mime = await storage.save_upload(upload)
        db.add(
            SubmissionFile(
                submission_id=submission.id, position=position, path=path, name=name, mime=mime
            )
        )
    await enqueue(db, "mark_submission", {"submission_id": submission.id})
    await db.commit()
    return await _student_view(db, assignment, submission)


async def _student_view(db, assignment: Assignment, submission: Submission | None) -> StudentSubmissionView:
    total_max = (
        await db.scalar(
            select(func.coalesce(func.sum(AssignmentQuestion.max_marks), 0)).where(
                AssignmentQuestion.assignment_id == assignment.id
            )
        )
    ) or 0
    if submission is None:
        return StudentSubmissionView(
            status="not_submitted",
            submitted_at=None,
            finalized_at=None,
            total=None,
            total_max=total_max,
            marks=[],
        )
    marks: list[StudentMarkRow] = []
    total: int | None = None
    if submission.status == SubmissionStatus.finalized:
        rows = (
            await db.execute(
                select(QuestionMark, AssignmentQuestion)
                .join(AssignmentQuestion, AssignmentQuestion.id == QuestionMark.question_id)
                .where(QuestionMark.submission_id == submission.id)
                .order_by(AssignmentQuestion.position)
            )
        ).all()
        marks = [
            StudentMarkRow(
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                final_marks=m.final_marks,
                final_feedback=m.final_feedback,
            )
            for m, q in rows
        ]
        total = sum(m.final_marks or 0 for m, _ in rows)
    # Students see only lifecycle status, never AI drafts.
    public_status = {
        SubmissionStatus.submitted: "submitted",
        SubmissionStatus.marking: "being_marked",
        SubmissionStatus.ai_marked: "being_marked",
        SubmissionStatus.ai_failed: "being_marked",
        SubmissionStatus.finalized: "marked",
    }[submission.status]
    return StudentSubmissionView(
        status=public_status,
        submitted_at=submission.submitted_at,
        finalized_at=submission.finalized_at,
        total=total,
        total_max=total_max,
        marks=marks,
    )


@router.get("/me/assignments", response_model=list[StudentAssignment])
async def my_assignments(db: DbSession, user: CurrentUser) -> list[StudentAssignment]:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    rows = (
        await db.execute(
            select(Assignment, Group)
            .join(Group, Group.id == Assignment.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(
                GroupMember.student_id == user.id,
                Assignment.status.in_([AssignmentStatus.published, AssignmentStatus.closed]),
            )
            .options(selectinload(Group.subject))
            .order_by(Assignment.due_at.is_(None), Assignment.due_at)
        )
    ).all()
    out: list[StudentAssignment] = []
    for assignment, group in rows:
        stats = (
            await db.execute(
                select(
                    func.count(AssignmentQuestion.id),
                    func.coalesce(func.sum(AssignmentQuestion.max_marks), 0),
                ).where(AssignmentQuestion.assignment_id == assignment.id)
            )
        ).one()
        submission = await db.scalar(
            select(Submission).where(
                Submission.assignment_id == assignment.id, Submission.student_id == user.id
            )
        )
        view = await _student_view(db, assignment, submission)
        out.append(
            StudentAssignment(
                id=assignment.id,
                title=assignment.title,
                instructions=assignment.instructions,
                due_at=assignment.due_at,
                subject_name=group.subject.name,
                group_name=group.name,
                question_count=stats[0],
                total_marks=stats[1],
                submission_status=view.status,
                my_total=view.total,
            )
        )
    return out


@router.get("/assignments/{assignment_id}/my-submission", response_model=StudentSubmissionView)
async def my_submission(assignment_id: int, db: DbSession, user: CurrentUser) -> StudentSubmissionView:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    member = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == assignment.group_id, GroupMember.student_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    submission = await db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment_id, Submission.student_id == user.id
        )
    )
    return await _student_view(db, assignment, submission)


@router.get("/assignments/{assignment_id}/submissions", response_model=list[SubmissionSummary])
async def list_submissions(assignment_id: int, db: DbSession, user: CurrentUser) -> list[SubmissionSummary]:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    group = await db.get(Group, assignment.group_id)
    if group.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    total_max = (
        await db.scalar(
            select(func.coalesce(func.sum(AssignmentQuestion.max_marks), 0)).where(
                AssignmentQuestion.assignment_id == assignment.id
            )
        )
    ) or 0
    rows = (
        await db.execute(
            select(Submission, User)
            .join(User, User.id == Submission.student_id)
            .where(Submission.assignment_id == assignment_id)
            .order_by(User.name)
        )
    ).all()
    out = []
    for submission, student in rows:
        total_final = None
        if submission.status == SubmissionStatus.finalized:
            total_final = (
                await db.scalar(
                    select(func.coalesce(func.sum(QuestionMark.final_marks), 0)).where(
                        QuestionMark.submission_id == submission.id
                    )
                )
            ) or 0
        out.append(
            SubmissionSummary(
                id=submission.id,
                student_id=student.id,
                student_name=student.name,
                status=submission.status.value,
                submitted_at=submission.submitted_at,
                total_final=total_final,
                total_max=total_max,
            )
        )
    return out


async def _mark_rows(db, submission: Submission) -> list[MarkRow]:
    rows = (
        await db.execute(
            select(AssignmentQuestion, QuestionMark)
            .outerjoin(
                QuestionMark,
                (QuestionMark.question_id == AssignmentQuestion.id)
                & (QuestionMark.submission_id == submission.id),
            )
            .where(AssignmentQuestion.assignment_id == submission.assignment_id)
            .order_by(AssignmentQuestion.position)
        )
    ).all()
    return [
        MarkRow(
            question_id=q.id,
            number=q.number,
            text_summary=q.text_summary,
            max_marks=q.max_marks,
            has_mark_scheme=q.has_mark_scheme,
            ai_transcription=m.ai_transcription if m else None,
            ai_marks=m.ai_marks if m else None,
            ai_feedback=m.ai_feedback if m else None,
            ai_confidence=m.ai_confidence.value if m and m.ai_confidence else None,
            final_marks=m.final_marks if m else None,
            final_feedback=m.final_feedback if m else None,
            overridden=m.overridden if m else False,
        )
        for q, m in rows
    ]


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def submission_detail(submission_id: int, db: DbSession, user: CurrentUser) -> SubmissionDetail:
    submission = await _tutor_submission(db, user, submission_id)
    assignment = await db.get(Assignment, submission.assignment_id)
    student = await db.get(User, submission.student_id)
    return SubmissionDetail(
        id=submission.id,
        assignment_id=assignment.id,
        assignment_title=assignment.title,
        student_id=student.id,
        student_name=student.name,
        status=submission.status.value,
        ai_error=submission.ai_error,
        submitted_at=submission.submitted_at,
        files=[SubmissionFileOut.model_validate(f) for f in submission.files],
        marks=await _mark_rows(db, submission),
    )


@router.get("/submissions/{submission_id}/files/{file_id}")
async def submission_file(
    submission_id: int, file_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    submission = await db.get(Submission, submission_id, options=[selectinload(Submission.files)])
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if user.id != submission.student_id:
        assignment = await db.get(Assignment, submission.assignment_id)
        group = await db.get(Group, assignment.group_id)
        if group.tutor_id != user.id and user.role != UserRole.admin:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    file = next((f for f in submission.files if f.id == file_id), None)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(storage.absolute_path(file.path), media_type=file.mime, filename=file.name)


@router.put("/submissions/{submission_id}/marks", response_model=SubmissionDetail)
async def save_marks(
    submission_id: int, body: list[MarkUpdate], db: DbSession, user: CurrentUser
) -> SubmissionDetail:
    submission = await _tutor_submission(db, user, submission_id)
    if submission.status == SubmissionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "This submission is already finalized")
    questions = {
        q.id: q
        for q in (
            await db.scalars(
                select(AssignmentQuestion).where(
                    AssignmentQuestion.assignment_id == submission.assignment_id
                )
            )
        ).all()
    }
    existing = {
        m.question_id: m
        for m in (
            await db.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission.id)
            )
        ).all()
    }
    for update in body:
        question = questions.get(update.question_id)
        if question is None:
            continue
        mark = existing.get(update.question_id)
        if mark is None:
            mark = QuestionMark(submission_id=submission.id, question_id=question.id)
            db.add(mark)
            existing[question.id] = mark
        if update.final_marks is not None and update.final_marks > question.max_marks:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Q{question.number}: marks cannot exceed {question.max_marks}",
            )
        mark.final_marks = update.final_marks
        mark.final_feedback = update.final_feedback
        mark.overridden = mark.ai_marks is not None and update.final_marks != mark.ai_marks
    await db.commit()
    return await submission_detail(submission_id, db, user)


@router.post("/submissions/{submission_id}/finalize", response_model=SubmissionDetail)
async def finalize_submission(submission_id: int, db: DbSession, user: CurrentUser) -> SubmissionDetail:
    submission = await _tutor_submission(db, user, submission_id)
    if submission.status == SubmissionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "This submission is already finalized")
    marks = await _mark_rows(db, submission)
    missing = [m.number for m in marks if m.final_marks is None]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Set final marks for every question first (missing: {', '.join(missing)})",
        )
    submission.status = SubmissionStatus.finalized
    submission.finalized_at = datetime.now(timezone.utc)
    submission.finalized_by_id = user.id
    await db.commit()
    return await submission_detail(submission_id, db, user)
