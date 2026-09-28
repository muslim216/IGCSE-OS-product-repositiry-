"""Per-subject readiness factor config and per-factor on/off (task 5.4a).

One resolver decides which ReadinessWeights row applies to a (organization,
subject): the subject's own row if one exists, else the account row, else the
built-in defaults — whole-row, never field by field (decision 8). A switched-off
factor is still computed and stored by Layer 1, but synthesis never sees it.
"""

from sqlalchemy import select

from app.db import async_session
from app.models import (
    FactorEvaluation,
    Group,
    GroupMember,
    Job,
    ReadinessFactor,
    ReadinessSnapshot,
    ReadinessWeights,
    Subject,
    User,
    UserRole,
)
from app.services.readiness_config import DEFAULT_WEIGHTS, resolve_readiness_config
from app.services.readiness_v2_ai import (
    SCORE_CONTRADICTION_TOLERANCE,
    ReadinessSynthesis,
    _weighted_reference_score,
    compute_readiness_v2,
)
from tests.factories import other_org_subject, subject_defaults
from tests.test_readiness_api import world  # noqa: F401 - shared fixture

ALL_FACTORS = [f.value for f in ReadinessFactor if f != ReadinessFactor.consistency]


def _body(**overrides) -> dict:
    body = {f"weight_{f}": 1.0 for f in ALL_FACTORS}
    body.update({f"enabled_{f}": True for f in ALL_FACTORS})
    body["half_life_days"] = 45.0
    body.update(overrides)
    return body


async def _tutor_org(session) -> int:
    return await session.scalar(
        select(User.organization_id).where(User.email == "tutor@example.com")
    )


# ---- The resolver ----


async def test_the_resolver_falls_back_to_the_built_in_defaults(client, tutor, world):  # noqa: F811
    async with async_session() as session:
        config = await resolve_readiness_config(
            session, await _tutor_org(session), world["subject_id"]
        )
    assert config.source == "default"
    assert config.weights == DEFAULT_WEIGHTS
    assert config.enabled == frozenset(ReadinessFactor(f) for f in ALL_FACTORS)
    assert config.half_life_days == 45.0


async def test_the_resolver_uses_the_account_row_when_the_subject_has_none(
    client,
    tutor,
    world,  # noqa: F811
):
    async with async_session() as session:
        org = await _tutor_org(session)
        session.add(
            ReadinessWeights(
                organization_id=org,
                tutor_id=tutor["user"]["id"],
                weight_topic_mastery=2.0,
                enabled_mistake_analysis=False,
            )
        )
        await session.commit()
        config = await resolve_readiness_config(session, org, world["subject_id"])
    assert config.source == "account"
    assert config.weights["weight_topic_mastery"] == 2.0
    assert ReadinessFactor.mistake_analysis not in config.enabled


async def test_a_subject_row_replaces_the_account_row_whole(client, tutor, world):  # noqa: F811
    """Decision 8: no per-field inheritance. The account row switches mistake
    analysis off; the subject row leaves it on — so it is on, because every
    value comes from the subject row."""
    async with async_session() as session:
        org = await _tutor_org(session)
        session.add_all(
            [
                ReadinessWeights(
                    organization_id=org,
                    tutor_id=tutor["user"]["id"],
                    weight_topic_mastery=2.0,
                    enabled_mistake_analysis=False,
                    half_life_days=30.0,
                ),
                ReadinessWeights(
                    organization_id=org,
                    subject_id=world["subject_id"],
                    tutor_id=tutor["user"]["id"],
                    weight_topic_mastery=0.5,
                ),
            ]
        )
        await session.commit()
        config = await resolve_readiness_config(session, org, world["subject_id"])
        account = await resolve_readiness_config(session, org, None)
    assert config.source == "subject"
    assert config.weights["weight_topic_mastery"] == 0.5
    assert ReadinessFactor.mistake_analysis in config.enabled
    assert config.half_life_days == 45.0
    assert account.source == "account" and account.weights["weight_topic_mastery"] == 2.0


# ---- Synthesis ----


