from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Evidence,
    Group,
    GroupMember,
    ParentLink,
    ReadinessHistory,
    Subject,
    Topic,
    TopicReadiness,
    User,
    UserRole,
)
from app.schemas.readiness import (
    EvidenceItem,
    StudentReadinessSummary,
    SubjectTrend,
    TopicEvidence,
    TrendPoint,
)
from app.services.readiness_summary import build_summary

router = APIRouter(prefix="/readiness", tags=["readiness"])


async def visible_subject_ids(db: AsyncSession, viewer: User, student_id: int) -> list[int] | None:
    """Return the subject ids the viewer may see for this student, or raise 403.

    Students see their own subjects; parents see linked children's; tutors see
    only the subjects they teach that student; admins see everything.
    """
    # Subjects the student is enrolled in (via group membership).
    enrolled = (
        await db.scalars(
            select(Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == student_id)
        )
    ).all()
    enrolled_set = set(enrolled)

    if viewer.role == UserRole.admin:
        return list(enrolled_set)
    if viewer.role == UserRole.student:
        if viewer.id != student_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return list(enrolled_set)
    if viewer.role == UserRole.parent:
        link = await db.scalar(
            select(ParentLink).where(
                ParentLink.parent_id == viewer.id, ParentLink.student_id == student_id
            )
        )
        if link is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return list(enrolled_set)
    if viewer.role == UserRole.tutor:
        taught = (
            await db.scalars(
                select(Group.subject_id)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.student_id == student_id, Group.tutor_id == viewer.id)
            )
        ).all()
        taught_set = set(taught)
        if not taught_set:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
        return list(taught_set)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


@router.get("/me", response_model=StudentReadinessSummary)
async def my_readiness(db: DbSession, user: CurrentUser) -> StudentReadinessSummary:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    subject_ids = await visible_subject_ids(db, user, user.id)
    return await build_summary(db, user, subject_ids or [])


@router.get("/students/{student_id}", response_model=StudentReadinessSummary)
async def student_readiness(
    student_id: int, db: DbSession, user: CurrentUser
) -> StudentReadinessSummary:
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    subject_ids = await visible_subject_ids(db, user, student_id)
    return await build_summary(db, student, subject_ids or [])


@router.get(
    "/students/{student_id}/topics/{topic_id}/evidence", response_model=TopicEvidence
)
async def topic_evidence(
    student_id: int, topic_id: int, db: DbSession, user: CurrentUser
) -> TopicEvidence:
    """Drill-down: the evidence behind one topic's readiness score."""
    subject_ids = await visible_subject_ids(db, user, student_id)
    topic = await db.get(Topic, topic_id)
    if topic is None or topic.subject_id not in (subject_ids or []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    readiness = await db.scalar(
        select(TopicReadiness).where(
            TopicReadiness.student_id == student_id, TopicReadiness.topic_id == topic_id
        )
    )
    evidence_rows = (
        await db.scalars(
            select(Evidence)
            .where(Evidence.student_id == student_id, Evidence.topic_id == topic_id)
            .order_by(Evidence.occurred_at.desc())
        )
    ).all()
    return TopicEvidence(
        topic_id=topic.id,
        topic_code=topic.code,
        topic_title=topic.title,
        score=readiness.score if readiness else 0.0,
        confidence=readiness.confidence.value if readiness else "none",
        evidence=[
            EvidenceItem(
                source_type=e.source_type.value,
                score_pct=e.score_pct,
                max_marks=e.max_marks,
                occurred_at=e.occurred_at,
                label=e.label,
            )
            for e in evidence_rows
        ],
    )


@router.get("/students/{student_id}/trend", response_model=list[SubjectTrend])
async def student_trend(
    student_id: int, db: DbSession, user: CurrentUser
) -> list[SubjectTrend]:
    subject_ids = await visible_subject_ids(db, user, student_id)
    out: list[SubjectTrend] = []
    for subject_id in subject_ids or []:
        subject = await db.get(Subject, subject_id)
        points = (
            await db.scalars(
                select(ReadinessHistory)
                .where(
                    ReadinessHistory.student_id == student_id,
                    ReadinessHistory.subject_id == subject_id,
                )
                .order_by(ReadinessHistory.recorded_at)
            )
        ).all()
        if not points:
            continue
        out.append(
            SubjectTrend(
                subject_id=subject_id,
                subject_name=subject.name,
                points=[TrendPoint(recorded_at=p.recorded_at, score=p.score) for p in points],
            )
        )
    return out
