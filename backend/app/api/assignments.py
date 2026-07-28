from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Classified,
    Group,
    GroupMember,
    QuestionTopic,
    Submission,
    Topic,
    User,
    UserRole,
)
from app.schemas.groups import TopicOut
from app.schemas.homework import (
    AssignmentCreate,
    AssignmentDetail,
    AssignmentOut,
    QuestionIn,
    QuestionOut,
    StudentAssignment,
)
from app.services import storage
from app.workers.jobs import enqueue

router = APIRouter(prefix="/assignments", tags=["assignments"])


async def _owned_assignment(db, user: User, assignment_id: int) -> Assignment:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    group = await db.get(Group, assignment.group_id)
    if group.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return assignment


async def _question_rows(db, assignment_id: int) -> list[QuestionOut]:
    questions = (
        await db.scalars(
            select(AssignmentQuestion)
            .where(AssignmentQuestion.assignment_id == assignment_id)
            .options(selectinload(AssignmentQuestion.topics))
            .order_by(AssignmentQuestion.position)
        )
    ).all()
    topic_ids = {qt.topic_id for q in questions for qt in q.topics}
    topics = {}
    if topic_ids:
        for t in (await db.scalars(select(Topic).where(Topic.id.in_(topic_ids)))).all():
            topics[t.id] = TopicOut.model_validate(t)
    return [
        QuestionOut(
            id=q.id,
            number=q.number,
            text_summary=q.text_summary,
            max_marks=q.max_marks,
            has_mark_scheme=q.has_mark_scheme,
            topics=[topics[qt.topic_id] for qt in q.topics if qt.topic_id in topics],
        )
        for q in questions
    ]


@router.post("", response_model=AssignmentDetail, status_code=status.HTTP_201_CREATED)
async def create_assignment(body: AssignmentCreate, db: DbSession, user: CurrentUser) -> AssignmentDetail:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    group = await db.get(Group, body.group_id)
    if group is None or group.tutor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    classified = await db.get(Classified, body.classified_id)
    if classified is None or classified.tutor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classified not found")
    if classified.subject_id != group.subject_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This classified belongs to a different subject than the group",
        )
    assignment = Assignment(
        group_id=group.id,
        classified_id=classified.id,
        title=body.title,
        instructions=body.instructions,
        due_at=body.due_at,
        question_range=body.question_range,
        status=AssignmentStatus.extracting,
    )
    db.add(assignment)
    await db.flush()
    await enqueue(db, "extract_assignment", {"assignment_id": assignment.id})
    await db.commit()
    return AssignmentDetail(
        id=assignment.id,
        group_id=assignment.group_id,
        classified_id=assignment.classified_id,
        title=assignment.title,
        instructions=assignment.instructions,
        due_at=assignment.due_at,
        question_range=assignment.question_range,
        status=assignment.status.value,
        extraction_error=None,
        questions=[],
    )


