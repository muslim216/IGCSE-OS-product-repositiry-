"""Grade boundaries: the defaults, the editor, and the precedence between them.

The cross-tenant case is the one that matters. `Subject` has no
`organization_id`, so the obvious implementation — let a tutor edit
`Subject.grade_boundaries` — silently moves every other organization's predicted
grades. `test_org_a_boundary_edit_does_not_change_org_b_predicted_grades` is the
test that must fail against that implementation, and it is why the write target
is the org-scoped table.
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
from tests.test_homework import (  # noqa: F401 - shared fixtures
    group,
    student,
    subject,
)

#: What the shared `subject` fixture ships as its global default.
GLOBAL = [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}]


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


async def test_boundary_write_targets_the_org_scoped_table_not_subject(client, tutor, subject):
    from app.db import async_session
    from app.models import Subject

    resp = await client.put(
        f"/api/v1/subjects/{subject['id']}/grade-boundaries",
        json={"boundaries": [{"grade": "9", "min": 80}, {"grade": "U", "min": 0}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "organization"

    async with async_session() as session:
        stored = await session.get(Subject, subject["id"])
        # The global default is untouched — nothing may write it.
        assert stored.grade_boundaries == GLOBAL

    rows = await _org_rows(subject["id"])
    assert {(r.grade_label, r.min_percentage) for r in rows} == {("9", 80.0), ("U", 0.0)}


async def test_org_a_boundary_edit_does_not_change_org_b_predicted_grades(
    client, tutor, other_tutor, subject
):
    """The cross-tenant case. Subjects are global; boundaries must not be."""
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

    # 60% is a 9 under A's edited boundaries and a U under the untouched global
    # default that B still reads.
    assert predict_grade(60.0, a_bands) == "9"
    assert predict_grade(60.0, b_bands) == "U"


async def test_org_override_takes_precedence_over_global_default(client, tutor, subject):
    from app.db import async_session
    from app.models import Subject, User

    async with async_session() as session:
        stored = await session.get(Subject, subject["id"])
        user = await session.get(User, tutor["user"]["id"])
        assert await resolve_grade_boundaries(session, user.organization_id, stored) == GLOBAL

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
    assert len(await _org_rows(subject["id"])) == 2


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
async def blank_subject():
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        s = Subject(
            exam_board="Cambridge",
            code="5070",
            name="Chemistry O Level",
            grade_scale="A*-E",
            grade_boundaries=[],
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
    """A tutor who deliberately left boundaries empty must not find them filled
    in because someone opened the page."""
    from app.db import async_session
    from app.models import Subject

    await client.get(f"/api/v1/subjects/{blank_subject}/grade-boundaries", headers=tutor["headers"])

    async with async_session() as session:
        stored = await session.get(Subject, blank_subject)
        assert stored.grade_boundaries == []
    assert await _org_rows(blank_subject) == []
