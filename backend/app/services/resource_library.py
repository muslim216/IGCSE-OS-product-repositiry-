from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupResource, ResourceKind


async def tutor_shared_resources(
    db: AsyncSession, *, tutor_id: int, organization_id: int, kind: ResourceKind | None = None
) -> list[tuple[GroupResource, str]]:
    """Every file and recording shared with the tutor's own classes, newest first.

    One joined query rather than a per-class loop, so the cost does not grow with
    the number of classes (PERF-1). The organization binds alongside ownership
    (SEC-7), as it does on the per-class routes. `id` breaks a created_at tie so
    the order is stable.
    """
    query = (
        select(GroupResource, Group.name)
        .join(Group, Group.id == GroupResource.group_id)
        .where(Group.tutor_id == tutor_id, Group.organization_id == organization_id)
        .order_by(GroupResource.created_at.desc(), GroupResource.id.desc())
    )
    if kind is not None:
        query = query.where(GroupResource.kind == kind)
    return [(r, name) for r, name in (await db.execute(query)).all()]
