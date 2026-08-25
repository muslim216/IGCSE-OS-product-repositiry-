from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, TutorUser
from app.models import (
    Assignment,
    Group,
    GroupMember,
    QuestionMark,
    Subject,
    Submission,
    SubmissionStatus,
    Topic,
    TopicReadiness,
    User,
    UserRole,
)
from app.models.readiness import ReadinessConfidence
from app.schemas.readiness import (
    AgreementStats,
    TopicHeat,
    TutorAnalytics,
    WeakStudent,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

WEAK_THRESHOLD = 60.0


@router.get("/groups/{group_id}", response_model=TutorAnalytics)
async def group_analytics(group_id: int, db: DbSession, user: TutorUser) -> TutorAnalytics:
    group = await db.get(Group, group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    subject = await db.get(Subject, group.subject_id)
    subject_name = subject.name if subject else ""
    student_ids = (
        await db.scalars(select(GroupMember.student_id).where(GroupMember.group_id == group_id))
    ).all()
    topics = (await db.scalars(select(Topic).where(Topic.subject_id == group.subject_id))).all()
    topic_by_id = {t.id: t for t in topics}
    topic_ids = list(topic_by_id.keys())

    # Weak students: subject-weighted readiness per student, lowest first.
    weak_students: list[WeakStudent] = []
    topic_scores: dict[int, list[float]] = {}
    for sid in student_ids:
        student = await db.get(User, sid)
        rows = (
            await db.scalars(
                select(TopicReadiness).where(
                    TopicReadiness.student_id == sid,
                    TopicReadiness.topic_id.in_(topic_ids or [0]),
                )
            )
        ).all()
        confident = [r for r in rows if r.confidence != ReadinessConfidence.none]
        if not confident:
            continue
        weighted = sum(topic_by_id[r.topic_id].weight * r.score for r in confident)
        weight_total = sum(topic_by_id[r.topic_id].weight for r in confident)
        overall = round(weighted / weight_total, 1) if weight_total else 0.0
        weak_students.append(
            WeakStudent(
                student_id=sid,
                student_name=student.name if student else "?",
                subject_name=subject_name,
                score=overall,
            )
        )
        for r in confident:
            topic_scores.setdefault(r.topic_id, []).append(r.score)

    weak_students.sort(key=lambda w: w.score)

    # Weak topics: average readiness across the group's students, lowest first.
    weak_topics: list[TopicHeat] = []
    for topic_id, scores in topic_scores.items():
        topic = topic_by_id[topic_id]
        avg = round(sum(scores) / len(scores), 1)
        weak_topics.append(
            TopicHeat(
                topic_code=topic.code,
                topic_title=topic.title,
                avg_score=avg,
                student_count=len(scores),
            )
        )
    weak_topics.sort(key=lambda t: t.avg_score)

    # AI agreement rate on finalized submissions in this group.
    #
    # `finalized` alone is deliberate here, and is the one place that does not
    # use SETTLED_STATUSES (AV-80). This measures how often a *tutor* agreed
    # with the AI, so it counts only submissions the tutor pressed finalize
    # on — and, within one, only the questions the tutor actually decided.
    # A submission finalizes once its low-confidence questions are decided,
    # but confidently auto-marked ones ride along unchanged: those rows still
    # carry `QuestionMark.auto_finalized = True` even though the *submission*
    # is now `finalized`, so they are excluded here too. Without that, a
    # question the AI marked and nobody ever looked at would count as the AI
    # agreeing with itself and drive the rate toward 100% as auto-finalize
    # coverage grows — the same reason an `auto_finalized` *submission* is
    # excluded outright by not being in SETTLED_STATUSES here. Do not "fix"
    # this filter to match the other call sites.
    marks = (
        await db.scalars(
            select(QuestionMark)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(
                Assignment.group_id == group_id,
                Submission.status == SubmissionStatus.finalized,
                QuestionMark.auto_finalized.is_(False),
            )
        )
    ).all()
    scored = [m for m in marks if m.ai_marks is not None and m.final_marks is not None]
    agreed = sum(1 for m in scored if m.ai_marks == m.final_marks)
    agreement = AgreementStats(
        total_marked_questions=len(scored),
        ai_agreed=agreed,
        agreement_rate=round(agreed / len(scored) * 100, 1) if scored else None,
    )

    return TutorAnalytics(
        weak_students=weak_students[:10],
        weak_topics=weak_topics[:10],
        agreement=agreement,
    )
