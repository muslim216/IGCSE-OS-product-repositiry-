"""Grade boundaries: the defaults, the editor, and the one source they come from.

Task 2.4 (`AV-11`) removed the second source. There is no
`Subject.grade_boundaries` column any more, so a subject an organization has not
set has **no predicted grade at all** rather than one mapped through a shipped
default — `test_an_unset_subject_has_no_predicted_grade` is the test that pins
that, and `PROD-2` is why it must stay true.

The cross-tenant case still matters, and now for the table alone:
`test_org_a_boundary_edit_does_not_change_org_b_predicted_grades` must fail
against any implementation that stores a subject's boundaries anywhere shared.
"""

import pytest
from sqlalchemy import select

from app.services.grade_boundaries import (
    DEFAULT_BOUNDARIES,
    defaults_for_scale,
    resolve_grade_boundaries,
    set_org_boundaries,
)
from app.services.grades import predict_grade
from tests.factories import subject_defaults


@pytest.fixture
async def other_tutor(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other Tutor", "email": "other@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


async def _org_rows(subject_id: int):
    from app.db import async_session
    from app.models import GradeBoundary

    async with async_session() as session:
        return (
            await session.scalars(
                select(GradeBoundary).where(GradeBoundary.subject_id == subject_id)
            )
        ).all()


# ---- defaults ----


def test_defaults_exist_for_every_shipped_scale():
    """A scale with no published default is not a bug — it reports "no grade
    boundaries set" with the control that fixes it — but the two scales the
    product actually ships must not fall into that hole on day one."""
    for scale in ("9-1", "A*-E"):
        assert defaults_for_scale(scale), scale


def test_defaults_are_ordered_highest_first_with_strictly_falling_cutoffs():
    """predict_grade walks the list top to bottom and returns the first grade
    whose minimum is met. An out-of-order default does not raise — it awards the
    wrong grade to every student on that scale."""
    for scale, bands in DEFAULT_BOUNDARIES.items():
        mins = [b["min"] for b in bands]
        assert all(later < earlier for earlier, later in zip(mins, mins[1:], strict=False)), scale
        assert bands[-1]["min"] == 0.0, f"{scale} must have a floor grade"


def test_defaults_for_an_unknown_scale_are_empty_not_invented():
    """Inventing a split for a scale nobody wrote defaults for would produce
    grades nothing stands behind (PROD-1)."""
    assert defaults_for_scale("Pass/Fail") == []


def test_defaults_are_copied_so_a_caller_cannot_mutate_the_shared_table():
    first = defaults_for_scale("9-1")
    first[0]["min"] = 1.0
    assert defaults_for_scale("9-1")[0]["min"] == 90.0


# ---- the editor ----


async def test_a_boundary_edit_writes_org_scoped_rows(client, tutor, subject):
    resp = await client.put(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries",
        json={"boundaries": [{"grade": "9", "min": 80}, {"grade": "U", "min": 0}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "organization"

    rows = await _org_rows(subject["id"])
    assert {(r.grade_label, r.min_percentage) for r in rows} == {("9", 80.0), ("U", 0.0)}


async def test_org_a_boundary_edit_does_not_change_org_b_predicted_grades(
    client, tutor, other_tutor, subject
):
    """The cross-tenant case. Boundaries are per organization, and one tenant's
    edit must never reach another's grades — the whole reason this table exists
    rather than a column somewhere shared (SEC-8)."""
    from app.db import async_session
    from app.models import Subject, User

    await client.put(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries",
        json={"boundaries": [{"grade": "9", "min": 40}, {"grade": "U", "min": 0}]},
        headers=tutor["headers"],
    )

    async with async_session() as session:
        stored = await session.get(Subject, subject["id"])
        a = await session.get(User, tutor["user"]["id"])
        b = await session.get(User, other_tutor["user"]["id"])
        assert a.organization_id != b.organization_id
        a_bands = await resolve_grade_boundaries(session, a.organization_id, stored)
        b_bands = await resolve_grade_boundaries(session, b.organization_id, stored)

    # 60% is a 9 under A's boundaries. B has none — and gets no grade, not a
    # grade off someone else's list and not one off a shipped default.
    assert predict_grade(60.0, a_bands) == "9"
    assert b_bands == []
    assert predict_grade(60.0, b_bands) == "—"


async def test_an_unset_subject_has_no_predicted_grade(client, tutor, subject):
    """One source since 2.4: nothing stands behind a grade for a subject whose
    organization has not set boundaries, so the product shows none (PROD-2).

    The published split for the scale is *offered* by the editor and counts only
    once the tutor saves it.
    """
    from app.db import async_session
    from app.models import Subject, User

    async with async_session() as session:
        stored = await session.get(Subject, subject["id"])
        user = await session.get(User, tutor["user"]["id"])
        assert await resolve_grade_boundaries(session, user.organization_id, stored) == []

        await set_org_boundaries(
            session,
            user.organization_id,
            subject["id"],
            [{"grade": "A", "min": 70}, {"grade": "U", "min": 0}],
        )
        await session.commit()
        resolved = await resolve_grade_boundaries(session, user.organization_id, stored)

    assert [b["grade"] for b in resolved] == ["A", "U"]


async def test_a_second_edit_replaces_rather_than_accumulates(client, tutor, subject):
    """Merging would leave a band the tutor deleted still in force, with nothing
    on screen to show it."""
    for bands in (
        [{"grade": "9", "min": 90}, {"grade": "7", "min": 70}, {"grade": "U", "min": 0}],
        [{"grade": "9", "min": 85}, {"grade": "U", "min": 0}],
    ):
        resp = await client.put(
            f"/api/v1/subjects/{subject['id']}/grade-boundaries",
            json={"boundaries": bands},
            headers=tutor["headers"],
        )
        assert resp.status_code == 200, resp.text

    body = await client.get(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries", headers=tutor["headers"]
    )
    assert [b["grade"] for b in body.json()["boundaries"]] == ["9", "U"]
    assert len(await _org_rows(subject["id"])) == 2  # not 3 — replaced, not merged


async def test_student_cannot_call_the_endpoint(client, tutor, subject, student):
    """QA-12: a write endpoint touching tenant data ships with its negative case."""
    payload = {"boundaries": [{"grade": "9", "min": 80}, {"grade": "U", "min": 0}]}
    resp = await client.put(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries",
        json=payload,
        headers=student["headers"],
    )
    assert resp.status_code == 403

    anonymous = await client.put(f"/api/v1/subjects/{subject['id']}/grade-boundaries", json=payload)
    assert anonymous.status_code == 401


@pytest.mark.parametrize(
    "bands",
    [
        [{"grade": "9", "min": 50}, {"grade": "U", "min": 80}],  # ascending
        [{"grade": "9", "min": 50}, {"grade": "U", "min": 50}],  # equal cut-offs
        [{"grade": "9", "min": 90}, {"grade": "9", "min": 0}],  # duplicate grade
        [{"grade": "9", "min": 90}],  # a single band is not a scale
    ],
    ids=["ascending", "equal", "duplicate", "one_band"],
)
async def test_an_unusable_boundary_list_is_rejected(client, tutor, subject, bands):
    """Each of these produces a grade nobody intended rather than an error, so
    they are refused at the edge."""
    resp = await client.put(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries",
        json={"boundaries": bands},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422, resp.text


@pytest.fixture
async def blank_subject(tutor):  # depends on `tutor` so the organization exists first:
    # without it pytest may build the subject before any account, and
    # `subject_defaults` would fall back to creating a second organization
    # the tutor is not in — every `owned_subject` lookup then 404s.
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        s = Subject(
            **await subject_defaults(session),
            exam_board="Cambridge",
            code="5070",
            name="Chemistry O Level",
            grade_scale="A*-E",
        )
        session.add(s)
        await session.commit()
        return s.id


async def test_an_unset_subject_offers_the_published_default_as_unconfirmed(
    client, tutor, blank_subject
):
    """PROD-8: a default nobody has confirmed is not presented as the tutor's
    own number."""
    body = (
        await client.get(
            f"/api/v1/subjects/{blank_subject}/grade-boundaries", headers=tutor["headers"]
        )
    ).json()
    assert body["source"] == "none"
    assert [b["grade"] for b in body["boundaries"]] == [
        b["grade"] for b in DEFAULT_BOUNDARIES["A*-E"]
    ]


async def test_reading_an_unset_subject_writes_nothing(client, tutor, blank_subject):
    """A tutor who has not set boundaries must not find them filled in because
    someone opened the page — an offered default that wrote itself would be
    indistinguishable from their own figures (PROD-8)."""
    await client.get(f"/api/v1/subjects/{blank_subject}/grade-boundaries", headers=tutor["headers"])

    assert await _org_rows(blank_subject) == []
