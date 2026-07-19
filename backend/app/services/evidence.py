"""Turn finalized academic events into readiness evidence rows.

Only finalized homework and entered assessment/observation data become
evidence — nothing provisional (like an AI draft) ever influences readiness.
"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssignmentQuestion,
    Evidence,
    EvidenceSource,
    QuestionMark,
    QuestionTopic,
    Submission,
)


async def build_homework_evidence(session: AsyncSession, submission: Submission) -> set[int]:
    """Create one evidence row per topic covered by a finalized submission,
    aggregating marks across all questions tagged with that topic. Returns the
    set of affected topic ids. Idempotent: replaces prior evidence for this
    submission if it is re-finalized."""
    rows = (
        await session.execute(
            select(QuestionMark, AssignmentQuestion)
            .join(AssignmentQuestion, AssignmentQuestion.id == QuestionMark.question_id)
            .where(QuestionMark.submission_id == submission.id)
        )
    ).all()

    # topic_id -> [got_marks, max_marks]
    totals: dict[int, list[int]] = {}
    for mark, question in rows:
        if mark.final_marks is None:
            continue
        topic_ids = (
            await session.scalars(
                select(QuestionTopic.topic_id).where(QuestionTopic.question_id == question.id)
            )
        ).all()
        for topic_id in topic_ids:
            bucket = totals.setdefault(topic_id, [0, 0])
            bucket[0] += mark.final_marks
            bucket[1] += question.max_marks

    source_ref = f"submission:{submission.id}"
    await session.execute(delete(Evidence).where(Evidence.source_ref == source_ref))

    occurred = submission.finalized_at or datetime.now(timezone.utc)
    for topic_id, (got, mx) in totals.items():
        if mx <= 0:
            continue
        session.add(
            Evidence(
                student_id=submission.student_id,
                topic_id=topic_id,
                source_type=EvidenceSource.homework,
                score_pct=round(got / mx * 100, 1),
                max_marks=mx,
                occurred_at=occurred,
                source_ref=source_ref,
            )
        )
    return set(totals.keys())
