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
from sqlalchemy.exc import IntegrityError

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
    # 403 exactly, not "401 or 403". The token is valid and the student is who
    # they say they are; what fails is the `TutorUser` gate, which is the claim
    # this test exists to pin — `tests/test_authorization.py` pins it the same
    # way. Accepting 401 would let a regression that rejects a valid student
    # for the wrong reason pass as though nothing had changed (QA-12, cubic).
    assert r.status_code == 403


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


async def test_saving_the_same_list_twice_is_not_an_error(client, tutor, subject):
    """The plainest thing a client does: send the same payload again.

    A double-clicked save, a retry after a timeout, a form that did not keep
    the ids the first reply carried. With no id to match on, the name is the
    key — the unique constraint says so. Matching only *archived* names sent
    this straight into an IntegrityError the tutor saw as a 500.
    """
    body = {"categories": [{"name": "Careless", "description": "slip"}]}
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json=body,
        headers=tutor["headers"],
    )
    assert first.status_code == 200, first.text

    second = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json=body,
        headers=tutor["headers"],
    )
    assert second.status_code == 200, second.text
    assert [c["name"] for c in second.json()["categories"]] == ["Careless"]

    async with async_session() as session:
        rows = (await session.scalars(select(MistakeCategory))).all()
    assert len(rows) == 1, "the second save reused the row rather than inserting a second"


async def test_a_rename_frees_its_name_for_a_new_category_in_the_same_save(client, tutor, subject):
    """Rename "Careless" to "Slip" and add a fresh "Careless", in one save.

    Legal, and it has to work. SQLAlchemy emits INSERTs before UPDATEs inside a
    single flush, so done naively the new row is inserted while the old one
    still holds the name and the unique constraint rejects it — which is why
    existing rows are settled and flushed before any row is created.
    """
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=tutor["headers"],
    )
    original_id = first.json()["categories"][0]["id"]

    second = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={
            "categories": [
                {"id": original_id, "name": "Slip"},
                {"name": "Careless", "description": "a different thing now"},
            ]
        },
        headers=tutor["headers"],
    )
    assert second.status_code == 200, second.text
    returned = second.json()["categories"]
    # Ordered by id, which is what `save_categories` returns and what
    # `list_categories` returns after it — so a save and the reload that
    # follows agree. It coincides with payload order here only because the
    # renamed row keeps its original, smaller id; do not read this as a promise
    # that the payload's order survives, because it does not (cubic).
    assert [c["name"] for c in returned] == ["Slip", "Careless"], "ordered by id"
    assert returned[0]["id"] == original_id, "the renamed row is the same row"
    assert returned[1]["id"] != original_id, "the reused name is a new row"


async def test_a_description_longer_than_the_bound_is_rejected(client, tutor, subject):
    """Bounded because 4.2 puts it in a prompt — an unbounded description is a
    per-call cost nobody sees coming."""
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless", "description": "x" * 401}]},
        headers=tutor["headers"],
    )
    assert r.status_code == 422


async def test_an_empty_category_list_is_rejected(client, tutor, subject):
    """ "No categories" is not a state the product can express.

    Accepting it archived everything and answered `source="organization"`,
    while the next GET found nothing stored, answered `source="none"` and
    re-offered the published defaults — telling the tutor the edit they had
    just confirmed had not happened, and inviting them to save back the list
    they meant to clear (PROD-8).
    """
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": []},
        headers=tutor["headers"],
    )
    assert r.status_code == 422


async def test_the_same_category_twice_in_one_payload_is_rejected(client, tutor, subject):
    """Two items carrying one id resolve to the same row twice, and the reply
    listed that category twice — the editor renders one category as two, each
    overwriting the other."""
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=tutor["headers"],
    )
    existing_id = first.json()["categories"][0]["id"]

    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={
            "categories": [
                {"id": existing_id, "name": "One"},
                {"id": existing_id, "name": "Two"},
            ]
        },
        headers=tutor["headers"],
    )
    assert r.status_code == 422


