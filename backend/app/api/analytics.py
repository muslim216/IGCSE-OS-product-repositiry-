from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, TutorUser
from app.models import (
    Assignment,
    Group,
    QuestionMark,
    Subject,
    Submission,
    SubmissionStatus,
    UserRole,
)
from app.schemas.readiness import (
    AgreementStats,
    TopicHeat,
    TutorAnalytics,
    WeakStudent,
)
from app.services.class_readiness import class_readiness

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/groups/{group_id}", response_model=TutorAnalytics)
async def group_analytics(group_id: int, db: DbSession, user: TutorUser) -> TutorAnalytics:
    group = await db.get(Group, group_id)
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    subject = await db.get(Subject, group.subject_id)
    subject_name = subject.name if subject else ""

    # One v2 aggregation, shared with the tutor home, the class page and the
    # class cards (decisions 13, 15) — before 5.3a this loop re-read
    # TopicReadiness per student, the query-per-learner shape PERF-1 forbids.
    detail = await class_readiness(db, group_id)
    weak_students = [
        WeakStudent(
            student_id=s.student_id,
            student_name=s.student_name,
            subject_name=subject_name,
            score=s.score,  # non-None: `detail.scored` excludes no-evidence learners
        )
        for s in detail.scored  # already lowest-first
    ]
    weak_topics = [
        TopicHeat(
            topic_code=t.topic_code,
            topic_title=t.topic_title,
            avg_score=t.avg_score,
            student_count=t.student_count,
        )
        for t in detail.topic_means  # already lowest-first
    ]

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
            .join(Assignment, Assignment.work_id == Submission.work_id)
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
