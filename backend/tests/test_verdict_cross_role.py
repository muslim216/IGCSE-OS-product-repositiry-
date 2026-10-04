"""Coherence C.1: the same student gets the same verdict from the tutor's,
the student's and the parent's endpoints — the core assertion of the task."""

import pytest

from app.db import async_session
from app.models import FactorConfidence, ParentLink, Topic, User, UserRole
from app.services.class_verdicts import class_verdicts
from tests.factories import chemistry_with_topics, write_v2_snapshot

API = "/api/v1"


async def _login(client, identifier, password="password123"):
    r = await client.post(
        f"{API}/auth/login", json={"identifier": identifier, "password": password}
    )
    return {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        subject_id, topic_ids = await chemistry_with_topics(
            session, ["Atomic structure", "Ionic bonding", "Moles"]
        )

    group = (
        await client.post(
            f"{API}/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    sara = (
        await client.post(
            f"{API}/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=sara["id"],
            subject_id=subject_id,
            score=62.0,
            predicted_grade="6",
            topics={
                topic_ids[0]: (85.0, FactorConfidence.high),
                topic_ids[1]: (40.0, FactorConfidence.high),
                topic_ids[2]: (55.0, FactorConfidence.medium),
            },
        )
        await session.commit()

    # A parent linked to Sara, in her organization.
    parent = (
        await client.post(
            f"{API}/auth/register/tutor",
            json={"name": "P", "email": "parent@example.com", "password": "password123"},
        )
    ).json()
    async with async_session() as session:
        parent_user = await session.get(User, parent["user"]["id"])
        parent_user.role = UserRole.parent
        parent_user.organization_id = (await session.get(User, sara["id"])).organization_id
        session.add(ParentLink(parent_id=parent_user.id, student_id=sara["id"]))
        await session.commit()

    return {
        "group_id": group["id"],
        "subject_id": subject_id,
        "student_id": sara["id"],
        "student": await _login(client, "sara01"),
        "parent": await _login(client, "parent@example.com"),
    }


def _verdict(body):
    (subject,) = body["subjects"]
    return subject["verdict"]


async def test_tutor_student_and_parent_get_the_same_verdict(client, tutor, world):
    sid = world["student_id"]
    tutor_v = _verdict(
        (await client.get(f"{API}/readiness/students/{sid}", headers=tutor["headers"])).json()
    )
    student_v = _verdict((await client.get(f"{API}/readiness/me", headers=world["student"])).json())
    parent_v = _verdict(
        (await client.get(f"{API}/readiness/students/{sid}", headers=world["parent"])).json()
    )

    assert tutor_v["status"] == "needs_attention"
    # Weakest first, both below the 60 threshold; Atomic structure (85) is not.
    assert tutor_v["reason_topics"] == ["Ionic bonding", "Moles"]
    assert student_v == tutor_v
    assert parent_v == tutor_v


async def test_class_loader_agrees_with_the_profile_verdict(client, tutor, world):
    profile = _verdict(
        (
            await client.get(
                f"{API}/readiness/students/{world['student_id']}", headers=tutor["headers"]
            )
        ).json()
    )
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models import Group

        group = await session.scalar(
            select(Group).where(Group.id == world["group_id"]).options(selectinload(Group.subject))
        )
        verdicts = await class_verdicts(session, group)
    v = verdicts[world["student_id"]]
    assert (v.status, v.reason_topics, v.next_step) == (
        profile["status"],
        profile["reason_topics"],
        profile["next_step"],
    )


async def test_deleted_topics_do_not_take_weak_topic_places(client, tutor, world):
    """Rows for deleted topics are dropped before the weak-topic cap, so the
    class loader names the same topics as the profile."""
    from sqlalchemy import delete, select
    from sqlalchemy.orm import selectinload

    from app.models import Group

    async with async_session() as session:
        extra = [
            Topic(subject_id=world["subject_id"], code=f"x{i}", title=f"Extra {i}", weight=1.0)
            for i in range(4)
        ]
        session.add_all(extra)
        await session.flush()
        base = (
            await session.scalars(select(Topic).where(Topic.subject_id == world["subject_id"]))
        ).all()
        scores = {t.id: (85.0, FactorConfidence.high) for t in base if t.code == "1"}
        scores.update({t.id: (40.0, FactorConfidence.high) for t in base if t.code == "2"})
        scores.update({t.id: (55.0, FactorConfidence.medium) for t in base if t.code == "3"})
        for t, s in zip(extra, (10.0, 20.0, 30.0, 35.0), strict=True):
            scores[t.id] = (s, FactorConfidence.high)
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=62.0,
            predicted_grade="6",
            topics=scores,
        )
        # The three lowest topics are deleted after the run.
        await session.execute(delete(Topic).where(Topic.id.in_([t.id for t in extra[:3]])))
        await session.commit()

    profile = _verdict(
        (
            await client.get(
                f"{API}/readiness/students/{world['student_id']}", headers=tutor["headers"]
            )
        ).json()
    )
    async with async_session() as session:
        group = await session.scalar(
            select(Group).where(Group.id == world["group_id"]).options(selectinload(Group.subject))
        )
        v = (await class_verdicts(session, group))[world["student_id"]]
    assert profile["reason_topics"] == ["Extra 3", "Ionic bonding", "Moles"]
    assert v.reason_topics == profile["reason_topics"]


async def test_no_readiness_yet_is_not_enough_data_for_every_role(client, tutor, world):
    async with async_session() as session:
        from sqlalchemy import delete

        from app.models import ReadinessSnapshot

        await session.execute(delete(ReadinessSnapshot))
        await session.commit()
    sid = world["student_id"]
    for headers, url in (
        (tutor["headers"], f"{API}/readiness/students/{sid}"),
        (world["student"], f"{API}/readiness/me"),
        (world["parent"], f"{API}/readiness/students/{sid}"),
    ):
        v = _verdict((await client.get(url, headers=headers)).json())
        assert v["status"] == "not_enough_data"
        assert v["reason_topics"] == []


async def test_scope_is_unchanged_for_the_verdict(client, world):
    sid = world["student_id"]
    other = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    assert (
        await client.get(f"{API}/readiness/students/{sid}", headers=other_headers)
    ).status_code == 404
    # A parent with no link to this child, and another student, both get a 404.
    async with async_session() as session:
        stranger = await session.get(User, other.json()["user"]["id"])
        stranger.role = UserRole.parent
        await session.commit()
    assert (
        await client.get(f"{API}/readiness/students/{sid}", headers=other_headers)
    ).status_code == 404
