"""Mistake categories: the service that owns them, and the tutor's editor.

`MistakeCategory` was a five-member enum (`models/readiness_v2.py`) — every
tutor of every subject sorted mistakes the same way, and a tutor who disagreed
had nothing to change. It is now a table, scoped per (organization, subject)
like `GradeBoundary`, with the same "defaults are offered, never written"
discipline as `services/grade_boundaries.py`.

Nothing here, in `services/mistake_categories.py`, or anywhere else may branch
on a category's name — the contents are tutor data.
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import MistakeCategory
from app.services.mistake_categories import (
    DEFAULT_CATEGORIES,
    defaults_for_subject,
    ensure_categories,
    list_categories,
    save_categories,
)
from tests.factories import make_subject, other_org_subject


@pytest.fixture
async def org_and_subject(tutor):
    """An (organization_id, subject_id) pair in the tutor's own organization —
    the scope every mistake category is keyed on (decision 1)."""
    async with async_session() as session:
        subject = await make_subject(session)
        await session.commit()
        return subject.organization_id, subject.id


# ---- the service ----


async def test_defaults_are_offered_not_written(org_and_subject):
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        assert await list_categories(session, org_id, subject_id) == []
    assert defaults_for_subject()

    async with async_session() as session:
        stored = (await session.scalars(select(MistakeCategory))).all()
    assert stored == []  # reading did not persist


async def test_save_archives_what_the_payload_drops(org_and_subject):
    """A category a mistake points at cannot be deleted, so an edit that
    removes it archives it. This is the one place 4.1 diverges from the
    grade-boundary precedent, which replaces by delete-then-insert."""
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        saved = await save_categories(
            session, org_id, subject_id, [{"name": "Careless"}, {"name": "Content gap"}]
        )
        await session.commit()
    keep_id = next(c.id for c in saved if c.name == "Careless")

    async with async_session() as session:
        await save_categories(session, org_id, subject_id, [{"id": keep_id, "name": "Careless"}])
        await session.commit()

    async with async_session() as session:
        live = await list_categories(session, org_id, subject_id)
        assert [c.name for c in live] == ["Careless"]
        gone = await session.scalar(
            select(MistakeCategory).where(MistakeCategory.name == "Content gap")
        )
        assert gone is not None and gone.archived_at is not None


async def test_ensure_categories_writes_the_defaults_once(org_and_subject):
    """4.2's tagging job needs rows to point an FK at, and decision 3 says
    nothing is seeded at subject setup — so the first tagging run is what
    makes the defaults real. Twice must not double them."""
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        first = await ensure_categories(session, org_id, subject_id)
        await session.commit()
    async with async_session() as session:
        second = await ensure_categories(session, org_id, subject_id)
        await session.commit()

    assert [c.id for c in first] == [c.id for c in second]
    assert len(first) == len(DEFAULT_CATEGORIES)


async def test_a_rename_keeps_the_row_so_old_mistakes_follow_it(org_and_subject):
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        saved = await save_categories(session, org_id, subject_id, [{"name": "Careless"}])
        await session.commit()
    original_id = saved[0].id

    async with async_session() as session:
        renamed = await save_categories(
            session, org_id, subject_id, [{"id": original_id, "name": "Slip"}]
        )
        await session.commit()

    assert renamed[0].id == original_id
    assert renamed[0].name == "Slip"


async def test_an_id_from_another_organization_is_not_found(org_and_subject):
    """A foreign id in the payload is not found — never someone else's row
    updated because the id happened to exist (SEC-7)."""
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        foreign = await other_org_subject(session)
        foreign_saved = await save_categories(
            session, foreign.organization_id, foreign.id, [{"name": "Careless"}]
        )
        await session.commit()
        foreign_category_id = foreign_saved[0].id

    async with async_session() as session:
        with pytest.raises(ValueError):
            await save_categories(
                session, org_id, subject_id, [{"id": foreign_category_id, "name": "Careless"}]
            )


# ---- the API ----


async def test_a_student_cannot_write_categories(client, student, subject):
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=student["headers"],
    )
    assert r.status_code in (401, 403)


async def test_another_organizations_subject_is_404_not_403(client, tutor):
    """404, not 403: integer keys are enumerable, and 403 confirms the row
    exists to someone who may not know it does (API-7, SEC-9)."""
    async with async_session() as session:
        foreign = await other_org_subject(session, code="9ZZ9")
        await session.commit()
        foreign_id = foreign.id

    read = await client.get(
        f"/api/v1/subjects/{foreign_id}/mistake-categories", headers=tutor["headers"]
    )
    assert read.status_code == 404

    write = await client.put(
        f"/api/v1/subjects/{foreign_id}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=tutor["headers"],
    )
    assert write.status_code == 404

    async with async_session() as session:
        rows = (
            await session.scalars(
                select(MistakeCategory).where(MistakeCategory.subject_id == foreign_id)
            )
        ).all()
        assert rows == []


async def test_get_offers_defaults_and_says_they_are_not_set(client, tutor, subject):
    r = await client.get(
        f"/api/v1/subjects/{subject['id']}/mistake-categories", headers=tutor["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "none"
    assert len(r.json()["categories"]) == len(DEFAULT_CATEGORIES)
    assert all(c["id"] is None for c in r.json()["categories"])


async def test_put_then_get_reports_the_organizations_own(client, tutor, subject):
    put = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless", "description": "slip"}]},
        headers=tutor["headers"],
    )
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "organization"

    r = await client.get(
        f"/api/v1/subjects/{subject['id']}/mistake-categories", headers=tutor["headers"]
    )
    assert r.json()["source"] == "organization"
    assert [c["name"] for c in r.json()["categories"]] == ["Careless"]


async def test_a_duplicate_name_in_one_payload_is_rejected(client, tutor, subject):
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}, {"name": "careless"}]},
        headers=tutor["headers"],
    )
    assert r.status_code == 422


async def test_dropping_a_category_from_the_payload_archives_it_not_deletes(client, tutor, subject):
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}, {"name": "Content gap"}]},
        headers=tutor["headers"],
    )
    keep_id = next(c["id"] for c in first.json()["categories"] if c["name"] == "Careless")

    second = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"id": keep_id, "name": "Careless"}]},
        headers=tutor["headers"],
    )
    assert [c["name"] for c in second.json()["categories"]] == ["Careless"]

    async with async_session() as session:
        gone = await session.scalar(
            select(MistakeCategory).where(MistakeCategory.name == "Content gap")
        )
        assert gone is not None and gone.archived_at is not None
