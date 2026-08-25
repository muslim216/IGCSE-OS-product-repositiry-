"""Tutor knowledge base.

**Not mounted.** 0.5 (AV-58) hid this surface: the router is no longer included
in main.py, so none of these routes are reachable. The code, its service, its
models and its tables are deliberately kept — this is hidden, not deleted, and
re-mounting the router is all it takes to bring it back.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor
from app.models import KnowledgeEntry, Subject, User, UserRole
from app.schemas.knowledge import KnowledgeEntryCreate, KnowledgeEntryOut, KnowledgeEntryUpdate

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _out(entry: KnowledgeEntry) -> KnowledgeEntryOut:
    return KnowledgeEntryOut(
        id=entry.id,
        kind=entry.kind.value,
        title=entry.title,
        body=entry.body,
        subject_id=entry.subject_id,
        created_at=entry.created_at,
    )


async def _owned_entry(db: DbSession, user: User, entry_id: int) -> KnowledgeEntry:
    assert_tutor(user)
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None or (entry.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge entry not found")
    return entry


@router.post("", response_model=KnowledgeEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: KnowledgeEntryCreate, db: DbSession, user: TutorUser
) -> KnowledgeEntryOut:
    if body.subject_id is not None and await db.get(Subject, body.subject_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    entry = KnowledgeEntry(
        organization_id=user.organization_id,
        tutor_id=user.id,
        subject_id=body.subject_id,
        kind=body.kind,
        title=body.title,
        body=body.body,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _out(entry)


@router.get("", response_model=list[KnowledgeEntryOut])
async def list_entries(
    db: DbSession, user: TutorUser, subject_id: int | None = None
) -> list[KnowledgeEntryOut]:
    query = select(KnowledgeEntry).where(KnowledgeEntry.tutor_id == user.id)
    if subject_id is not None:
        query = query.where(KnowledgeEntry.subject_id == subject_id)
    rows = (await db.scalars(query.order_by(KnowledgeEntry.created_at.desc()))).all()
    return [_out(e) for e in rows]


@router.patch("/{entry_id}", response_model=KnowledgeEntryOut)
async def update_entry(
    entry_id: int, body: KnowledgeEntryUpdate, db: DbSession, user: CurrentUser
) -> KnowledgeEntryOut:
    entry = await _owned_entry(db, user, entry_id)
    if body.subject_id is not None and await db.get(Subject, body.subject_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    entry.kind = body.kind
    entry.title = body.title
    entry.body = body.body
    entry.subject_id = body.subject_id
    await db.commit()
    return _out(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: int, db: DbSession, user: CurrentUser) -> None:
    entry = await _owned_entry(db, user, entry_id)
    await db.delete(entry)
    await db.commit()