async def test_a_disabled_factor_is_stored_but_never_reaches_synthesis(
    client,
    tutor,
    world,  # noqa: F811
    monkeypatch,
    fake_ai,
):
    # Two scored factors: the mock scores assessment performance and topic
    # mastery (90%), the seed estimate adds a second, lower topic.
    resp = await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "October Mock",
            "type": "mock",
            "date": "2026-06-15",
            "scores": [
                {
                    "student_id": world["student_id"],
                    "topic_id": world["topic1"],
                    "marks": 18,
                    "max_marks": 20,
                }
            ],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"/api/v1/students/{world['student_id']}/seed-readiness",
        json={"topics": [{"topic_id": world["topic2"], "score_pct": 20}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    resp = await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(enabled_assessment_performance=False),
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text

    prompts: list[str] = []
    inner = fake_ai(
        ReadinessSynthesis(score=0, weak_topics=[], rationale="r", recommended_revision="-")
    )

    async def spy(**kwargs):
        prompts.append(kwargs["content"][0]["text"])
        return await inner(**kwargs)

    monkeypatch.setattr("app.services.readiness_v2_ai.structured_complete", spy)
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )

    assert len(prompts) == 1
    assert "assessment_performance" not in prompts[0]
    assert "topic_mastery" in prompts[0]

    async with async_session() as session:
        snapshot = await session.scalar(select(ReadinessSnapshot))
        rows = (
            await session.scalars(
                select(FactorEvaluation).where(
                    FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id
                )
            )
        ).all()
    # Layer 1 still computed and kept it.
    assessment = [r for r in rows if r.factor == ReadinessFactor.assessment_performance]
    assert len(assessment) == 1 and assessment[0].score is not None

    enabled_rows = [r for r in rows if r.factor != ReadinessFactor.assessment_performance]
    counted = _weighted_reference_score(enabled_rows, DEFAULT_WEIGHTS)
    everything = _weighted_reference_score(rows, DEFAULT_WEIGHTS)
    assert counted is not None and everything is not None
    # Otherwise the assertion below could not tell the two apart.
    assert abs(counted - everything) > 0.5
    # The AI said 0, so the score is clamped to the reference's floor — the
    # reference built without the disabled factor.
    assert snapshot.score == counted - SCORE_CONTRADICTION_TOLERANCE


async def test_disabling_the_only_scored_factor_leaves_no_evidence(
    client,
    tutor,
    world,  # noqa: F811
    monkeypatch,
    fake_ai,
):
    await client.post(
        f"/api/v1/students/{world['student_id']}/seed-readiness",
        json={"topics": [{"topic_id": world["topic1"], "score_pct": 40}]},
        headers=tutor["headers"],
    )
    await client.put(
        "/api/v1/readiness/weights",
        json=_body(enabled_topic_mastery=False, enabled_syllabus_coverage=False),
        headers=tutor["headers"],
    )

    async def must_not_run(**kwargs):
        raise AssertionError("synthesis ran on factors that were all switched off")

    monkeypatch.setattr("app.services.readiness_v2_ai.structured_complete", must_not_run)
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )
        snapshot = await session.scalar(select(ReadinessSnapshot))
    assert snapshot.score is None
    assert snapshot.rationale == "No evidence yet for this subject."


# ---- The settings API ----


