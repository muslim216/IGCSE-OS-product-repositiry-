"""The class narrative's grounding reads the shared class aggregation.

Before the Phase 5 sweep `_class_grounding` looped `build_summary_v2` per learner
and counted how many learners each topic was weak *for* — low-confidence rows
included — while the class brief, Group Analytics and the class page all read
`services/class_readiness` (class means, medium/high confidence, at or below the
tutor's threshold). Two AI paragraphs about one class could name different
topics, and the query count grew with the roster (PERF-1).
"""

from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import (
    FactorConfidence,
    FactorEvaluation,
    Group,
    Narrative,
    NarrativeAudience,
    Organization,
    Topic,
    User,
    UserRole,
)
from app.security import create_access_token, hash_password
from app.services.class_readiness import class_readiness, weak_topic_means
from app.services.narrative import _class_grounding
from tests.factories import make_subject, write_v2_snapshot

HIGH = FactorConfidence.high
LOW = FactorConfidence.low


async def _class(client, tutor) -> dict:
    """A class in a subject with the default 9-1 boundaries and two topics."""
    async with async_session() as session:
        subject = await make_subject(session)
        atoms = Topic(subject_id=subject.id, code="1.3", title="Atoms", weight=1.0)
        bonding = Topic(subject_id=subject.id, code="1.6", title="Bonding", weight=1.0)
        session.add_all([atoms, bonding])
        await session.commit()
        ids = {"subject_id": subject.id, "atoms": atoms.id, "bonding": bonding.id}
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": ids["subject_id"]},
            headers=tutor["headers"],
        )
    ).json()
    return {**ids, "group_id": group["id"]}


