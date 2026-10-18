"""A topic id written by a tutor must be one of their own class's subject (`SR-L`).

Topics are per subject and a subject belongs to one organization. Three write
paths only checked that the id existed, so a tutor could tag their work with
another organization's syllabus topic — and the question list echoed its code
and title straight back. Every refusal treats a foreign id as a missing one
(`API-7`, `SEC-8`, `QA-12`).
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Lesson,
    Organization,
    QuestionTopic,
    Topic,
    TutorObservation,
    User,
    UserRole,
)
from app.security import hash_password
from tests.factories import make_subject

API = "/api/v1"


@pytest.fixture
async def foreign_topic(student) -> int:
    """A topic of a subject in an organization the fixture tutor isn't in,
    taught there in a real class the same student sits in — so only "a subject
    *this* tutor teaches the student" can refuse it, not "taught nowhere"."""
    async with async_session() as session:
        org = Organization(name="Org B")
        session.add(org)
        await session.flush()
        other = User(
            email="b@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.tutor,
            name="Tutor B",
            organization_id=org.id,
        )
        session.add(other)
        subject = await make_subject(session, organization_id=org.id, code="4PH1", name="Physics")
        topic = Topic(subject_id=subject.id, code="9.9", title="B-SECRET-TOPIC")
        session.add(topic)
        await session.flush()
        group = Group(organization_id=org.id, tutor_id=other.id, subject_id=subject.id, name="B")
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=student["user"]["id"]))
        await session.commit()
        return topic.id


@pytest.fixture
async def untaught_topic(group) -> int:
    """A topic of another subject in the tutor's own organization, which no
    class of theirs teaches."""
    async with async_session() as session:
        org_id = (await session.get(Group, group["id"])).organization_id
        subject = await make_subject(session, organization_id=org_id, code="4MA1", name="Maths")
        topic = Topic(subject_id=subject.id, code="1.1", title="Number")
        session.add(topic)
        await session.commit()
        return topic.id


@pytest.fixture
async def lesson_id(group) -> int:
    async with async_session() as session:
        g = await session.get(Group, group["id"])
        lesson = Lesson(
            organization_id=g.organization_id,
            group_id=g.id,
            date=date(2026, 9, 1),
            duration_min=60,
        )
        session.add(lesson)
        await session.commit()
        return lesson.id


async def test_a_question_keeps_its_own_topic_and_drops_a_foreign_one(
    client, tutor, subject, published_assignment, foreign_topic
):
    resp = await client.put(
        f"{API}/assignments/{published_assignment['id']}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Atoms",
                "max_marks": 4,
                "has_mark_scheme": False,
                "topic_ids": [subject["topic1"], foreign_topic],
            }
        ],
        headers=tutor["headers"],
    )

    assert resp.status_code == 200, resp.text
    [question] = resp.json()["questions"]
    assert [t["id"] for t in question["topics"]] == [subject["topic1"]]
    assert "B-SECRET-TOPIC" not in resp.text


async def test_a_question_drops_a_topic_of_another_subject_of_the_same_organization(
    client, tutor, subject, published_assignment, untaught_topic
):
    resp = await client.put(
        f"{API}/assignments/{published_assignment['id']}/questions",
        json=[
            {
                "number": "1",
                "text_summary": "Atoms",
                "max_marks": 4,
                "has_mark_scheme": False,
                "topic_ids": [untaught_topic],
            }
        ],
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["questions"][0]["topics"] == []


async def test_a_foreign_tag_written_before_the_check_is_not_shown(
    client, tutor, published_assignment, foreign_topic
):
    question_id = published_assignment["questions"][0]["id"]
    async with async_session() as session:
        session.add(QuestionTopic(question_id=question_id, topic_id=foreign_topic))
        await session.commit()

    resp = await client.get(
        f"{API}/assignments/{published_assignment['id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert "B-SECRET-TOPIC" not in resp.text


async def _observations() -> int:
    async with async_session() as session:
        return len((await session.scalars(select(TutorObservation))).all())


async def test_an_observation_on_a_foreign_topic_is_refused(
    client, tutor, subject, student, foreign_topic, untaught_topic
):
    body = {"student_id": student["user"]["id"], "comment": "Strong on this"}

    for topic_id in (foreign_topic, untaught_topic):
        refused = await client.post(
            f"{API}/observations",
            json=body | {"topic_id": topic_id},
            headers=tutor["headers"],
        )
        assert refused.status_code == 404, refused.text
    assert await _observations() == 0

    own = await client.post(
        f"{API}/observations",
        json=body | {"topic_id": subject["topic1"]},
        headers=tutor["headers"],
    )
    assert own.status_code == 201, own.text


async def test_a_lesson_observation_on_another_subjects_topic_is_refused(
    client, tutor, subject, student, lesson_id, foreign_topic, untaught_topic
):
    body = {"student_id": student["user"]["id"], "body": "Asked good questions"}
    path = f"{API}/lessons/{lesson_id}/observations"

    for topic_id in (foreign_topic, untaught_topic):
        refused = await client.post(
            path, json=body | {"topic_id": topic_id}, headers=tutor["headers"]
        )
        assert refused.status_code == 404, refused.text

    own = await client.post(
        path, json=body | {"topic_id": subject["topic1"]}, headers=tutor["headers"]
    )
    assert own.status_code == 201, own.text
