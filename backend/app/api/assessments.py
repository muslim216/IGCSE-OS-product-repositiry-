from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    Evidence,
    EvidenceSource,
    Group,
    GroupMember,
    Subject,
    Topic,
    TutorObservation,
    User,
    UserRole,
)
from app.schemas.readiness import (
    AssessmentCreate,
    AssessmentOut,
    ObservationCreate,
    ObservationOut,
)
from app.workers.jobs import enqueue

router = APIRouter(tags=["assessments"])


def _require_tutor(user: User) -> None:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


async def _tutor_teaches(db, tutor_id: int, student_id: int, subject_id: int) -> bool:
    row = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(
            GroupMember.student_id == student_id,
            Group.tutor_id == tutor_id,
            Group.subject_id == subject_id,
        )
        .limit(1)
    )
    return row is not None


@router.post("/assessments", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED)
async def create_assessment(body: AssessmentCreate, db: DbSession, user: CurrentUser) -> AssessmentOut:
    _require_tutor(user)
    subject = await db.get(Subject, body.subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    assessment = Assessment(
        tutor_id=user.id,
        subject_id=subject.id,
        title=body.title,
        type=AssessmentType(body.type),
        date=body.date,
    )
    db.add(assessment)
    await db.flush()

    occurred = datetime(body.date.year, body.date.month, body.date.day, tzinfo=timezone.utc)
    affected_students: set[int] = set()
    for s in body.scores:
        if not await _tutor_teaches(db, user.id, s.student_id, subject.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only enter marks for students you teach this subject",
            )
        if s.topic_id is not None:
            topic = await db.get(Topic, s.topic_id)
            if topic is None or topic.subject_id != subject.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid topic for subject")
        if s.marks > s.max_marks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "marks cannot exceed max_marks")
        db.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=s.student_id,
                topic_id=s.topic_id,
                marks=s.marks,
                max_marks=s.max_marks,
            )
        )
        score_pct = round(s.marks / s.max_marks * 100, 1)
        source_ref = f"assessment:{assessment.id}"
        if s.topic_id is not None:
            # Per-topic score → evidence on that topic.
            db.add(
                Evidence(
                    student_id=s.student_id,
                    topic_id=s.topic_id,
                    source_type=EvidenceSource.mock,
                    score_pct=score_pct,
                    max_marks=s.max_marks,
                    occurred_at=occurred,
                    source_ref=source_ref,
                    label=body.title,
                )
            )
        else:
            # Overall score → spread as evidence across every topic of the subject.
            topics = (await db.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
            for topic in topics:
                db.add(
                    Evidence(
                        student_id=s.student_id,
                        topic_id=topic.id,
                        source_type=EvidenceSource.mock,
                        score_pct=score_pct,
                        max_marks=s.max_marks,
                        occurred_at=occurred,
                        source_ref=source_ref,
                        label=f"{body.title} (overall)",
                    )
                )
        affected_students.add(s.student_id)

    for student_id in affected_students:
        await enqueue(db, "recompute_readiness", {"student_id": student_id, "subject_id": subject.id})
    await db.commit()
    return AssessmentOut(
        id=assessment.id,
        subject_id=subject.id,
        title=assessment.title,
        type=assessment.type.value,
        date=assessment.date,
        score_count=len(body.scores),
    )


@router.get("/assessments", response_model=list[AssessmentOut])
async def list_assessments(db: DbSession, user: CurrentUser, subject_id: int | None = None) -> list[AssessmentOut]:
    _require_tutor(user)
    query = select(Assessment).where(Assessment.tutor_id == user.id).order_by(Assessment.date.desc())
    if subject_id is not None:
        query = query.where(Assessment.subject_id == subject_id)
    rows = (await db.scalars(query)).all()
    out = []
    for a in rows:
        count = await db.scalar(
            select(func.count(AssessmentScore.id)).where(AssessmentScore.assessment_id == a.id)
        )
        out.append(
            AssessmentOut(
                id=a.id,
                subject_id=a.subject_id,
                title=a.title,
                type=a.type.value,
                date=a.date,
                score_count=count or 0,
            )
        )
    return out


@router.post("/observations", response_model=ObservationOut, status_code=status.HTTP_201_CREATED)
async def create_observation(body: ObservationCreate, db: DbSession, user: CurrentUser) -> ObservationOut:
    _require_tutor(user)
    # The tutor must share at least one group with the student.
    shares = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == body.student_id, Group.tutor_id == user.id)
        .limit(1)
    )
    if shares is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")

    subject_id_for_recompute: int | None = None
    if body.topic_id is not None:
        topic = await db.get(Topic, body.topic_id)
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
        subject_id_for_recompute = topic.subject_id

    observation = TutorObservation(
        tutor_id=user.id,
        student_id=body.student_id,
        topic_id=body.topic_id,
        comment=body.comment,
        rating=body.rating,
    )
    db.add(observation)
    await db.flush()

    # A rating on a specific topic feeds readiness as observation evidence.
    if body.rating is not None and body.topic_id is not None:
        db.add(
            Evidence(
                student_id=body.student_id,
                topic_id=body.topic_id,
                source_type=EvidenceSource.observation,
                score_pct=float(body.rating),
                max_marks=0,
                occurred_at=datetime.now(timezone.utc),
                source_ref=f"observation:{observation.id}",
                label="Tutor observation",
            )
        )
        await enqueue(
            db,
            "recompute_readiness",
            {"student_id": body.student_id, "subject_id": subject_id_for_recompute},
        )
    await db.commit()
    return ObservationOut(
        id=observation.id,
        student_id=observation.student_id,
        topic_id=observation.topic_id,
        comment=observation.comment,
        rating=observation.rating,
        created_at=observation.created_at,
    )


@router.get("/students/{student_id}/observations", response_model=list[ObservationOut])
async def list_observations(student_id: int, db: DbSession, user: CurrentUser) -> list[ObservationOut]:
    _require_tutor(user)
    shares = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.tutor_id == user.id)
        .limit(1)
    )
    if shares is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")
    rows = (
        await db.scalars(
            select(TutorObservation)
            .where(TutorObservation.student_id == student_id, TutorObservation.tutor_id == user.id)
            .order_by(TutorObservation.created_at.desc())
        )
    ).all()
    return [
        ObservationOut(
            id=o.id,
            student_id=o.student_id,
            topic_id=o.topic_id,
            comment=o.comment,
            rating=o.rating,
            created_at=o.created_at,
        )
        for o in rows
    ]