async def _learner(client, tutor, world, name, *, score=None, grade=None, topics=None) -> int:
    """Enrol a learner; with `score`/`topics`, write their latest v2 run too."""
    student = (
        await client.post(
            f"/api/v1/groups/{world['group_id']}/students",
            json={"name": name, "username": f"{name.lower()}01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    if score is not None or topics is not None:
        async with async_session() as session:
            await write_v2_snapshot(
                session,
                student_id=student["id"],
                subject_id=world["subject_id"],
                score=score,
                predicted_grade=grade,
                topics=topics or {},
            )
            await session.commit()
    return student["id"]


async def _grounding(world) -> str:
    async with async_session() as session:
        return await _class_grounding(session, await session.get(Group, world["group_id"]))


async def _mark_estimated(student_id: int, topic_id: int) -> None:
    """Make one learner's topic row rest on a tutor's estimate, the way
    readiness_factors.topic_mastery records it."""
    async with async_session() as session:
        row = await session.scalar(
            select(FactorEvaluation).where(
                FactorEvaluation.student_id == student_id, FactorEvaluation.topic_id == topic_id
            )
        )
        row.detail = {"tutor_estimate": {"score_pct": 40.0, "share": 1.0}}
        await session.commit()


async def test_weak_topics_are_the_class_means_the_brief_reads(client, tutor):
    world = await _class(client, tutor)
    await _learner(
        client,
        tutor,
        world,
        "Ada",
        score=40.0,
        grade="3",
        # Bonding is weak for Ada only at confidence `low` — the per-learner
        # count used to list it; the shared class aggregation does not.
        topics={world["atoms"]: (30.0, HIGH), world["bonding"]: (10.0, LOW)},
    )
    await _learner(
        client, tutor, world, "Bo", score=55.0, grade="5", topics={world["atoms"]: (50.0, HIGH)}
    )

    text = await _grounding(world)

    assert "- Atoms (1.3): avg 40.0% across 2 learners" in text
    assert "Bonding" not in text
    assert "weak for" not in text
    # And it is literally the same list the brief / class page / analytics read.
    async with async_session() as session:
        group = await session.get(Group, world["group_id"])
        shared = await weak_topic_means(session, group, await class_readiness(session, group.id))
    assert [t.topic_code for t in shared] == ["1.3"]


async def test_a_topic_above_the_threshold_is_not_flagged(client, tutor):
    world = await _class(client, tutor)
    await _learner(
        client, tutor, world, "Ada", score=90.0, grade="9", topics={world["atoms"]: (90.0, HIGH)}
    )

    text = await _grounding(world)

    assert "Weakest topics across the class:\n(none flagged)" in text
    assert "Class: Chem (Chemistry)" in text


async def test_status_lines_come_from_each_learners_own_snapshot_grade(client, tutor):
    world = await _class(client, tutor)
    await _learner(client, tutor, world, "Top", score=92.0, grade="9")
    await _learner(client, tutor, world, "Mid", score=58.0, grade="5")
    await _learner(client, tutor, world, "Low", score=35.4, grade="3")
    await _learner(client, tutor, world, "Ghost")  # enrolled, no run at all
    await _learner(client, tutor, world, "Blank", topics={})  # latest run found no evidence

    text = await _grounding(world)

    # "On track" is counted out of the learners who HAVE a score. Out of the
    # roster it read "1 of 5" — four learners not on track, when two of them
    # simply have no data (PROD-2). The unscored are said to be unscored.
    assert "Learners with a readiness score: 3 of 5\n" in text
    assert "On track: 1 of 3\n" in text
    assert "Not enough data yet: 2\n" in text
    assert "of 5\nOn track" in text and "Learners on track" not in text
    lower = text.split("Learners with lower readiness:\n")[1]
    assert lower == "- Low: 35% (at_risk)\n- Mid: 58% (needs_attention)"
    assert "Ghost" not in text and "Blank" not in text
    assert "0%" not in text.replace("40.0%", "")


async def test_a_fully_scored_class_has_no_not_enough_data_line(client, tutor):
    world = await _class(client, tutor)
    await _learner(client, tutor, world, "Top", score=92.0, grade="9")

    text = await _grounding(world)

    assert "Learners with a readiness score: 1 of 1\nOn track: 1 of 1\n" in text
    assert "Not enough data yet" not in text
    # Boundaries exist and the one scored learner is on track: a real "(none)".
    assert text.endswith("Learners with lower readiness:\n(none)")


async def test_a_scored_learner_with_no_band_is_not_counted_as_off_track(client, tutor):
    """Boundaries exist but this learner's stored grade is not one of them (a
    snapshot written before the boundaries were): no band, so "On track: 0 of
    1" would call them off track on no evidence (PROD-2)."""
    world = await _class(client, tutor)
    await _learner(client, tutor, world, "Stale", score=92.0, grade="—")
    await _learner(client, tutor, world, "Top", score=95.0, grade="9")

    text = await _grounding(world)

    assert "Learners with a readiness score: 2 of 2\nOn track: 1 of 1\n" in text
    assert "Scored, but no on-track status (grade not in the current boundaries):" in text
    assert text.endswith("- Stale: 92%")
    assert "Learners with lower readiness:\n(none)\n" in text


async def test_no_boundaries_means_no_status_claimed(client, tutor):
    """Without boundaries a stored grade has nothing to stand behind, so nobody
    is called on track or low (PROD-2) — the same rule the class page applies.

    And "nobody is called" has to be said in words. It used to read "Learners
    on track: 0 of 1" and "lower readiness: (none)" for a learner on 92% — two
    fabricated negatives — while the score itself never reached the model."""
    world = await _class(client, tutor)
    await _learner(client, tutor, world, "Top", score=92.0, grade="9")
    est = await _learner(
        client, tutor, world, "Est", score=40.0, grade="3", topics={world["atoms"]: (40.0, LOW)}
    )
    await _mark_estimated(est, world["atoms"])
    async with async_session() as session:
        from app.services.grade_boundaries import set_org_boundaries

        group = await session.get(Group, world["group_id"])
        await set_org_boundaries(session, group.organization_id, group.subject_id, [])
        await session.commit()

    text = await _grounding(world)

    assert "Learners with a readiness score: 2 of 2\n" in text
    assert "No grade boundaries set — on-track status is not available.\n" in text
    assert "On track:" not in text and "on track: 0" not in text.lower()
    assert "lower readiness" not in text and "(none)" not in text
    # The scores still reach the model, unbanded, estimate label intact (PROD-8).
    label = " (includes the tutor's starting estimate, not marked work)"
    assert text.endswith(f"Learner readiness scores:\n- Est: 40%{label}\n- Top: 92%")
    for band in ("on_track", "needs_attention", "at_risk"):
        assert band not in text


async def test_tutor_estimates_are_labelled_per_learner_and_per_topic(client, tutor):
    """PROD-8: an estimate-backed number is never handed to the model as marked
    work — on the learner's line, on the class topic mean, and as a count."""
    world = await _class(client, tutor)
    est = await _learner(
        client, tutor, world, "Est", score=40.0, grade="3", topics={world["atoms"]: (40.0, HIGH)}
    )
    await _learner(
        client, tutor, world, "Real", score=45.0, grade="4", topics={world["atoms"]: (45.0, HIGH)}
    )
    await _mark_estimated(est, world["atoms"])

    text = await _grounding(world)
    label = " (includes the tutor's starting estimate, not marked work)"

    assert "Learners whose readiness includes the tutor's starting estimate: 1\n" in text
    assert f"- Est: 40% (at_risk){label}" in text
    assert "- Real: 45% (at_risk)\n" in text + "\n"
    assert f"- Atoms (1.3): avg 42.5% across 2 learners{label}" in text


async def test_a_low_confidence_estimate_still_labels_the_learner(client, tutor):
    """A seed estimate alone scores a topic at confidence `low`, which the class
    means exclude — but the learner's *score* still rests on it, so the learner
    line and the count must still say so."""
    world = await _class(client, tutor)
    est = await _learner(
        client, tutor, world, "Est", score=40.0, grade="3", topics={world["atoms"]: (40.0, LOW)}
    )
    await _mark_estimated(est, world["atoms"])

    text = await _grounding(world)

    assert "Learners whose readiness includes the tutor's starting estimate: 1\n" in text
    assert "- Est: 40% (at_risk) (includes the tutor's starting estimate, not marked work)" in text
    # The only topic row is low-confidence, so there is no class mean at all —
    # which is not the same claim as "no topic is weak" (PROD-2).
    assert "Weakest topics across the class:\n(not enough confident topic data yet)" in text
    assert "(none flagged)" not in text


async def test_no_estimate_means_no_estimate_line(client, tutor):
    world = await _class(client, tutor)
    await _learner(
        client, tutor, world, "Real", score=45.0, grade="4", topics={world["atoms"]: (45.0, HIGH)}
    )

    assert "estimate" not in await _grounding(world)


async def test_an_empty_class_reads_as_empty(client, tutor):
    world = await _class(client, tutor)

    text = await _grounding(world)

    assert "Learners with a readiness score: 0 of 0\n" in text
    # Nothing to be on track *of*, no topic data, nobody to be low: each said
    # as absent, none as a negative finding (PROD-2).
    assert "On track" not in text and "Not enough data yet" not in text
    assert "(not enough confident topic data yet)" in text
    assert "(none flagged)" not in text
    assert text.endswith("Learners with lower readiness:\n(no learner has a readiness score yet)")


async def test_no_scored_learner_skips_the_estimate_read(client, tutor):
    """With nobody scored the per-learner estimate read has no runs to look in:
    it must not go to the database with an empty IN () (PERF-1)."""
    world = await _class(client, tutor)
    await _learner(client, tutor, world, "Ghost")
    queries: list[str] = []

    def before(conn, cursor, statement, params, context, executemany):
        queries.append(statement)

    async with async_session() as session:
        group = await session.get(Group, world["group_id"])
        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            text = await _class_grounding(session, group)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)

    assert not [q for q in queries if "factor_evaluations" in q]
    assert "Learners with a readiness score: 0 of 1\nNot enough data yet: 1\n" in text


async def test_grounding_query_count_is_flat_in_roster_size(client, tutor):
    """PERF-1: the job shares the API's event loop, and the old loop issued
    ~10 queries per learner."""
    world = await _class(client, tutor)
    await _learner(
        client, tutor, world, "Solo", score=40.0, grade="3", topics={world["atoms"]: (40.0, HIGH)}
    )

    async def count() -> int:
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        async with async_session() as session:
            group = await session.get(Group, world["group_id"])
            event.listen(engine.sync_engine, "before_cursor_execute", before)
            try:
                await _class_grounding(session, group)
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", before)
        return len(queries)

    baseline = await count()
    for i in range(5):
        await _learner(
            client,
            tutor,
            world,
            f"S{i}",
            score=30.0 + i,
            grade="3",
            topics={world["atoms"]: (30.0 + i, HIGH)},
        )
    await _learner(client, tutor, world, "Ghost")
    grown = await count()

    assert grown == baseline, (
        f"query count grew from {baseline} to {grown} as the roster went 1 -> 7; "
        "the class grounding must not fan out per learner"
    )


async def test_an_admin_cannot_read_another_organizations_narratives(client, tutor):
    """SEC-7 negative case: the admin branches in api/narrative.py sit behind an
    organization check, so an admin elsewhere gets the same 404 as anyone."""
    world = await _class(client, tutor)
    student_id = await _learner(client, tutor, world, "Sara")
    async with async_session() as session:
        org_id = (await session.get(Group, world["group_id"])).organization_id
        for audience, target in (
            (NarrativeAudience.tutor_class, {"group_id": world["group_id"]}),
            (NarrativeAudience.parent_student, {"student_id": student_id}),
        ):
            session.add(
                Narrative(
                    organization_id=org_id,
                    audience=audience,
                    text="tenant-private paragraph",
                    prompt_version="v1",
                    model="test-model",
                    **target,
                )
            )
        other = Organization(name="Elsewhere")
        session.add(other)
        await session.flush()
        admin = User(
            email="admin-elsewhere@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            name="Admin",
            organization_id=other.id,
        )
        session.add(admin)
        await session.commit()
        headers = {"Authorization": f"Bearer {create_access_token(admin.id, admin.token_version)}"}

    for url in (
        f"/api/v1/groups/{world['group_id']}/narrative",
        f"/api/v1/students/{student_id}/narrative",
    ):
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 404, url
        assert "tenant-private" not in resp.text
