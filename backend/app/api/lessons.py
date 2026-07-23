from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Evidence,
    EvidenceSource,
    Group,
    GroupMember,
    Lesson,
    LessonObservation,
    LessonTopic,
    Topic,
    User,
    UserRole,
)
from app.schemas.groups import TopicOut
from app.schemas.lessons import (
    LessonCreate,
    LessonObservationCreate,
    LessonObservationOut,
    LessonOut,
    LessonTopicsUpdate,
    LessonUpdate,
)
from app.workers.jobs import enqueue

router = APIRouter(prefix="/lessons", tags=["lessons"])


async def _owned_group(db: AsyncSession, user: User, group_id: int) -> Group:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    group = await db.get(Group, group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


async def _owned_lesson(db: AsyncSession, user: User, lesson_id: int) -> Lesson:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    group = await db.get(Group, lesson.group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return lesson


async def _lesson_out(db: AsyncSession, lesson: Lesson) -> LessonOut:
    topic_rows = (
        await db.scalars(
            select(Topic)
            .join(LessonTopic, LessonTopic.topic_id == Topic.id)
            .where(LessonTopic.lesson_id == lesson.id)
        )
    ).all()
    return LessonOut(
        id=lesson.id,
        group_id=lesson.group_id,
        date=lesson.date,
        duration_min=lesson.duration_min,
        notes=lesson.notes,
        schedule_slot_id=lesson.schedule_slot_id,
        topics=[TopicOut.model_validate(t) for t in topic_rows],
    )


@router.post("", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(body: LessonCreate, db: DbSession, user: CurrentUser) -> LessonOut:
    group = await _owned_group(db, user, body.group_id)
    lesson = Lesson(
        organization_id=user.organization_id,
        group_id=group.id,
        date=body.date,
        duration_min=body.duration_min,
        notes=body.notes,
        schedule_slot_id=body.schedule_slot_id,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return await _lesson_out(db, lesson)


@router.get("/group/{group_id}", response_model=list[LessonOut])
async def list_group_lessons(group_id: int, db: DbSession, user: CurrentUser) -> list[LessonOut]:
    group = await _owned_group(db, user, group_id)
    lessons = (
        await db.scalars(
            select(Lesson).where(Lesson.group_id == group.id).order_by(Lesson.date.desc())
        )
    ).all()
    return [await _lesson_out(db, lesson) for lesson in lessons]


@router.get("/{lesson_id}", response_model=LessonOut)
async def lesson_detail(lesson_id: int, db: DbSession, user: CurrentUser) -> LessonOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    return await _lesson_out(db, lesson)


@router.patch("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int, body: LessonUpdate, db: DbSession, user: CurrentUser
) -> LessonOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    if body.date is not None:
        lesson.date = body.date
    if body.duration_min is not None:
        lesson.duration_min = body.duration_min
    if body.notes is not None:
        lesson.notes = body.notes
    await db.commit()
    return await _lesson_out(db, lesson)


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(lesson_id: int, db: DbSession, user: CurrentUser) -> None:
    lesson = await _owned_lesson(db, user, lesson_id)
    await db.delete(lesson)
    await db.commit()


@router.put("/{lesson_id}/topics", response_model=LessonOut)
async def set_lesson_topics(
    lesson_id: int, body: LessonTopicsUpdate, db: DbSession, user: CurrentUser
) -> LessonOut:
    """Mark syllabus topics as covered in this lesson — the evidence-based
    root of Syllabus Coverage. Every student in the group is considered
    taught these topics as of the lesson date."""
    lesson = await _owned_lesson(db, user, lesson_id)
    existing = (
        await db.scalars(select(LessonTopic).where(LessonTopic.lesson_id == lesson.id))
    ).all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    for topic_id in set(body.topic_ids):
        topic = await db.get(Topic, topic_id)
        if topic is not None:
            db.add(LessonTopic(lesson_id=lesson.id, topic_id=topic_id))
    await db.commit()
    return await _lesson_out(db, lesson)


@router.post(
    "/{lesson_id}/observations",
    response_model=LessonObservationOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_lesson_observation(
    lesson_id: int, body: LessonObservationCreate, db: DbSession, user: CurrentUser
) -> LessonObservationOut:
    lesson = await _owned_lesson(db, user, lesson_id)
    shares = await db.scalar(
        select(GroupMember.id).where(
            GroupMember.group_id == lesson.group_id, GroupMember.student_id == body.student_id
        )
    )
    if shares is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in this lesson's group")
    topic = None
    if body.topic_id is not None:
        topic = await db.get(Topic, body.topic_id)
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")

    observation = LessonObservation(
        lesson_id=lesson.id,
        student_id=body.student_id,
        topic_id=body.topic_id,
        body=body.body,
        rating=body.rating,
    )
    db.add(observation)
    await db.flush()

    # A rating on a specific topic feeds readiness as observation evidence —
    # same pattern as the free-floating tutor observation (api/assessments.py).
    if body.rating is not None and topic is not None:
        db.add(
            Evidence(
                student_id=body.student_id,
                topic_id=topic.id,
                source_type=EvidenceSource.observation,
                score_pct=float(body.rating),
                max_marks=0,
                occurred_at=datetime.now(timezone.utc),
                source_ref=f"lesson_observation:{observation.id}",
                label="Lesson observation",
            )
        )
        await enqueue(
            db,
            "recompute_readiness",
            {"student_id": body.student_id, "subject_id": topic.subject_id},
        )
    await db.commit()
    return LessonObservationOut(
        id=observation.id,
        lesson_id=lesson.id,
        student_id=observation.student_id,
        topic_id=observation.topic_id,
        body=observation.body,
        rating=observation.rating,
        created_at=observation.created_at,
    )


@router.get("/{lesson_id}/observations", response_model=list[LessonObservationOut])
async def list_lesson_observations(
    lesson_id: int, db: DbSession, user: CurrentUser
) -> list[LessonObservationOut]:
    lesson = await _owned_lesson(db, user, lesson_id)
    rows = (
        await db.scalars(
            select(LessonObservation)
            .where(LessonObservation.lesson_id == lesson.id)
            .order_by(LessonObservation.created_at.desc())
        )
    ).all()
    return [
        LessonObservationOut(
            id=o.id,
            lesson_id=o.lesson_id,
            student_id=o.student_id,
            topic_id=o.topic_id,
            body=o.body,
            rating=o.rating,
            created_at=o.created_at,
        )
        for o in rows
    ]
