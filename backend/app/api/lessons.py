from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor
from app.models import (
    Group,
    GroupMember,
    Lesson,
    LessonMode,
    LessonObservation,
    LessonTopic,
    Topic,
    User,
    UserRole,
)
from app.schemas.groups import TopicOut
from app.schemas.lessons import (
    AttendanceRowOut,
    AttendanceUpdate,
    LessonCreate,
    LessonObservationCreate,
    LessonObservationOut,
    LessonOut,
    LessonTopicsUpdate,
    LessonUpdate,
)
from app.services import attendance, meeting_integrations, plan_lessons
from app.services.meeting_common import MeetingLinkError, parse_meeting_link
from app.services.plan_lessons import ScheduleSlotNotFound
from app.services.teaching_plan import PlanInputError, PlanSlotNotFound, PlanStateError

router = APIRouter(prefix="/lessons", tags=["lessons"])


async def _owned_group(db: AsyncSession, user: User, group_id: int) -> Group:
    assert_tutor(user)
    group = await db.get(Group, group_id)
    # The organization check binds first and applies to admins too: an admin has
    # wider reach inside their organization, not across organizations (`SEC-7`).
    if (
        group is None
        or group.organization_id != user.organization_id
        or (group.tutor_id != user.id and user.role != UserRole.admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


async def _owned_lesson(db: AsyncSession, user: User, lesson_id: int) -> Lesson:
    assert_tutor(user)
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    group = await db.get(Group, lesson.group_id)
    # The organization check binds first and applies to admins too: an admin has
    # wider reach inside their organization, not across organizations (`SEC-7`).
    # The lesson's own organization is checked as well as its group's — two
    # columns with no constraint tying them together.
    if (
        group is None
        or lesson.organization_id != user.organization_id
        or group.organization_id != user.organization_id
        or (group.tutor_id != user.id and user.role != UserRole.admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return lesson


def _check_meeting_link(link: str, mode: LessonMode) -> None:
    """A meeting link must be a Zoom/Meet one and belongs to an online lesson."""
    if mode != LessonMode.online:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Only an online lesson can have a meeting link."
        )
    try:
        parse_meeting_link(link)
    except MeetingLinkError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


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
        mode=lesson.mode,
        start_time=lesson.start_time,
        origin=lesson.origin,
        topics=[TopicOut.model_validate(t) for t in topic_rows],
        meeting_provider=lesson.meeting_provider,
        meeting_link=meeting_integrations.lesson_link(lesson),
    )


@router.post("", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(body: LessonCreate, db: DbSession, user: CurrentUser) -> LessonOut:
    group = await _owned_group(db, user, body.group_id)
    if body.meeting_link is not None:
        _check_meeting_link(body.meeting_link, body.mode)
    try:
        lesson = await plan_lessons.create_lesson(
            db,
            group=group,
            lesson_date=body.date,
            duration_min=body.duration_min,
            notes=body.notes,
            schedule_slot_id=body.schedule_slot_id,
            topic_ids=body.topic_ids,
            plan_slot_id=body.plan_slot_id,
            mode=body.mode,
            start_time=body.start_time,
        )
    except PlanSlotNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planned lesson not found") from exc
    except ScheduleSlotNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable slot not found") from exc
    except PlanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except PlanStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if body.meeting_link is not None:
        await meeting_integrations.set_lesson_meeting(db, lesson, body.meeting_link)
        await db.commit()
    return await _lesson_out(db, lesson)


@router.get("/group/{group_id}", response_model=list[LessonOut])
async def list_group_lessons(group_id: int, db: DbSession, user: CurrentUser) -> list[LessonOut]:
    group = await _owned_group(db, user, group_id)
    lessons = (
        await db.scalars(
            select(Lesson)
            # Same rule as `_owned_lesson`: the lesson's own organization, not
            # only its group's (`SEC-7`).
            .where(Lesson.group_id == group.id, Lesson.organization_id == user.organization_id)
            .order_by(Lesson.date.desc(), Lesson.start_time.desc().nulls_last(), Lesson.id.desc())
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
    if body.meeting_link is not None:
        _check_meeting_link(body.meeting_link, body.mode or lesson.mode)
    if body.date is not None:
        lesson.date = body.date
    if body.duration_min is not None:
        lesson.duration_min = body.duration_min
    if body.notes is not None:
        lesson.notes = body.notes
    if body.mode is not None:
        lesson.mode = body.mode
    # An explicit null clears the time (back to unknown); omitting it leaves it.
    if "start_time" in body.model_fields_set:
        lesson.start_time = body.start_time
    # An explicit null clears the link (and what was imported from it).
    if "meeting_link" in body.model_fields_set:
        await meeting_integrations.set_lesson_meeting(db, lesson, body.meeting_link)
    await db.commit()
    return await _lesson_out(db, lesson)


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(lesson_id: int, db: DbSession, user: CurrentUser) -> None:
    lesson = await _owned_lesson(db, user, lesson_id)
    await plan_lessons.release_slot_for_lesson(db, lesson.id)
    await attendance.delete_for_lesson(db, lesson.id)
    await meeting_integrations.delete_for_lesson(db, lesson.id)
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
    group = await db.get(Group, lesson.group_id)
    assert group is not None  # `_owned_lesson` just resolved it
    try:
        await plan_lessons.replace_lesson_topics(
            db, group=group, lesson=lesson, topic_ids=body.topic_ids
        )
    except PlanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
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

    # The rating stays on the observation, which belongs to the student
    # profile. It is not readiness evidence and queues no recompute (PROD-15).
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


async def _register(db: AsyncSession, lesson: Lesson) -> list[AttendanceRowOut]:
    rows = await attendance.lesson_register(db, lesson)
    return [
        AttendanceRowOut(
            student_id=r.student_id,
            name=r.name,
            state=r.state,
            source=r.source,
            recorded_at=r.recorded_at,
        )
        for r in rows
    ]


@router.get("/{lesson_id}/attendance", response_model=list[AttendanceRowOut])
async def lesson_attendance(
    lesson_id: int, db: DbSession, user: TutorUser
) -> list[AttendanceRowOut]:
    """The register: every student in the class, `state: null` where not taken."""
    lesson = await _owned_lesson(db, user, lesson_id)
    return await _register(db, lesson)


@router.put("/{lesson_id}/attendance", response_model=list[AttendanceRowOut])
async def set_lesson_attendance(
    lesson_id: int, body: AttendanceUpdate, db: DbSession, user: TutorUser
) -> list[AttendanceRowOut]:
    lesson = await _owned_lesson(db, user, lesson_id)
    try:
        await attendance.set_attendance(
            db,
            lesson,
            [attendance.AttendanceEntry(e.student_id, e.state) for e in body.entries],
            recorded_by=user,
        )
    except attendance.AttendanceConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Attendance was changed at the same time — refresh and try again",
        ) from exc
    except attendance.AttendanceStudentNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Student not found in this lesson's group"
        ) from exc
    return await _register(db, lesson)
