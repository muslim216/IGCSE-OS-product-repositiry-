"""Tutor-defined custom criteria (task 5.4b).

A tutor names a criterion ("Exam technique") and hand-scores each student 0-100
on it. Shown beside readiness, never in it: nothing here has a weight, and the
engine reads none of these tables. Unscored is absent (null), never 0
(`PROD-2`); every score edit leaves an append-only audit row (`PROD-7`).
"""

from sqlalchemy import select

from app.db import async_session
from app.models import (
    CustomCriterion,
    CustomCriterionScore,
    CustomCriterionScoreAudit,
    GroupMember,
    Subject,
)
from tests.factories import make_subject, other_org_subject, subject_for_tutor
from tests.test_readiness_api import world  # noqa: F401 - shared fixture

BASE = "/api/v1/custom-criteria"


def _scores_url(student_id: int, criterion_id: int | None = None) -> str:
    url = f"/api/v1/students/{student_id}/custom-criteria"
    return url if criterion_id is None else f"{url}/{criterion_id}"


async def _create(client, headers, **body) -> dict:
    body.setdefault("name", "Exam technique")
    resp = await client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _enroll(client, headers, student_id: int, subject_id: int) -> None:
    resp = await client.post(
        f"/api/v1/students/{student_id}/subjects",
        json={"subject_id": subject_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


async def _audit(student_id: int, criterion_id: int) -> list[tuple[int | None, int | None]]:
    async with async_session() as session:
        rows = (
            await session.scalars(
                select(CustomCriterionScoreAudit)
                .where(
                    CustomCriterionScoreAudit.student_id == student_id,
                    CustomCriterionScoreAudit.criterion_id == criterion_id,
                )
                .order_by(CustomCriterionScoreAudit.id)
            )
        ).all()
    return [(r.old_score, r.new_score) for r in rows]


async def _rival(client) -> dict:
    """A second tenant: its own tutor, subject, group and student."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": "rival@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    async with async_session() as session:
        subject = await subject_for_tutor(session, "rival@example.com")
        await session.commit()
        subject_id = subject.id
    group = (
        await client.post(
            "/api/v1/groups", json={"name": "Rival", "subject_id": subject_id}, headers=headers
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Omar", "username": "omar01", "password": "password123"},
            headers=headers,
        )
    ).json()
    return {
        "headers": headers,
        "subject_id": subject_id,
        "group_id": group["id"],
        "student_id": student["id"],
    }


# ---- Criteria ----


async def test_create_list_and_archive(client, tutor, world):  # noqa: F811
    created = await _create(client, tutor["headers"], description="Uses command words")
    assert created["name"] == "Exam technique"
    assert created["description"] == "Uses command words"
    assert created["subject_id"] is None
    assert created["archived_at"] is None
    assert "weight" not in created
    other = await _create(client, tutor["headers"], name="Confidence")

    listed = (await client.get(BASE, headers=tutor["headers"])).json()
    assert [c["id"] for c in listed] == [created["id"], other["id"]]

    resp = await client.patch(
        f"{BASE}/{created['id']}",
        json={"archived": True, "name": "Exam craft"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is not None
    assert resp.json()["name"] == "Exam craft"

    listed = (await client.get(BASE, headers=tutor["headers"])).json()
    assert [c["id"] for c in listed] == [other["id"]]
    listed = (await client.get(f"{BASE}?include_archived=true", headers=tutor["headers"])).json()
    assert {c["id"] for c in listed} == {created["id"], other["id"]}

    resp = await client.patch(
        f"{BASE}/{created['id']}", json={"archived": False}, headers=tutor["headers"]
    )
    assert resp.json()["archived_at"] is None


async def test_the_subject_cannot_be_changed_after_creation(client, tutor, world):  # noqa: F811
    created = await _create(client, tutor["headers"])
    resp = await client.patch(
        f"{BASE}/{created['id']}",
        json={"subject_id": world["subject_id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_a_name_is_one_line(client, tutor):
    created = await _create(client, tutor["headers"], name="Exam\n# Fake heading\n  technique")
    assert created["name"] == "Exam # Fake heading technique"


async def test_a_blank_name_is_refused(client, tutor):
    assert (
        await client.post(BASE, json={"name": "   "}, headers=tutor["headers"])
    ).status_code == 422
    created = await _create(client, tutor["headers"])
    for null_body in ({"name": None}, {"archived": None}):
        resp = await client.patch(
            f"{BASE}/{created['id']}", json=null_body, headers=tutor["headers"]
        )
        assert resp.status_code == 422, null_body


# ---- Scope ----


async def test_an_all_subject_criterion_applies_to_every_student(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    listed = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert [c["criterion_id"] for c in listed] == [criterion["id"]]


async def test_a_subject_criterion_applies_only_to_enrolled_students(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"], subject_id=world["subject_id"])
    url = _scores_url(world["student_id"])

    assert (await client.get(url, headers=tutor["headers"])).json() == []
    resp = await client.put(
        _scores_url(world["student_id"], criterion["id"]),
        json={"score": 50},
        headers=tutor["headers"],
    )
    assert resp.status_code == 409
    assert "enrolled" in resp.json()["detail"]

    await _enroll(client, tutor["headers"], world["student_id"], world["subject_id"])
    listed = (await client.get(url, headers=tutor["headers"])).json()
    assert [c["criterion_id"] for c in listed] == [criterion["id"]]
    # Two subject-specific criteria can share a name, so each row says which
    # subject it is for; an account-wide one has none to name.
    async with async_session() as session:
        subject_name = (await session.get(Subject, world["subject_id"])).name
    assert listed[0]["subject_name"] == subject_name
    scored = await client.put(
        _scores_url(world["student_id"], criterion["id"]),
        json={"score": 50},
        headers=tutor["headers"],
    )
    assert scored.json()["subject_name"] == subject_name
    everywhere = await _create(client, tutor["headers"], name="Focus")
    listed = (await client.get(url, headers=tutor["headers"])).json()
    assert {c["criterion_id"]: c["subject_name"] for c in listed}[everywhere["id"]] is None


async def test_a_criterion_for_another_subject_does_not_apply(client, tutor, world):  # noqa: F811
    async with async_session() as session:
        physics = await make_subject(session, code="4PH1", name="Physics")
        await session.commit()
        physics_id = physics.id
    await _enroll(client, tutor["headers"], world["student_id"], world["subject_id"])
    await _create(client, tutor["headers"], subject_id=physics_id)
    listed = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert listed == []


# ---- Scores ----


async def test_unscored_is_null_never_zero(client, tutor, world):  # noqa: F811
    await _create(client, tutor["headers"])
    [row] = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert row["score"] is None
    assert row["updated_at"] is None
    assert row["updated_by_id"] is None
    assert row["source"] == "tutor"


async def test_every_score_edit_is_audited(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    sid, cid = world["student_id"], criterion["id"]
    url = _scores_url(sid, cid)

    resp = await client.put(url, json={"score": 60}, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] == 60
    assert body["updated_by_id"] == tutor["user"]["id"]
    assert body["source"] == "tutor"
    assert await _audit(sid, cid) == [(None, 60)]

    await client.put(url, json={"score": 75}, headers=tutor["headers"])
    assert await _audit(sid, cid) == [(None, 60), (60, 75)]

    # The same score again changes nothing, so it records nothing.
    resp = await client.put(url, json={"score": 75}, headers=tutor["headers"])
    assert resp.status_code == 200
    assert await _audit(sid, cid) == [(None, 60), (60, 75)]

    [row] = (await client.get(_scores_url(sid), headers=tutor["headers"])).json()
    assert row["score"] == 75

    assert (await client.delete(url, headers=tutor["headers"])).status_code == 204
    assert await _audit(sid, cid) == [(None, 60), (60, 75), (75, None)]
    [row] = (await client.get(_scores_url(sid), headers=tutor["headers"])).json()
    assert row["score"] is None

    # Clearing what is already clear is a no-op, not a second audit row.
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 204
    assert await _audit(sid, cid) == [(None, 60), (60, 75), (75, None)]


async def test_zero_is_a_score_not_an_absence(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    url = _scores_url(world["student_id"], criterion["id"])
    assert (await client.put(url, json={"score": 0}, headers=tutor["headers"])).status_code == 200
    [row] = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert row["score"] == 0
    assert await _audit(world["student_id"], criterion["id"]) == [(None, 0)]


async def test_a_score_out_of_range_is_refused(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    url = _scores_url(world["student_id"], criterion["id"])
    for bad in (-1, 101, 50.5, None, True, "50"):
        resp = await client.put(url, json={"score": bad}, headers=tutor["headers"])
        assert resp.status_code == 422, bad
    assert await _audit(world["student_id"], criterion["id"]) == []


async def test_an_archived_criterion_cannot_be_scored_but_keeps_its_score(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    url = _scores_url(world["student_id"], criterion["id"])
    await client.put(url, json={"score": 40}, headers=tutor["headers"])
    await client.patch(
        f"{BASE}/{criterion['id']}", json={"archived": True}, headers=tutor["headers"]
    )

    assert (await client.put(url, json={"score": 90}, headers=tutor["headers"])).status_code == 409
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 409
    listed = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert listed == []

    async with async_session() as session:
        kept = await session.scalar(
            select(CustomCriterionScore).where(CustomCriterionScore.criterion_id == criterion["id"])
        )
    assert kept is not None and kept.score == 40

    # Unarchiving brings the score back exactly as it was.
    await client.patch(
        f"{BASE}/{criterion['id']}", json={"archived": False}, headers=tutor["headers"]
    )
    [row] = (await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])).json()
    assert row["score"] == 40


async def test_no_endpoint_edits_or_deletes_an_audit_row(client, tutor, world):  # noqa: F811
    criterion = await _create(client, tutor["headers"])
    url = _scores_url(world["student_id"], criterion["id"])
    await client.put(url, json={"score": 10}, headers=tutor["headers"])
    await client.delete(url, headers=tutor["headers"])
    await client.patch(
        f"{BASE}/{criterion['id']}", json={"archived": True}, headers=tutor["headers"]
    )
    # Clearing the score and archiving the criterion both leave the trail whole.
    assert await _audit(world["student_id"], criterion["id"]) == [(None, 10), (10, None)]


# ---- Negatives (QA-12) ----


async def test_another_organizations_criterion_is_not_found(client, tutor, world):  # noqa: F811
    rival = await _rival(client)
    theirs = await _create(client, rival["headers"], name="Theirs")

    resp = await client.patch(
        f"{BASE}/{theirs['id']}", json={"name": "Mine"}, headers=tutor["headers"]
    )
    assert resp.status_code == 404
    url = _scores_url(world["student_id"], theirs["id"])
    assert (await client.put(url, json={"score": 5}, headers=tutor["headers"])).status_code == 404
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 404
    assert (await client.get(BASE, headers=tutor["headers"])).json() == []
    assert (
        await client.get(_scores_url(world["student_id"]), headers=tutor["headers"])
    ).json() == []
    assert await _audit(world["student_id"], theirs["id"]) == []

    # A criterion that never existed looks exactly the same.
    assert (
        await client.patch(f"{BASE}/999999", json={"name": "x"}, headers=tutor["headers"])
    ).status_code == 404


async def test_another_organizations_subject_is_not_found_on_create(client, tutor):
    async with async_session() as session:
        rival = await other_org_subject(session)
        await session.commit()
        rival_id = rival.id
    resp = await client.post(
        BASE, json={"name": "x", "subject_id": rival_id}, headers=tutor["headers"]
    )
    assert resp.status_code == 404


async def test_a_student_the_tutor_does_not_teach_is_not_found(client, tutor, world):  # noqa: F811
    rival = await _rival(client)
    mine = await _create(client, tutor["headers"])
    url = _scores_url(rival["student_id"], mine["id"])
    assert (
        await client.get(_scores_url(rival["student_id"]), headers=tutor["headers"])
    ).status_code == 404
    assert (await client.put(url, json={"score": 5}, headers=tutor["headers"])).status_code == 404
    assert (await client.delete(url, headers=tutor["headers"])).status_code == 404
    assert await _audit(rival["student_id"], mine["id"]) == []


async def test_a_tutor_sharing_a_student_reads_their_own_criteria_not_the_home_ones(
    client,
    tutor,
    world,  # noqa: F811
):
    """A student homed here also sits in a rival organization's class. The
    rival's tutor may open them — and must be shown the rival's criteria, never
    this organization's criteria and the scores given on them."""
    mine = await _create(client, tutor["headers"], name="Home effort")
    resp = await client.put(
        _scores_url(world["student_id"], mine["id"]), json={"score": 70}, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    rival = await _rival(client)
    await _create(client, rival["headers"], name="Rival effort")
    async with async_session() as session:
        session.add(GroupMember(group_id=rival["group_id"], student_id=world["student_id"]))
        await session.commit()

    async def seen(headers) -> list[tuple[str, int | None]]:
        resp = await client.get(_scores_url(world["student_id"]), headers=headers)
        assert resp.status_code == 200, resp.text
        return [(row["name"], row["score"]) for row in resp.json()]

    assert await seen(rival["headers"]) == [("Rival effort", None)]
    assert await seen(tutor["headers"]) == [("Home effort", 70)]
    # The student reads their own organization's, as before.
    assert await seen(world["student_headers"]) == [("Home effort", 70)]


async def test_subject_names_keeps_to_one_organization():
    from app.services.custom_criteria import subject_names

    async with async_session() as session:
        mine = await make_subject(session)
        theirs = await other_org_subject(session, code="9RIV", name="Rival Physics")
        criteria = [CustomCriterion(subject_id=mine.id), CustomCriterion(subject_id=theirs.id)]
        assert await subject_names(session, criteria, mine.organization_id) == {
            mine.id: "Chemistry"
        }


async def _parent_of(client, tutor_headers, student_id: int, email: str) -> dict:
    code = (
        await client.post(f"/api/v1/students/{student_id}/parent-code", headers=tutor_headers)
    ).json()["code"]
    parent = await client.post(
        "/api/v1/auth/register/parent",
        json={"link_code": code, "name": "Parent", "email": email, "password": "password123"},
    )
    assert parent.status_code == 201, parent.text
    return {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"}


async def _second_student(client, tutor_headers, group_id: int) -> dict:
    student = (
        await client.post(
            f"/api/v1/groups/{group_id}/students",
            json={"name": "Lina", "username": "lina01", "password": "password123"},
            headers=tutor_headers,
        )
    ).json()
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "lina01", "password": "password123"}
    )
    return {
        "id": student["id"],
        "headers": {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"},
    }


async def test_a_student_and_their_linked_parent_read_the_scores(client, tutor, world):  # noqa: F811
    """Decision 18: the student and their parent see the tutor's scores."""
    criterion = await _create(client, tutor["headers"])
    score_url = _scores_url(world["student_id"], criterion["id"])
    assert (
        await client.put(score_url, json={"score": 70}, headers=tutor["headers"])
    ).status_code == 200
    parent_headers = await _parent_of(
        client, tutor["headers"], world["student_id"], "parent@example.com"
    )

    for headers in (world["student_headers"], parent_headers):
        resp = await client.get(_scores_url(world["student_id"]), headers=headers)
        assert resp.status_code == 200, resp.text
        [row] = resp.json()
        assert (row["name"], row["score"], row["source"]) == ("Exam technique", 70, "tutor")


async def test_nobody_reads_another_familys_scores(client, tutor, world):  # noqa: F811
    await _create(client, tutor["headers"])
    other = await _second_student(client, tutor["headers"], world["group"]["id"])
    other_parent = await _parent_of(client, tutor["headers"], other["id"], "other@example.com")
    # Another student, and a parent linked only to another student.
    for headers in (other["headers"], other_parent):
        resp = await client.get(_scores_url(world["student_id"]), headers=headers)
        assert resp.status_code == 404, resp.text


async def test_students_and_parents_cannot_manage_or_score(client, tutor, world):  # noqa: F811
    """Reading is widened (decision 18); every write stays tutor-only."""
    criterion = await _create(client, tutor["headers"])
    parent_headers = await _parent_of(
        client, tutor["headers"], world["student_id"], "parent@example.com"
    )
    score_url = _scores_url(world["student_id"], criterion["id"])

    for headers in (world["student_headers"], parent_headers):
        calls = [
            client.get(BASE, headers=headers),
            client.post(BASE, json={"name": "x"}, headers=headers),
            client.patch(f"{BASE}/{criterion['id']}", json={"name": "x"}, headers=headers),
            client.put(score_url, json={"score": 1}, headers=headers),
            client.delete(score_url, headers=headers),
        ]
        for call in calls:
            resp = await call
            assert resp.status_code == 403, resp.request.url
    assert await _audit(world["student_id"], criterion["id"]) == []