@router.post("/upload", response_model=AssignmentDetail, status_code=status.HTTP_201_CREATED)
async def create_assignment_with_paper(
    db: DbSession,
    user: CurrentUser,
    group_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str | None, Form()] = None,
    instructions: Annotated[str | None, Form()] = None,
    due_at: Annotated[datetime | None, Form()] = None,
    question_range: Annotated[str | None, Form()] = None,
) -> AssignmentDetail:
    """Upload a question paper and set it as homework in one request.

    Previously the client had to POST the classified and then POST the
    assignment; a failure between the two left an orphaned classified behind.
    Only the group and the file are required — the title falls back to the
    file name, and everything else can be edited afterwards.
    """
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    group = await db.get(Group, group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    path, name, mime = await storage.save_upload(file)
    # "4CH1 June 2023 Paper 1.pdf" -> "4CH1 June 2023 Paper 1"
    fallback_title = Path(name).stem or name
    classified = Classified(
        tutor_id=user.id,
        subject_id=group.subject_id,
        title=(title or fallback_title)[:255],
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
    await db.flush()

    assignment = Assignment(
        group_id=group.id,
        classified_id=classified.id,
        title=(title or fallback_title)[:255],
        instructions=instructions or None,
        due_at=due_at,
        question_range=question_range or None,
        status=AssignmentStatus.extracting,
    )
    db.add(assignment)
    await db.flush()
    await enqueue(db, "extract_assignment", {"assignment_id": assignment.id})
    await db.commit()
    return AssignmentDetail(
        id=assignment.id,
        group_id=assignment.group_id,
        classified_id=assignment.classified_id,
        title=assignment.title,
        instructions=assignment.instructions,
        due_at=assignment.due_at,
        question_range=assignment.question_range,
        status=assignment.status.value,
        extraction_error=None,
        questions=[],
    )


@router.get("/group/{group_id}", response_model=list[AssignmentOut])
async def list_group_assignments(group_id: int, db: DbSession, user: CurrentUser) -> list[AssignmentOut]:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    group = await db.get(Group, group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    assignments = (
        await db.scalars(
            select(Assignment).where(Assignment.group_id == group_id).order_by(Assignment.created_at.desc())
        )
    ).all()
    out = []
    for a in assignments:
        stats = (
            await db.execute(
                select(
                    func.count(AssignmentQuestion.id),
                    func.coalesce(func.sum(AssignmentQuestion.max_marks), 0),
                ).where(AssignmentQuestion.assignment_id == a.id)
            )
        ).one()
        submission_count = (
            await db.scalar(
                select(func.count(Submission.id)).where(Submission.assignment_id == a.id)
            )
        ) or 0
        out.append(
            AssignmentOut(
                id=a.id,
                group_id=a.group_id,
                title=a.title,
                status=a.status.value,
                due_at=a.due_at,
                question_count=stats[0],
                total_marks=stats[1],
                submission_count=submission_count,
            )
        )
    return out


@router.get("/{assignment_id}", response_model=AssignmentDetail)
async def assignment_detail(assignment_id: int, db: DbSession, user: CurrentUser) -> AssignmentDetail:
    assignment = await _owned_assignment(db, user, assignment_id)
    return AssignmentDetail(
        id=assignment.id,
        group_id=assignment.group_id,
        classified_id=assignment.classified_id,
        title=assignment.title,
        instructions=assignment.instructions,
        due_at=assignment.due_at,
        question_range=assignment.question_range,
        status=assignment.status.value,
        extraction_error=assignment.extraction_error,
        questions=await _question_rows(db, assignment.id),
    )


@router.put("/{assignment_id}/questions", response_model=AssignmentDetail)
async def replace_questions(
    assignment_id: int, body: list[QuestionIn], db: DbSession, user: CurrentUser
) -> AssignmentDetail:
    """Bulk-replace the question list.

    Assignments publish themselves once extraction succeeds, so "published" can
    no longer mean "locked" — the tutor would never get to correct the AI. The
    real constraint is work already submitted against these questions, since
    replacing them would orphan its marks.
    """
    assignment = await _owned_assignment(db, user, assignment_id)
    if assignment.status == AssignmentStatus.closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This homework is closed")
    submitted = await db.scalar(
        select(func.count(Submission.id)).where(Submission.assignment_id == assignment.id)
    )
    if submitted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Students have already submitted, so the questions can't change now",
        )
    existing = (
        await db.scalars(
            select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment.id)
        )
    ).all()
    for q in existing:
        await db.delete(q)
    await db.flush()
    for position, q in enumerate(body):
        question = AssignmentQuestion(
            assignment_id=assignment.id,
            position=position,
            number=q.number,
            text_summary=q.text_summary,
            max_marks=q.max_marks,
            has_mark_scheme=q.has_mark_scheme,
        )
        db.add(question)
        await db.flush()
        for topic_id in set(q.topic_ids):
            topic = await db.get(Topic, topic_id)
            if topic is not None:
                db.add(QuestionTopic(question_id=question.id, topic_id=topic_id))
    if assignment.status == AssignmentStatus.extraction_failed and body:
        assignment.status = AssignmentStatus.review
    await db.commit()
    return await assignment_detail(assignment_id, db, user)


@router.post("/{assignment_id}/publish", response_model=AssignmentDetail)
async def publish_assignment(assignment_id: int, db: DbSession, user: CurrentUser) -> AssignmentDetail:
    assignment = await _owned_assignment(db, user, assignment_id)
    if assignment.status not in (AssignmentStatus.review, AssignmentStatus.extraction_failed):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only assignments in review can be published")
    count = await db.scalar(
        select(func.count(AssignmentQuestion.id)).where(
            AssignmentQuestion.assignment_id == assignment.id
        )
    )
    if not count:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one question first")
    assignment.status = AssignmentStatus.published
    await db.commit()
    return await assignment_detail(assignment_id, db, user)


@router.post("/{assignment_id}/retry-extraction", response_model=AssignmentDetail)
async def retry_extraction(assignment_id: int, db: DbSession, user: CurrentUser) -> AssignmentDetail:
    assignment = await _owned_assignment(db, user, assignment_id)
    if assignment.status not in (AssignmentStatus.extraction_failed, AssignmentStatus.review):
        raise HTTPException(status.HTTP_409_CONFLICT, "Extraction can only be retried before publishing")
    existing = (
        await db.scalars(
            select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment.id)
        )
    ).all()
    for q in existing:
        await db.delete(q)
    assignment.status = AssignmentStatus.extracting
    assignment.extraction_error = None
    await enqueue(db, "extract_assignment", {"assignment_id": assignment.id})
    await db.commit()
    return await assignment_detail(assignment_id, db, user)
