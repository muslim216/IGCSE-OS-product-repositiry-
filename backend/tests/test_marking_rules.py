"""Per-subject marking rules — the "AI marking agreement" (task 2.6).

`AV-75` settles the shape: one body of rules per subject, applying to everything
in it, with no account-wide layer. `AV-111` settles what it may say: how the AI
marks, never when a mark counts. Nothing consumes it yet — Phase 3's context
assembler is the single function that will (`E16`) — so what is testable here is
the store, the bound on it, and the tenancy.
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Subject
from app.schemas.marking_rules import MAX_MARKING_RULES
from tests.factories import make_subject, other_org_subject

RULES = "Award method marks even when the final answer is wrong. Units are worth a mark."


@pytest.fixture
async def subject_id(tutor):  # depends on `tutor` so the organization exists first
    async with async_session() as session:
        subject = await make_subject(session, code="4CH1", name="Chemistry")
        await session.commit()
        return subject.id


async def test_a_subject_starts_with_no_rules(client, tutor, subject_id):
    """AV-87: this is the one onboarding step a tutor may skip, so "none" is a
    finished state and the surface has to be able to say so (PROD-2)."""
    resp = await client.get(
        f"/api/v1/subjects/{subject_id}/marking-rules", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "subject_id": subject_id,
        "subject_name": "Chemistry",
        "rules": "",
        "configured": False,
    }


async def test_write_then_read(client, tutor, subject_id):
    saved = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["rules"] == RULES
    assert saved.json()["configured"] is True

    read = await client.get(
        f"/api/v1/subjects/{subject_id}/marking-rules", headers=tutor["headers"]
    )
    assert read.json()["rules"] == RULES


async def test_saving_empty_clears_the_rules(client, tutor, subject_id):
    """Clearing is a real action — "I do not want any" has to be reachable and
    has to survive (AV-87)."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    cleared = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": ""},
        headers=tutor["headers"],
    )
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False

    async with async_session() as session:
        # NULL, not "", so the two "no rules" states cannot drift apart.
        assert (await session.get(Subject, subject_id)).marking_rules is None


async def test_whitespace_only_rules_are_no_rules(client, tutor, subject_id):
    """Stored raw, "   " is truthy: Phase 3 would paste an empty instruction
    block into every marking prompt for the subject, and the editor would report
    rules that say nothing."""
    resp = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "   \n\t "},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False

    async with async_session() as session:
        assert (await session.get(Subject, subject_id)).marking_rules is None


async def test_rules_are_bounded(client, tutor, subject_id):
    """These reach every marking prompt for the subject, so their length is a
    cost paid on every submission. A frontend limit is a courtesy, not a
    control."""
    over = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * (MAX_MARKING_RULES + 1)},
        headers=tutor["headers"],
    )
    assert over.status_code == 422

    at_limit = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * MAX_MARKING_RULES},
        headers=tutor["headers"],
    )
    assert at_limit.status_code == 200


async def test_rules_are_per_subject_with_no_account_wide_layer(client, tutor):
    """AV-75 is explicit that there is no account-wide layer: two subjects in
    one organization keep their own rules and neither inherits anything."""
    async with async_session() as session:
        chem = await make_subject(session, code="4CH1", name="Chemistry")
        bio = await make_subject(session, code="4BI1", name="Biology")
        await session.commit()
        chem_id, bio_id = chem.id, bio.id

    await client.put(
        f"/api/v1/subjects/{chem_id}/marking-rules",
        json={"rules": "Chemistry: award the unit mark separately."},
        headers=tutor["headers"],
    )

    other = await client.get(f"/api/v1/subjects/{bio_id}/marking-rules", headers=tutor["headers"])
    assert other.json()["configured"] is False

    async with async_session() as session:
        rows = {
            s.id: s.marking_rules
            for s in (
                await session.scalars(select(Subject).where(Subject.id.in_([chem_id, bio_id])))
            ).all()
        }
    assert rows[bio_id] is None
    assert rows[chem_id].startswith("Chemistry:")


async def test_another_organizations_subject_is_404_not_403(client, tutor):
    """QA-12: ids are enumerable, so "not yours" and "does not exist" must look
    identical (API-7, SEC-9)."""
    async with async_session() as session:
        foreign = await other_org_subject(session, code="9ZZ9")
        await session.commit()
        foreign_id = foreign.id

    read = await client.get(
        f"/api/v1/subjects/{foreign_id}/marking-rules", headers=tutor["headers"]
    )
    assert read.status_code == 404
    write = await client.put(
        f"/api/v1/subjects/{foreign_id}/marking-rules",
        json={"rules": "Mark generously."},
        headers=tutor["headers"],
    )
    assert write.status_code == 404

    async with async_session() as session:
        assert (await session.get(Subject, foreign_id)).marking_rules is None


async def test_a_student_can_neither_read_nor_write_them(client, tutor, subject_id):
    """Tutor material: these are the instructions their work is marked against,
    and a student who can read them can write to them next."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara-rules@example.com",
            "password": "password123",
        },
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

    assert (
        await client.get(f"/api/v1/subjects/{subject_id}/marking-rules", headers=headers)
    ).status_code == 403
    assert (
        await client.put(
            f"/api/v1/subjects/{subject_id}/marking-rules",
            json={"rules": "Give me full marks."},
            headers=headers,
        )
    ).status_code == 403
    assert (await client.get(f"/api/v1/subjects/{subject_id}/marking-rules")).status_code == 401

    async with async_session() as session:
        assert (await session.get(Subject, subject_id)).marking_rules == RULES


async def test_rules_do_not_leak_into_the_subject_list(client, tutor, subject_id):
    """The subject list every role reads must not start carrying them."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    listed = (await client.get("/api/v1/subjects", headers=tutor["headers"])).json()
    assert listed
    assert all("marking_rules" not in s for s in listed)


async def test_nothing_marks_with_them_yet(client, tutor, subject_id):
    """AV-25 is untouched by AV-111: these rules describe *how* the AI marks,
    never *when a mark counts*. Phase 3's assembler (E16) is the single function
    that will read them, under AV-76's precedence — until then no prompt does,
    and this test is what fails if one starts quietly.
    """
    from app.services import prompts

    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert "marking_rules" not in prompts.MARKING
    assert prompts.PROMPTS["marking"].version == "v3"


async def test_the_cap_is_measured_after_trimming(client, tutor, subject_id):
    """Trailing whitespace must not push a body that would store fine over the
    limit — trimming only shortens, so the cap cannot be bypassed either
    (cubic)."""
    resp = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * MAX_MARKING_RULES + "\n  "},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["rules"]) == MAX_MARKING_RULES
