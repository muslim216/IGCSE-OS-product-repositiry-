"""AV-80: the tutor-agreement stat on /analytics/groups/{id} measures how
often a *tutor* agreed with the AI. A finalized submission can still contain
questions the tutor never looked at — the ones the AI marked confidently
enough to auto-finalize — and those must not count, or the rate just measures
the AI agreeing with itself as auto-finalize coverage grows (a review finding
on task 0.1/0.2's PR caught this: the endpoint filtered on submission status
alone and let those rows through)."""

from datetime import datetime, timezone

from app.db import async_session
from app.models import QuestionMark, Submission, SubmissionStatus
from tests.test_homework import (  # noqa: F401 - shared fixtures
    classified,
    fake_extraction,
    group,
    published_assignment,
    student,
    subject,
)


async def test_auto_finalized_questions_in_a_finalized_submission_are_excluded(
    client,
    tutor,
    student,
    published_assignment,  # noqa: F811
):
    q1, q2 = published_assignment["questions"]
    async with async_session() as session:
        submission = Submission(
            assignment_id=published_assignment["id"],
            student_id=student["user"]["id"],
            status=SubmissionStatus.finalized,
            submitted_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
            finalized_by_id=tutor["user"]["id"],
        )
        session.add(submission)
        await session.flush()
        session.add_all(
            [
                # Rode along unchanged: the AI marked it confidently, no tutor
                # ever looked at it, but it now sits inside a finalized
                # submission. Must not count as tutor agreement.
                QuestionMark(
                    submission_id=submission.id,
                    question_id=q1["id"],
                    ai_marks=2,
                    final_marks=2,
                    auto_finalized=True,
                ),
                # The tutor actually reviewed this one and disagreed with the
                # AI. Must count, and must count as a disagreement.
                QuestionMark(
                    submission_id=submission.id,
                    question_id=q2["id"],
                    ai_marks=1,
                    final_marks=0,
                    auto_finalized=False,
                ),
            ]
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/analytics/groups/{published_assignment['group_id']}",
        headers=tutor["headers"],
    )
    assert resp.status_code == 200
    agreement = resp.json()["agreement"]
    assert agreement["total_marked_questions"] == 1
    assert agreement["ai_agreed"] == 0
    assert agreement["agreement_rate"] == 0.0
