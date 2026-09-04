"""A tutor's starting estimate: self-declared, and it gives way.

The decay test is the gate on this change. The seed exists so a class that has
just filled shows a new tutor something on day one rather than three weeks of
"not enough data yet" — and the whole reason that is acceptable is that it
corrects itself. If it stopped decaying, a judgement typed in September would
still be shaping a student's predicted grade in May, and the Readiness Engine
feeds every number in the product.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import EvidenceSource
from app.services.readiness import SOURCE_WEIGHTS, EvidencePoint, compute_topic
from tests.factories import subject_defaults
from tests.test_homework import (  # noqa: F401 - shared fixtures
    group,
    student,
    subject,
)

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


def _point(source: EvidenceSource, score: float, days_ago: int = 0) -> EvidencePoint:
    return EvidencePoint(source=source, score_pct=score, occurred_at=NOW - timedelta(days=days_ago))


def test_every_consumer_of_evidence_source_handles_the_new_member():
    """`native_enum=False` means a new member needs no migration — which also
    means nothing forces an audit of the code that switches on it (DB-5,
    ADR-0007). SOURCE_WEIGHTS is the consumer that fails hardest: compute_topic
    indexes it directly, so a member missing here is a KeyError on the readiness
    path rather than a wrong number."""
    assert set(SOURCE_WEIGHTS) == set(EvidenceSource)


def test_a_tutors_estimate_is_worth_less_than_any_marked_work():
    """It is the only source that is not a mark on a piece of work."""
    estimate = SOURCE_WEIGHTS[EvidenceSource.tutor_estimate]
    assert all(
        estimate < weight
        for source, weight in SOURCE_WEIGHTS.items()
        if source is not EvidenceSource.tutor_estimate
    )


def test_a_seed_alone_carries_the_topic():
    """Before anything is marked the estimate is the whole answer — otherwise
    there was no point entering it."""
    result = compute_topic([_point(EvidenceSource.tutor_estimate, 40.0)], NOW)
    assert result.score == 40.0


def test_seeded_source_decays_against_marked_evidence():
    """The gate. Each marked piece pushes the seed further out of the answer,
    with no passage of time involved — same day, same seed, more marked work.

    Time decay alone does not do this: the half-life discounts a seed and a real
    mark equally, so without this the first impression keeps its full *relative*
    weight for as long as the topic is quiet.
    """
    seed = _point(EvidenceSource.tutor_estimate, 0.0)
    marked = [_point(EvidenceSource.homework, 100.0) for _ in range(3)]

    scores = [compute_topic([seed, *marked[:n]], NOW).score for n in range(1, 4)]
    # Strictly rising towards the marked evidence as more of it arrives.
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]
    # And by the third piece the seed is worth a quarter of its own weight, so
    # the answer is within a few points of the marked work alone.
    assert scores[-1] > 95.0


def test_the_seed_is_never_deleted_only_outweighed():
    """The row is the record of what a score was built from, and PROD-1 needs it
    to stay readable. Outweighing it is the mechanism; deleting it would be the
    other option and it loses the audit trail."""
    seed = _point(EvidenceSource.tutor_estimate, 0.0)
    marked = [_point(EvidenceSource.homework, 100.0) for _ in range(5)]
    result = compute_topic([seed, *marked], NOW)
    assert result.evidence_count == 6
    assert result.score < 100.0  # still contributing, just barely


def test_time_decay_still_applies_to_the_seed():
    """The two mechanisms are independent: an estimate typed a year ago is both
    stale and outweighed."""
    fresh = compute_topic([_point(EvidenceSource.tutor_estimate, 80.0)], NOW)
    assert fresh.score == 80.0
    old = compute_topic(
        [
            _point(EvidenceSource.tutor_estimate, 80.0, days_ago=365),
            _point(EvidenceSource.homework, 40.0),
        ],
        NOW,
    )
    assert old.score < 45.0


# ---- the entry surface ----


async def test_a_tutor_can_seed_a_student_they_teach(client, tutor, student, subject):
    from app.db import async_session
    from app.models import Evidence

    resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={"topics": [{"topic_id": subject["topic1"], "score_pct": 55}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text

    async with async_session() as session:
        from sqlalchemy import select

        rows = (await session.scalars(select(Evidence))).all()
    assert len(rows) == 1
    assert rows[0].source_type is EvidenceSource.tutor_estimate
    assert rows[0].score_pct == 55.0
    # PROD-8: labelled as self-declared at the point it is written, so every
    # surface that renders the label says so without having to know the rule.
    assert "self-declared" in rows[0].label


async def test_re_seeding_replaces_rather_than_stacking(client, tutor, student, subject):
    """This is the tutor's current opinion, not a history of their opinions.
    Stacking would let one topic be seeded into a score by repetition."""
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Evidence

    for score in (30, 70):
        resp = await client.post(
            f"/api/v1/students/{student['user']['id']}/seed-readiness",
            json={"topics": [{"topic_id": subject["topic1"], "score_pct": score}]},
            headers=tutor["headers"],
        )
        assert resp.status_code == 201, resp.text

    async with async_session() as session:
        rows = (await session.scalars(select(Evidence))).all()
    assert len(rows) == 1
    assert rows[0].score_pct == 70.0


async def test_a_tutor_cannot_seed_a_student_they_do_not_teach(client, student, subject):
    """QA-12. 404 rather than 403 — a tutor may not learn that this student
    exists (API-7 / SEC-9)."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}

    denied = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={"topics": [{"topic_id": subject["topic1"], "score_pct": 55}]},
        headers=other,
    )
    assert denied.status_code == 404


async def test_a_tutor_cannot_seed_a_topic_from_a_subject_they_do_not_teach(
    client, tutor, student, subject
):
    """The authorization that matters. Topics are global, so verifying the tutor
    teaches the student *somewhere* is not enough — a tutor teaching Sara
    Chemistry must not be able to inject evidence onto her Physics record (Qodo).
    Every topic's subject is checked against what this tutor teaches this
    student; a foreign one is 404 (not 403 — a global key must not confirm what
    it points at across the boundary), and nothing is written.
    """
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Evidence, Subject, Topic

    async with async_session() as session:
        other = Subject(
            **await subject_defaults(session),
            exam_board="Cambridge",
            code="5054",
            name="Physics",
            grade_scale="A*-E",
            grade_boundaries=[{"grade": "A*", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(other)
        await session.flush()
        foreign = Topic(subject_id=other.id, code="P1", title="Forces")
        session.add(foreign)
        await session.commit()
        foreign_topic_id = foreign.id

    resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={"topics": [{"topic_id": foreign_topic_id, "score_pct": 80}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404

    # A payload mixing a taught topic with a foreign one is rejected whole — the
    # taught one must not slip through.
    mixed = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={
            "topics": [
                {"topic_id": subject["topic1"], "score_pct": 55},
                {"topic_id": foreign_topic_id, "score_pct": 80},
            ]
        },
        headers=tutor["headers"],
    )
    assert mixed.status_code == 404

    async with async_session() as session:
        assert (await session.scalars(select(Evidence))).all() == []


async def test_a_student_cannot_seed_themselves(client, student, subject):
    """The whole point is that this is the tutor's judgement. A student writing
    it would be self-reported attainment feeding their own predicted grade."""
    resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={"topics": [{"topic_id": subject["topic1"], "score_pct": 99}]},
        headers=student["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("score", [-1, 101])
async def test_an_out_of_range_estimate_is_rejected(client, tutor, student, subject, score):
    resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/seed-readiness",
        json={"topics": [{"topic_id": subject["topic1"], "score_pct": score}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
