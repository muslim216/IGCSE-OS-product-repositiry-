"""Where a subject's mistake categories come from — one source, and this module.

**Defaults are offered, never written.** `DEFAULT_CATEGORIES` is what the
editor pre-fills and what `ensure_categories` writes on first use; until one of
those happens this organization has no categories and the table says so. The
same discipline as `services/grade_boundaries.py`, for the same reason: a
published starting point written on a tutor's behalf is indistinguishable from
their own decision afterwards.

**Saving diffs; it does not replace.** Grade boundaries replace by
delete-then-insert, which cannot work here — a category a Mistake row points at
must survive being dropped from the editor, or the mistake loses the word it
was tagged with. Dropped categories are archived: hidden from new tagging and
from the editor, still readable on everything already tagged.

**Nothing here or anywhere else may branch on a category's name.** The contents
are tutor data. Code that reads meaning into them breaks on a rename, and a
rename is a valid edit that fails nothing.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MistakeCategory
from app.models.base import utcnow

# The five members the old enum shipped, kept as the starting point a new
# subject opens with (decision 6) — each with a description written for 4.2's
# tagging prompt to read, not only for the tutor: a bare word like "careless"
# is ambiguous to anything that has not sat in the room.
DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "Misread the question",
        "description": "Answered something the question did not ask — a misread instruction, a missed condition, the wrong quantity.",
    },
    {
        "name": "Content gap",
        "description": "The underlying method or fact was not known, not merely mis-executed.",
    },
    {
        "name": "Careless",
        "description": "The method was right and known; execution slipped — a dropped sign, a copied digit, a skipped line.",
    },
    {
        "name": "Calculation",
        "description": "The approach was correct but the arithmetic or algebra went wrong.",
    },
    {
        "name": "Time management",
        "description": "Left blank, abandoned part-way, or visibly rushed at the end of the paper.",
    },
]


def defaults_for_subject() -> list[dict]:
    """A copy of the published starting list — never the shared list itself,
    so a caller mutating its copy cannot corrupt what the next caller sees."""
    return [dict(item) for item in DEFAULT_CATEGORIES]


async def list_categories(
    session: AsyncSession, organization_id: int, subject_id: int
) -> list[MistakeCategory]:
    """This organization's live categories for the subject, or an empty list.

    Empty means nothing is set — never the defaults. Offering those is the
    router's job, exactly as `resolve_grade_boundaries` leaves `defaults_for_scale`
    to `api/grade_boundaries.py`: a service that quietly hands back a published
    guess as if it were `list_categories`' own answer is what makes a written
    row indistinguishable from an unconfirmed one.
    """
    rows = (
        await session.scalars(
            select(MistakeCategory)
            .where(
                MistakeCategory.organization_id == organization_id,
                MistakeCategory.subject_id == subject_id,
                MistakeCategory.archived_at.is_(None),
            )
            .order_by(MistakeCategory.id)
        )
    ).all()
    return list(rows)


async def save_categories(
    session: AsyncSession, organization_id: int, subject_id: int, items: list[dict]
) -> list[MistakeCategory]:
    """Diff this organization's categories for a subject against `items`.

    Diffs rather than replaces (decision 2) — the one place this diverges from
    `set_org_boundaries`'s delete-then-insert. A category a `Mistake` row
    points at cannot be deleted out from under it, so:
      - an item carrying an `id` updates that row (and un-archives it, in case
        it was previously dropped and is now being brought back by id);
      - an item with no `id` is created, unless it reuses an *archived* row's
        name, in which case that row is revived rather than inserting a
        duplicate the (organization_id, subject_id, name) constraint would
        reject;
      - a live row whose id is absent from the payload is archived, not
        deleted, so mistakes already tagged with it keep reading back.
    """
    existing = {
        row.id: row
        for row in (
            await session.scalars(
                select(MistakeCategory).where(
                    MistakeCategory.organization_id == organization_id,
                    MistakeCategory.subject_id == subject_id,
                )
            )
        ).all()
    }

    kept_ids: set[int] = set()
    result: list[MistakeCategory] = []
    for item in items:
        item_id = item.get("id")
        if item_id is not None:
            row = existing.get(item_id)
            if row is None:
                # An id that is not this organization's own row — never someone
                # else's row updated because the id happened to exist (SEC-7).
                raise ValueError(f"no mistake category {item_id} in this subject")
            row.name = item["name"]
            row.description = item.get("description")
            row.archived_at = None
            kept_ids.add(row.id)
            result.append(row)
            continue

        archived_match = next(
            (r for r in existing.values() if r.name == item["name"] and r.archived_at is not None),
            None,
        )
        if archived_match is not None:
            archived_match.description = item.get("description")
            archived_match.archived_at = None
            kept_ids.add(archived_match.id)
            result.append(archived_match)
            continue

        row = MistakeCategory(
            organization_id=organization_id,
            subject_id=subject_id,
            name=item["name"],
            description=item.get("description"),
        )
        session.add(row)
        await session.flush()
        kept_ids.add(row.id)
        result.append(row)

    now = utcnow()
    for row_id, row in existing.items():
        if row_id not in kept_ids and row.archived_at is None:
            row.archived_at = now

    await session.flush()
    return result


async def ensure_categories(
    session: AsyncSession, organization_id: int, subject_id: int
) -> list[MistakeCategory]:
    """Live rows for this subject, or the published defaults written once.

    The only thing that makes an FK possible under decision 3 (no seed at
    subject setup): 4.2's tagging job needs a category row to point a Mistake
    at, and `save_categories` is not guaranteed to have run yet.
    """
    live = await list_categories(session, organization_id, subject_id)
    if live:
        return live

    # A tutor who archived every category made that choice deliberately —
    # only write the defaults the first time this subject has no categories
    # at all, never to refill a list the tutor emptied on purpose.
    ever_had_any = await session.scalar(
        select(MistakeCategory.id)
        .where(
            MistakeCategory.organization_id == organization_id,
            MistakeCategory.subject_id == subject_id,
        )
        .limit(1)
    )
    if ever_had_any is not None:
        return []

    rows = [
        MistakeCategory(organization_id=organization_id, subject_id=subject_id, **item)
        for item in defaults_for_subject()
    ]
    session.add_all(rows)
    await session.flush()
    return rows
