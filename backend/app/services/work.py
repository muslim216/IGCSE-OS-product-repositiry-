"""Creating the parent row that every piece of assessable work hangs off.

One function, called by all seven places that create an assignment, a past
paper or a mock, because `assessable_work.organization_id` is a *copy* of the
child's tenant and a copy with several writers drifts. Drift here is not a
cosmetic bug: once the cross-kind queries filter the parent instead of ORing
three child columns, a parent row carrying the wrong organization hides a
tutor's work from them, or shows it to the wrong tenant (`SEC-7`, `PROD-4`).

`kind` is passed rather than inferred because nothing in the arguments says
which arm is calling — and a parent whose `kind` disagrees with the table
pointing at it is the one inconsistency no per-table unique constraint can
catch (each `uq_*_work_id` is scoped to its own table).

An assignment is the awkward arm: it carries neither `organization_id` nor
`subject_id` of its own, so its caller reads both off the `Group`. That is the
whole reason this table exists — see `services/submission_kind.py`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssessableWork, WorkKind


async def create_work(
    session: AsyncSession,
    *,
    kind: WorkKind,
    organization_id: int,
    subject_id: int,
    title: str | None,
) -> AssessableWork:
    """Insert the parent row and flush so its `id` is available to the child.

    Flush, not commit: the parent and its child must land in the same
    transaction, or a crash between them leaves a parent nothing points at.
    """
    work = AssessableWork(
        kind=kind,
        organization_id=organization_id,
        subject_id=subject_id,
        title=title,
    )
    session.add(work)
    await session.flush()
    return work
