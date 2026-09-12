"""Turn finalized academic events into readiness evidence rows.

Only finalized work — homework, past papers and mocks — plus entered
assessment/observation data becomes evidence; nothing provisional (like an AI
draft) ever influences readiness.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Evidence,
    QuestionMark,
    Submission,
)
from app.services.submission_kind import kind_of


async def build_homework_evidence(session: AsyncSession, submission: Submission) -> set[int]:
    """Create one evidence row per topic covered by a settled submission,
    aggregating marks across all questions tagged with that topic. Returns the
    set of affected topic ids. Idempotent: replaces prior evidence for this
    submission if it is re-finalized.

    Handles every kind of submission — homework, past paper and mock — since all
    three are Submission/QuestionMark rows. Which question and topic tables to
    read, and which evidence source the marks become, come from
    submission_kind.kind_of rather than from a branch written here: a past
    paper's marks weigh more than homework's and a mock's more again (see
    readiness.SOURCE_WEIGHTS)."""
    kind = kind_of(submission)
    question_model = kind.question_model
    rows: Sequence[Any] = (
        await session.execute(
            select(QuestionMark, question_model)
            .join(question_model, question_model.id == getattr(QuestionMark, kind.mark_fk))
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
                select(kind.topic_model.topic_id).where(kind.topic_model.question_id == question.id)
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
                source_type=kind.evidence_source,
                score_pct=round(got / mx * 100, 1),
                max_marks=mx,
                occurred_at=occurred,
                source_ref=source_ref,
            )
        )
    return set(totals.keys())