async def test_get_reports_the_scope_and_where_its_values_came_from(client, tutor, world):  # noqa: F811
    resp = await client.get(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subject_id"] == world["subject_id"]
    assert body["source"] == "default"
    assert all(body[f"enabled_{f}"] is True for f in ALL_FACTORS)

    await client.put(
        "/api/v1/readiness/weights",
        json=_body(weight_topic_mastery=2.5),
        headers=tutor["headers"],
    )
    body = (
        await client.get(
            f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
            headers=tutor["headers"],
        )
    ).json()
    assert body["source"] == "account" and body["weight_topic_mastery"] == 2.5
    account = (await client.get("/api/v1/readiness/weights", headers=tutor["headers"])).json()
    assert account["subject_id"] is None and account["source"] == "account"


async def test_saving_a_subject_creates_an_override_and_recomputes_that_subject(
    client,
    tutor,
    world,  # noqa: F811
):
    await client.put("/api/v1/readiness/weights", json=_body(), headers=tutor["headers"])
    async with async_session() as session:
        for job in (await session.scalars(select(Job))).all():
            await session.delete(job)
        await session.commit()

    resp = await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(weight_mistake_analysis=0.0, enabled_syllabus_coverage=False),
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "subject" and body["enabled_syllabus_coverage"] is False

    # The account row is untouched.
    account = (await client.get("/api/v1/readiness/weights", headers=tutor["headers"])).json()
    assert account["enabled_syllabus_coverage"] is True
    async with async_session() as session:
        assert len((await session.scalars(select(ReadinessWeights))).all()) == 2
        jobs = (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()
    assert [j.payload for j in jobs] == [
        {"student_id": world["student_id"], "subject_id": world["subject_id"]}
    ]


async def test_saving_every_factor_switched_off_is_refused(client, tutor, world):  # noqa: F811
    resp = await client.put(
        "/api/v1/readiness/weights",
        json=_body(**{f"enabled_{f}": False for f in ALL_FACTORS}),
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
    assert "at least one" in resp.text.lower()


async def test_removing_an_override_falls_back_to_the_account(client, tutor, world):  # noqa: F811
    url = f"/api/v1/readiness/weights?subject_id={world['subject_id']}"
    await client.put(url, json=_body(weight_topic_mastery=3.0), headers=tutor["headers"])

    resp = await client.delete(url, headers=tutor["headers"])
    assert resp.status_code == 204
    body = (await client.get(url, headers=tutor["headers"])).json()
    assert body["source"] == "default" and body["weight_topic_mastery"] == 1.0
    async with async_session() as session:
        assert (await session.scalars(select(ReadinessWeights))).all() == []
        jobs = (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()
    assert {"student_id": world["student_id"], "subject_id": world["subject_id"]} in [
        j.payload for j in jobs
    ]

    # Already gone: nothing to remove.
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 404


async def test_removing_the_account_row_is_not_an_override(client, tutor):
    resp = await client.delete("/api/v1/readiness/weights", headers=tutor["headers"])
    assert resp.status_code == 422


async def test_another_organizations_subject_is_not_found(client, tutor):
    async with async_session() as session:
        rival = await other_org_subject(session)
        await session.commit()
        rival_id = rival.id
    url = f"/api/v1/readiness/weights?subject_id={rival_id}"
    assert (await client.get(url, headers=tutor["headers"])).status_code == 404
    assert (await client.put(url, json=_body(), headers=tutor["headers"])).status_code == 404
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 404
    async with async_session() as session:
        assert (await session.scalars(select(ReadinessWeights))).all() == []


async def test_students_and_parents_cannot_touch_the_config(client, tutor, world):  # noqa: F811
    code = (
        await client.post(
            f"/api/v1/students/{world['student_id']}/parent-code", headers=tutor["headers"]
        )
    ).json()["code"]
    parent = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Parent",
            "email": "parent@example.com",
            "password": "password123",
        },
    )
    assert parent.status_code == 201, parent.text
    parent_headers = {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"}
    url = f"/api/v1/readiness/weights?subject_id={world['subject_id']}"
    for headers in (world["student_headers"], parent_headers):
        assert (await client.get(url, headers=headers)).status_code == 403
        assert (await client.put(url, json=_body(), headers=headers)).status_code == 403
        assert (await client.delete(url, headers=headers)).status_code == 403


async def test_v2_factors_say_whether_they_are_switched_on(
    client,
    tutor,
    world,  # noqa: F811
    monkeypatch,
    fake_ai,
):
    await client.post(
        f"/api/v1/students/{world['student_id']}/seed-readiness",
        json={"topics": [{"topic_id": world["topic1"], "score_pct": 40}]},
        headers=tutor["headers"],
    )
    await client.put(
        f"/api/v1/readiness/weights?subject_id={world['subject_id']}",
        json=_body(enabled_mistake_analysis=False),
        headers=tutor["headers"],
    )
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        fake_ai(
            ReadinessSynthesis(score=40, weak_topics=[], rationale="r", recommended_revision="-")
        ),
    )
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )
    resp = await client.get(
        f"/api/v1/readiness/v2/students/{world['student_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    factors = resp.json()["subjects"][0]["factors"]
    by_factor = {f["factor"]: f["enabled"] for f in factors}
    assert by_factor["mistake_analysis"] is False
    assert by_factor["topic_mastery"] is True


async def _recompute_jobs() -> set[tuple[int, int | None]]:
    async with async_session() as session:
        jobs = (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()
        for job in jobs:
            await session.delete(job)
        await session.commit()
    return {(j.payload["student_id"], j.payload["subject_id"]) for j in jobs}


async def test_a_save_recomputes_the_whole_organization_but_not_other_overrides(
    client,
    tutor,
    world,  # noqa: F811
):
    """The config is the organization's, so a save must reach a colleague's
    students too — they were left on the old config until unrelated evidence
    arrived. And an account save skips a subject with its own override: its
    result cannot change, and each run is an AI call."""
    subject = world["subject_id"]
    async with async_session() as session:
        org = (await session.get(User, world["student_id"])).organization_id
        colleague = User(
            email="colleague@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="Colleague",
            organization_id=org,
        )
        kid = User(
            username="kid02",
            password_hash="x",
            role=UserRole.student,
            name="Kid",
            organization_id=org,
        )
        physics = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add_all([colleague, kid, physics])
        await session.flush()
        for subject_id in (subject, physics.id):
            group = Group(
                organization_id=org, tutor_id=colleague.id, subject_id=subject_id, name="G"
            )
            session.add(group)
            await session.flush()
            session.add(GroupMember(group_id=group.id, student_id=kid.id))
        session.add(
            ReadinessWeights(organization_id=org, subject_id=physics.id, tutor_id=colleague.id)
        )
        await session.commit()
        kid_id, physics_id = kid.id, physics.id
    await _recompute_jobs()

    resp = await client.put("/api/v1/readiness/weights", json=_body(), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    # Physics is absent: it has its own override, which this save did not touch.
    assert await _recompute_jobs() == {(world["student_id"], subject), (kid_id, subject)}

    resp = await client.put(
        f"/api/v1/readiness/weights?subject_id={physics_id}", json=_body(), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert await _recompute_jobs() == {(kid_id, physics_id)}
