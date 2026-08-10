"""Coverage counts — how much of a class, and how much of a subject, the
readiness numbers actually speak for.

A status derived from part of a class is a different claim from one derived
from all of it, and PROD-2 forbids the two rendering alike. These assert the
numerator and denominator that let a surface tell them apart.
"""

import pytest

from app.db import async_session
from app.models import (
    GroupMember,
    ReadinessConfidence,
    Subject,
    Topic,
    TopicReadiness,
    User,
)
from app.services.groups import summaries


@pytest.fixture
async def world(client, tutor):
    """A subject with two topics, a class, and one enrolled student."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.flush()
        t1 = Topic(subject_id=subject.id, code="1.1", title="Forces", weight=1.0)
        t2 = Topic(subject_id=subject.id, code="1.2", title="Motion", weight=1.0)
        session.add_all([t1, t2])
        await session.commit()
        subject_id, t1_id, t2_id = subject.id, t1.id, t2.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set A", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()

    return {
        "subject_id": subject_id,
        "topic1": t1_id,
        "topic2": t2_id,
        "group_id": group["id"],
        "student_id": student["id"],
    }


async def add_readiness(student_id, topic_id, confidence, score=70.0):
    async with async_session() as session:
        session.add(
            TopicReadiness(
                student_id=student_id,
                topic_id=topic_id,
                score=score,
                confidence=confidence,
                evidence_count=1,
            )
        )
        await session.commit()


async def summary_for(group_id):
    async with async_session() as session:
        return (await summaries(session, [group_id]))[group_id]


async def test_class_with_no_evidence_reports_zero_of_n(client, tutor, world):
    # One student enrolled, nothing marked. The field is present and zero — an
    # absent field would let a surface skip the sentence entirely.
    result = await summary_for(world["group_id"])
    assert result.member_count == 1
    assert result.students_with_evidence == 0


async def test_confident_evidence_counts_the_student(client, tutor, world):
    await add_readiness(world["student_id"], world["topic1"], ReadinessConfidence.medium)
    result = await summary_for(world["group_id"])
    assert result.students_with_evidence == 1


async def test_low_confidence_does_not_count(client, tutor, world):
    # "Confident" stays medium-or-better, as readiness_summary defines it.
    await add_readiness(world["student_id"], world["topic1"], ReadinessConfidence.low)
    result = await summary_for(world["group_id"])
    assert result.students_with_evidence == 0


async def test_student_with_evidence_on_two_topics_counted_once(client, tutor, world):
    # A student holds one readiness row per topic; without DISTINCT this would
    # report 2 of 1 — more covered students than there are students.
    await add_readiness(world["student_id"], world["topic1"], ReadinessConfidence.high)
    await add_readiness(world["student_id"], world["topic2"], ReadinessConfidence.high)
    result = await summary_for(world["group_id"])
    assert result.students_with_evidence == 1
    assert result.member_count == 1


async def test_student_in_two_groups_not_double_counted(client, tutor, world):
    """The same student enrolled in a second class of the same subject counts
    once in each — coverage is a per-class statement, not a global tally."""
    second = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set B", "subject_id": world["subject_id"]},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        session.add(GroupMember(group_id=second["id"], student_id=world["student_id"]))
        await session.commit()

    await add_readiness(world["student_id"], world["topic1"], ReadinessConfidence.high)
    await add_readiness(world["student_id"], world["topic2"], ReadinessConfidence.high)

    async with async_session() as session:
        both = await summaries(session, [world["group_id"], second["id"]])
    assert both[world["group_id"]].students_with_evidence == 1
    assert both[second["id"]].students_with_evidence == 1


async def test_another_subjects_evidence_does_not_count(client, tutor, world):
    """Evidence in a subject this class does not teach says nothing about it."""
    async with async_session() as session:
        other = Subject(
            exam_board="Edexcel IGCSE",
            code="4BI1",
            name="Biology",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(other)
        await session.flush()
        other_topic = Topic(subject_id=other.id, code="2.1", title="Cells", weight=1.0)
        session.add(other_topic)
        await session.commit()
        other_topic_id = other_topic.id

    await add_readiness(world["student_id"], other_topic_id, ReadinessConfidence.high)
    result = await summary_for(world["group_id"])
    assert result.students_with_evidence == 0


async def test_subject_coverage_counts_topics_with_evidence(client, tutor, world):
    """Per-subject coverage: topics carrying evidence over topics that exist."""
    from app.services.readiness_summary import build_summary

    await add_readiness(world["student_id"], world["topic1"], ReadinessConfidence.high)

    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        summary = await build_summary(session, student, [world["subject_id"]])

    subject = summary.subjects[0]
    assert subject.topics_with_evidence == 1
    assert subject.topic_count == 2


async def test_subject_with_no_evidence_reports_zero_of_n(client, tutor, world):
    from app.services.readiness_summary import build_summary

    async with async_session() as session:
        student = await session.get(User, world["student_id"])
        summary = await build_summary(session, student, [world["subject_id"]])

    subject = summary.subjects[0]
    assert subject.topics_with_evidence == 0
    assert subject.topic_count == 2


async def test_only_the_requested_groups_are_returned(client, tutor, world):
    """A group that exists but was not asked for never appears in the result —
    the counts inherit whatever scoping the caller applied (SEC-7)."""
    other = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set B", "subject_id": world["subject_id"]},
            headers=tutor["headers"],
        )
    ).json()

    async with async_session() as session:
        result = await summaries(session, [world["group_id"]])

    assert set(result) == {world["group_id"]}
    assert other["id"] not in result
