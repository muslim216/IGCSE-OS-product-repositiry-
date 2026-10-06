from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupResource, ResourceKind

#: A hard cap standing in for cursor pagination (API-13): the Library lists the
#: most recent rows and no more, so the response stays bounded (API-12). The order
#: `(created_at desc, id desc)` is already the cursor a later version would page
#: on. The gap, that older material is reachable only through each class's
#: Resources tab, is recorded as a Known Gap.
LIBRARY_RESOURCE_LIMIT = 200


async def tutor_shared_resources(
    db: AsyncSession, *, tutor_id: int, organization_id: int, kind: ResourceKind | None = None
) -> list[tuple[GroupResource, str]]:
    """Every file and recording shared with the tutor's own classes, newest first,
    at most `LIBRARY_RESOURCE_LIMIT` of them.

    One joined query rather than a per-class loop, so the cost does not grow with
    the number of classes (PERF-1). The organization binds alongside ownership
    (SEC-7), as it does on the per-class routes. `id` breaks a created_at tie so
    the order is stable.
    """
    query = (
        select(GroupResource, Group.name)
        .join(Group, Group.id == GroupResource.group_id)
        .where(
            Group.tutor_id == tutor_id,
            Group.organization_id == organization_id,
            Group.deleted_at.is_(None),
        )
        .order_by(GroupResource.created_at.desc(), GroupResource.id.desc())
        .limit(LIBRARY_RESOURCE_LIMIT)
    )
    if kind is not None:
        query = query.where(GroupResource.kind == kind)
    return [(r, name) for r, name in (await db.execute(query)).all()]
