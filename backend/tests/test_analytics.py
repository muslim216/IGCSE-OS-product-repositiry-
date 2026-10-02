"""AV-80: the tutor-agreement stat on /analytics/groups/{id} measures how
often a *tutor* agreed with the AI. A finalized submission can still contain
questions the tutor never looked at — the ones the AI marked confidently
enough to auto-finalize — and those must not count, or the rate just measures
the AI agreeing with itself as auto-finalize coverage grows (a review finding
on task 0.1/0.2's PR caught this: the endpoint filtered on submission status
alone and let those rows through)."""

from datetime import datetime, timezone

from app.db import async_session
from app.models import (
    Assignment,
    FactorConfidence,
    QuestionMark,
    Submission,
    SubmissionStatus,
)
from tests.factories import write_v2_snapshot
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_auto_finalized_questions_in_a_finalized_submission_are_excluded(
    client,
    tutor,
    student,
    published_assignment,  # noqa: F811
):
    q1, q2 = published_assignment["questions"]
    async with async_session() as session:
        assignment = await session.get(Assignment, published_assignment["id"])
        submission = Submission(
            student_id=student["user"]["id"],
            status=SubmissionStatus.finalized,
            submitted_at=datetime.now(timezone.utc),
            finalized_at=datetime.now(timezone.utc),
            finalized_by_id=tutor["user"]["id"],
            work_id=assignment.work_id,
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


# ---- topic_mean_count: how many topics the weak-topic filter was run over ----
#
# `weak_topics` is the class means at or below the threshold, so an empty list
# is ambiguous on its own: nothing weak, or nothing compared. The count is what
# lets the page say which (PROD-2).


async def _topic_snapshot(world, topics) -> None:  # noqa: F811
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=55.0,
            topics=topics,
        )
        await session.commit()


async def _analytics(client, tutor, world) -> dict:  # noqa: F811
    resp = await client.get(
        f"/api/v1/analytics/groups/{world['group']['id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_topic_mean_count_is_zero_with_no_evidence(client, tutor, world):  # noqa: F811
    body = await _analytics(client, tutor, world)
    assert body["weak_topics"] == []
    assert body["topic_mean_count"] == 0


async def test_topic_mean_count_counts_every_class_mean_not_only_weak_ones(client, tutor, world):  # noqa: F811
    await _topic_snapshot(
        world,
        {
            world["topic1"]: (70.0, FactorConfidence.high),
            world["topic2"]: (50.0, FactorConfidence.high),
        },
    )
    body = await _analytics(client, tutor, world)
    assert len(body["weak_topics"]) == 1
    assert body["topic_mean_count"] == 2


async def test_low_confidence_topics_are_not_counted_as_compared(client, tutor, world):  # noqa: F811
    """A scored learner whose only topic rows are low-confidence has no class
    mean: the empty weak list means nothing was compared, not nothing is weak."""
    await _topic_snapshot(world, {world["topic1"]: (30.0, FactorConfidence.low)})
    body = await _analytics(client, tutor, world)
    assert len(body["weak_students"]) == 1
    assert body["weak_topics"] == []
    assert body["topic_mean_count"] == 0
