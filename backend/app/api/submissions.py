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
    MarkOverrideAudit,
    PastPaper,
    PastPaperQuestion,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.homework import (
    MarkHistoryEntry,
    MarkRow,
    MarkUpdate,
    RemarkRequestCreate,
    RemarkRequestOut,
    ReviewQueueItem,
    StudentAssignment,
    StudentMarkRow,
    StudentSubmissionView,
    SubmissionDetail,
    SubmissionFileOut,
    SubmissionSummary,
)
from app.services import storage
from app.services.marking import record_marks_as_evidence
from app.workers.jobs import enqueue

router = APIRouter(tags=["submissions"])

# Once a submission reaches one of these, its marks count and it is closed to
# resubmission. auto_finalized got there without a tutor; finalized had one.
SETTLED_STATUSES = (SubmissionStatus.auto_finalized, SubmissionStatus.finalized)


async def _tutor_submission(db, user: User, submission_id: int) -> Submission:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    submission = await db.get(
        Submission, submission_id, options=[selectinload(Submission.files)]
    )
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    if submission.past_paper_id is not None:
        # Past papers belong to the organization, not to one tutor's group.
        paper = await db.get(PastPaper, submission.past_paper_id)
        owned = paper is not None and paper.organization_id == user.organization_id
    else:
        assignment = await db.get(Assignment, submission.assignment_id)
        group = await db.get(Group, assignment.group_id)
        owned = group.tutor_id == user.id
    if not owned and user.role != UserRole.admin:
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
    if submission is not None and submission.status in SETTLED_STATUSES:
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
            submission_id=None,
            status="not_submitted",
            submitted_at=None,
            finalized_at=None,
            total=None,
            total_max=total_max,
            marks=[],
        )
    marks: list[StudentMarkRow] = []
    total: int | None = None
    if submission.status in SETTLED_STATUSES:
        rows = (
            await db.execute(
                select(QuestionMark, AssignmentQuestion)
                .join(AssignmentQuestion, AssignmentQuestion.id == QuestionMark.question_id)
                .where(QuestionMark.submission_id == submission.id)
                .order_by(AssignmentQuestion.position)
            )
        ).all()
        remark_status = {
            mark_id: state
            for mark_id, state in (
                await db.execute(
                    select(RemarkRequest.question_mark_id, RemarkRequest.status).where(
                        RemarkRequest.question_mark_id.in_([m.id for m, _ in rows] or [0])
                    )
                )
            ).all()
        }
        marks = [
            StudentMarkRow(
                question_id=q.id,
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                final_marks=m.final_marks,
                final_feedback=m.final_feedback,
                remark_status=(
                    remark_status[m.id].value if m.id in remark_status else None
                ),
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
        # A submission waiting on the tutor still reads as "being marked" to
        # the student — they never see the AI's uncertainty.
        SubmissionStatus.needs_review: "being_marked",
        SubmissionStatus.auto_finalized: "marked",
        SubmissionStatus.finalized: "marked",
    }[submission.status]
    return StudentSubmissionView(
        submission_id=submission.id,
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
        if submission.status in SETTLED_STATUSES:
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


async def _open_remarks(db, submission_id: int) -> dict[int, str | None]:
    """question_mark_id -> the student's stated reason, for requests still open."""
    rows = (
        await db.execute(
            select(RemarkRequest.question_mark_id, RemarkRequest.reason)
            .join(QuestionMark, QuestionMark.id == RemarkRequest.question_mark_id)
            .where(
                QuestionMark.submission_id == submission_id,
                RemarkRequest.status == RemarkRequestStatus.open,
            )
        )
    ).all()
    return {mark_id: reason for mark_id, reason in rows}


async def _mark_rows(db, submission: Submission) -> list[MarkRow]:
    """One row per question, whether the submission is homework or a past
    paper — the review UI is the same either way."""
    open_remarks = await _open_remarks(db, submission.id)
    if submission.past_paper_id is not None:
        question, link = PastPaperQuestion, QuestionMark.past_paper_question_id
        scope = PastPaperQuestion.past_paper_id == submission.past_paper_id
    else:
        question, link = AssignmentQuestion, QuestionMark.question_id
        scope = AssignmentQuestion.assignment_id == submission.assignment_id
    rows = (
        await db.execute(
            select(question, QuestionMark)
            .outerjoin(
                QuestionMark,
                (link == question.id) & (QuestionMark.submission_id == submission.id),
            )
            .where(scope)
            .order_by(question.position)
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
            needs_review=m.needs_review if m else False,
            auto_finalized=m.auto_finalized if m else False,
            remark_requested=m.id in open_remarks if m else False,
            remark_reason=open_remarks.get(m.id) if m else None,
        )
        for q, m in rows
    ]


@router.get("/submissions/review-queue", response_model=list[ReviewQueueItem])
async def review_queue(db: DbSession, user: CurrentUser) -> list[ReviewQueueItem]:
    """Everything waiting on this tutor: submissions with at least one question
    the AI was unsure about, or with a student's remark request open. This is
    the whole of the tutor's marking workload — confidently marked work never
    appears here."""
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    # Left-joined both ways: a submission belongs to an assignment (homework)
    # or a past paper, never both, and the queue covers both kinds.
    rows = (
        await db.execute(
            select(Submission, Assignment, PastPaper, User)
            .outerjoin(Assignment, Assignment.id == Submission.assignment_id)
            .outerjoin(Group, Group.id == Assignment.group_id)
            .outerjoin(PastPaper, PastPaper.id == Submission.past_paper_id)
            .join(User, User.id == Submission.student_id)
            .where(
                Submission.status == SubmissionStatus.needs_review,
                (Group.organization_id == user.organization_id)
                | (PastPaper.organization_id == user.organization_id),
            )
            .order_by(Submission.submitted_at.desc())
        )
    ).all()
    out: list[ReviewQueueItem] = []
    for submission, assignment, past_paper, student in rows:
        unsure = (
            await db.scalar(
                select(func.count(QuestionMark.id)).where(
                    QuestionMark.submission_id == submission.id,
                    QuestionMark.needs_review.is_(True),
                )
            )
        ) or 0
        remarks = len(await _open_remarks(db, submission.id))
        out.append(
            ReviewQueueItem(
                submission_id=submission.id,
                assignment_id=assignment.id if assignment else None,
                past_paper_id=past_paper.id if past_paper else None,
                assignment_title=(
                    assignment.title
                    if assignment
                    else f"{past_paper.session_label} {past_paper.paper_number}"
                ),
                student_id=student.id,
                student_name=student.name,
                submitted_at=submission.submitted_at,
                unsure_count=unsure,
                remark_request_count=remarks,
            )
        )
    return out


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def submission_detail(submission_id: int, db: DbSession, user: CurrentUser) -> SubmissionDetail:
    submission = await _tutor_submission(db, user, submission_id)
    student = await db.get(User, submission.student_id)
    if submission.past_paper_id is not None:
        paper = await db.get(PastPaper, submission.past_paper_id)
        title = f"{paper.session_label} {paper.paper_number}"
    else:
        assignment = await db.get(Assignment, submission.assignment_id)
        title = assignment.title
    return SubmissionDetail(
        id=submission.id,
        assignment_id=submission.assignment_id,
        past_paper_id=submission.past_paper_id,
        assignment_title=title,
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
    """Set or change marks as the tutor. Works on an auto-finalized submission
    too — the tutor keeps override authority over any mark at any time — and
    every change to an already-set mark is written to the append-only audit."""
    submission = await _tutor_submission(db, user, submission_id)
    if submission.status == SubmissionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "This submission is already finalized")
    open_remarks = {
        r.question_mark_id: r
        for r in (
            await db.scalars(
                select(RemarkRequest)
                .join(QuestionMark, QuestionMark.id == RemarkRequest.question_mark_id)
                .where(
                    QuestionMark.submission_id == submission.id,
                    RemarkRequest.status == RemarkRequestStatus.open,
                )
            )
        ).all()
    }
    # Homework and past papers keep their questions in different tables; the
    # tutor's review screen is the same either way.
    is_past_paper = submission.past_paper_id is not None
    if is_past_paper:
        question_query = select(PastPaperQuestion).where(
            PastPaperQuestion.past_paper_id == submission.past_paper_id
        )
    else:
        question_query = select(AssignmentQuestion).where(
            AssignmentQuestion.assignment_id == submission.assignment_id
        )
    questions = {q.id: q for q in (await db.scalars(question_query)).all()}
    existing = {
        (m.past_paper_question_id if is_past_paper else m.question_id): m
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
            mark = QuestionMark(submission_id=submission.id)
            if is_past_paper:
                mark.past_paper_question_id = question.id
            else:
                mark.question_id = question.id
            db.add(mark)
            await db.flush()
            existing[question.id] = mark
        if update.final_marks is not None and update.final_marks > question.max_marks:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Q{question.number}: marks cannot exceed {question.max_marks}",
            )
        previous = mark.final_marks
        remark = open_remarks.get(mark.id)
        if previous is not None and previous != update.final_marks:
            # Changing a mark that already counted — record who, when, and
            # what it was. Append-only; nothing edits or deletes these.
            db.add(
                MarkOverrideAudit(
                    question_mark_id=mark.id,
                    old_marks=previous,
                    new_marks=update.final_marks,
                    changed_by_id=user.id,
                    reason="remark_request" if remark is not None else None,
                )
            )
        mark.final_marks = update.final_marks
        mark.final_feedback = update.final_feedback
        mark.overridden = mark.ai_marks is not None and update.final_marks != mark.ai_marks
        if update.final_marks is not None:
            # A tutor has now ruled on it, so it leaves the review queue —
            # whether they changed the number or confirmed the AI's.
            mark.needs_review = False
            mark.auto_finalized = False
        if remark is not None:
            remark.status = RemarkRequestStatus.resolved
            remark.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    await _refresh_review_state(db, submission)
    await db.commit()
    return await submission_detail(submission_id, db, user)


async def _subject_id(db, submission: Submission) -> int:
    """The subject a submission's evidence belongs to, from either side of the
    polymorphic split."""
    if submission.past_paper_id is not None:
        paper = await db.get(PastPaper, submission.past_paper_id)
        return paper.subject_id
    assignment = await db.get(Assignment, submission.assignment_id)
    group = await db.get(Group, assignment.group_id)
    return group.subject_id


async def _refresh_review_state(db, submission: Submission) -> None:
    """Move a submission out of the review queue once nothing on it is still
    waiting for a tutor. A submission that had already settled stays settled."""
    if submission.status not in (SubmissionStatus.needs_review, *SETTLED_STATUSES):
        return
    outstanding = await db.scalar(
        select(QuestionMark.id)
        .outerjoin(
            RemarkRequest,
            (RemarkRequest.question_mark_id == QuestionMark.id)
            & (RemarkRequest.status == RemarkRequestStatus.open),
        )
        .where(
            QuestionMark.submission_id == submission.id,
            (QuestionMark.needs_review.is_(True)) | (RemarkRequest.id.is_not(None)),
        )
        .limit(1)
    )
    if outstanding is not None:
        submission.status = SubmissionStatus.needs_review
    elif submission.status == SubmissionStatus.needs_review:
        # Everything is decided but no tutor has pressed finalize yet; leave it
        # for them to sign off rather than settling it behind their back.
        submission.status = SubmissionStatus.ai_marked


@router.post("/submissions/{submission_id}/finalize", response_model=SubmissionDetail)
async def finalize_submission(submission_id: int, db: DbSession, user: CurrentUser) -> SubmissionDetail:
    """Sign off a submission. Only the questions the AI wasn't sure about (and
    any open remark requests) need the tutor's attention — confidently
    auto-marked questions already carry a final mark."""
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
    unresolved = [m.number for m in marks if m.remark_requested]
    if unresolved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Resolve the open remark requests first (Q"
            + ", Q".join(unresolved)
            + ")",
        )
    submission.status = SubmissionStatus.finalized
    submission.finalized_at = datetime.now(timezone.utc)
    submission.finalized_by_id = user.id
    for row in await db.scalars(
        select(QuestionMark).where(QuestionMark.submission_id == submission.id)
    ):
        row.needs_review = False
    await db.flush()

    # Finalized marks become readiness evidence; recompute in the background.
    await record_marks_as_evidence(db, submission, await _subject_id(db, submission))
    await db.commit()
    return await submission_detail(submission_id, db, user)


@router.get(
    "/submissions/{submission_id}/marks/{question_id}/history",
    response_model=list[MarkHistoryEntry],
)
async def mark_history(
    submission_id: int, question_id: int, db: DbSession, user: CurrentUser
) -> list[MarkHistoryEntry]:
    """Every tutor change to this mark, oldest first."""
    submission = await _tutor_submission(db, user, submission_id)
    mark = await db.scalar(
        select(QuestionMark).where(
            QuestionMark.submission_id == submission.id,
            QuestionMark.question_id == question_id,
        )
    )
    if mark is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mark not found")
    rows = (
        await db.execute(
            select(MarkOverrideAudit, User)
            .join(User, User.id == MarkOverrideAudit.changed_by_id)
            .where(MarkOverrideAudit.question_mark_id == mark.id)
            .order_by(MarkOverrideAudit.created_at)
        )
    ).all()
    return [
        MarkHistoryEntry(
            old_marks=audit.old_marks,
            new_marks=audit.new_marks,
            changed_by_name=changed_by.name,
            reason=audit.reason,
            created_at=audit.created_at,
        )
        for audit, changed_by in rows
    ]


@router.post(
    "/submissions/{submission_id}/questions/{question_id}/remark-request",
    response_model=RemarkRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_remark(
    submission_id: int,
    question_id: int,
    body: RemarkRequestCreate,
    db: DbSession,
    user: CurrentUser,
) -> RemarkRequestOut:
    """A student contesting a mark that counted. This never triggers an AI
    re-mark: it puts the question in front of the tutor, with the AI's original
    reasoning attached. One request per question, ever — once the tutor rules
    on it, that question is settled."""
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    submission = await db.get(Submission, submission_id)
    if submission is None or submission.student_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    mark = await db.scalar(
        select(QuestionMark).where(
            QuestionMark.submission_id == submission.id,
            QuestionMark.question_id == question_id,
        )
    )
    if mark is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mark not found")
    if mark.final_marks is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This question hasn't been marked yet"
        )
    existing = await db.scalar(
        select(RemarkRequest).where(RemarkRequest.question_mark_id == mark.id)
    )
    if existing is not None:
        detail = (
            "You've already asked for this question to be looked at again"
            if existing.status == RemarkRequestStatus.open
            else "This question has already been re-marked by your tutor"
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail)

    request = RemarkRequest(
        question_mark_id=mark.id, requested_by_id=user.id, reason=body.reason
    )
    db.add(request)
    # Put the submission back in front of the tutor.
    submission.status = SubmissionStatus.needs_review
    await db.commit()
    return RemarkRequestOut(
        id=request.id,
        question_id=question_id,
        status=request.status.value,
        reason=request.reason,
        created_at=request.created_at,
    )
