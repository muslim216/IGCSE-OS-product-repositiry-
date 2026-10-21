"""Ending a parent's access to a child.

Every parent read path looks the `ParentLink` row up on each request and nothing
caches it, so deleting the row revokes access at once. The audit row is written
in the same transaction, so a link never disappears unrecorded (`PROD-7`).
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParentLink, ParentLinkRemoval, User
from app.schemas.parent_links import LinkedParentOut


async def linked_parents(db: AsyncSession, student_id: int) -> list[LinkedParentOut]:
    rows = (
        await db.execute(
            select(ParentLink, User)
            .join(User, User.id == ParentLink.parent_id)
            .where(ParentLink.student_id == student_id)
            .order_by(ParentLink.created_at, ParentLink.id)
        )
    ).all()
    return [
        LinkedParentOut(
            id=link.id,
            parent_id=parent.id,
            name=parent.name,
            email=parent.email,
            linked_at=link.created_at,
        )
        for link, parent in rows
    ]


async def remove_link(
    db: AsyncSession,
    *,
    parent_id: int | None = None,
    student_id: int,
    link_id: int | None = None,
    actor: User,
) -> None:
    """Delete the link (by id, or by parent+student) and record who did it.

    The caller has already established that `actor` may act on `student_id`; a
    link that is not that student's is a 404 like any other row they cannot see
    (`API-7`)."""
    q = select(ParentLink).where(ParentLink.student_id == student_id)
    q = (
        q.where(ParentLink.id == link_id)
        if link_id is not None
        else q.where(ParentLink.parent_id == parent_id)
    )
    link = await db.scalar(q)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    student = await db.get(User, student_id)
    assert student is not None  # the caller resolved this student
    db.add(
        ParentLinkRemoval(
            organization_id=student.organization_id,
            link_id=link.id,
            parent_id=link.parent_id,
            student_id=student_id,
            removed_by_id=actor.id,
            removed_by_role=actor.role.value,
        )
    )
    await db.delete(link)
    await db.commit()