async def test_a_name_match_never_takes_a_row_the_payload_already_claimed_by_id(
    client, tutor, subject
):
    """Add "Careless" while renaming the row that currently holds that name.

    Both items point at the same stored row: one by name, one by id. Resolved
    in payload order they both won it — the reply listed that category twice,
    the "Careless" the tutor was adding was never created, and nothing failed.
    The reverse payload order worked, so the outcome depended on which row the
    tutor happened to put first. Ids are settled before names for that reason.
    """
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=tutor["headers"],
    )
    original_id = first.json()["categories"][0]["id"]

    second = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={
            "categories": [
                {"name": "Careless", "description": "a different thing now"},
                {"id": original_id, "name": "Slip"},
            ]
        },
        headers=tutor["headers"],
    )
    assert second.status_code == 200, second.text
    returned = second.json()["categories"]
    assert sorted(c["name"] for c in returned) == ["Careless", "Slip"]
    assert len({c["id"] for c in returned}) == 2, "two categories, not one listed twice"

    async with async_session() as session:
        live = (
            await session.scalars(
                select(MistakeCategory).where(MistakeCategory.archived_at.is_(None))
            )
        ).all()
    assert sorted(row.name for row in live) == ["Careless", "Slip"]


async def test_two_categories_can_swap_names_in_one_save(client, tutor, subject):
    """A tutor deciding the words are the wrong way round.

    Legal, and it has to work. The unique index is checked one statement at a
    time, so writing the first new name lands while the other row still holds
    it — which is why a row whose name is changing is parked on a placeholder
    and flushed before the real names are written.
    """
    first = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}, {"name": "Calculation"}]},
        headers=tutor["headers"],
    )
    careless_id, calculation_id = (c["id"] for c in first.json()["categories"])

    second = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={
            "categories": [
                {"id": careless_id, "name": "Calculation"},
                {"id": calculation_id, "name": "Careless"},
            ]
        },
        headers=tutor["headers"],
    )
    assert second.status_code == 200, second.text
    assert {c["id"]: c["name"] for c in second.json()["categories"]} == {
        careless_id: "Calculation",
        calculation_id: "Careless",
    }

    async with async_session() as session:
        rows = (await session.scalars(select(MistakeCategory))).all()
    assert len(rows) == 2, "a swap renames two rows; it does not create any"
    assert all(row.archived_at is None for row in rows)


async def test_a_description_of_only_whitespace_is_stored_as_absent(client, tutor, subject):
    """Not stored as spaces. 4.2 interpolates descriptions into the tagging
    prompt, where a blank label is worse than no label and the padding is paid
    for on every call."""
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "  Careless  ", "description": "   "}]},
        headers=tutor["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["categories"][0] == {
        "id": r.json()["categories"][0]["id"],
        "name": "Careless",
        "description": None,
    }


async def test_a_name_at_the_bound_with_surrounding_space_is_accepted(client, tutor, subject):
    """60 characters plus a trailing space is a 60-character name. Rejecting it
    asks the tutor to count a character they cannot see, for a space that is
    never stored."""
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": " " + "x" * 60 + " "}]},
        headers=tutor["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["categories"][0]["name"] == "x" * 60


async def test_the_database_holds_one_name_per_subject_whatever_its_case(org_and_subject):
    """The editor and `save_categories` both treat "Careless" and "careless" as
    one category, so the database has to as well.

    It does not bite through `save_categories`, which matches case-insensitively
    itself. It bites when two saves land at once: both find no match, both
    insert, and the editor then reads its own stored list as a duplicate and
    disables saving with nothing the tutor can do from the screen. The index is
    on `lower(name)` so the second insert loses instead.
    """
    organization_id, subject_id = org_and_subject
    async with async_session() as session:
        session.add(
            MistakeCategory(organization_id=organization_id, subject_id=subject_id, name="Careless")
        )
        await session.commit()

    with pytest.raises(IntegrityError):
        async with async_session() as session:
            session.add(
                MistakeCategory(
                    organization_id=organization_id, subject_id=subject_id, name="careless"
                )
            )
            await session.commit()


async def test_a_name_taken_since_the_editor_loaded_is_a_conflict_not_a_500(
    client, tutor, subject, monkeypatch
):
    """Two tutors in one organization saving the same subject at once.

    The later save diffed against a list that had already moved, so a name it
    believed was free is taken by the time it flushes. The later save still
    wins the list — but an edit that is legal and merely late must not reach
    the tutor as a 500 with nothing saying which it was.
    """
    import app.api.mistake_categories as api_module

    async def _taken(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(api_module, "save_categories", _taken)

    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "Careless"}]},
        headers=tutor["headers"],
    )
    assert r.status_code == 409
    assert "changed while you were editing" in r.json()["detail"]
