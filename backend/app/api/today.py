"""One aggregate endpoint for the tutor's home, and one for the class page.

Before this, the home issued three queries plus one `groupAnalytics` per class,
and each of those looped `db.get(User)` + a TopicReadiness select **per learner**
server-side (api/analytics.py). Eight classes meant eight round trips, each
internally N+1 — the exact shape PERF-1 exists to prevent.

The aggregation itself lives in services/today.py; these handlers are
request/response wiring and authorization only (BE-1, BE-2).

group_analytics is deliberately left in place — the class page's tabs still use
it. It simply stops being on the home's path.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, TutorUser
from app.api.me import my_today_lessons
from app.models import Group, UserRole
from app.schemas.today import ClassOverview, TodayView
from app.services.today import build_class_overview, build_today

router = APIRouter(prefix="/today", tags=["today"])


@router.get("", response_model=TodayView)
async def today_view(db: DbSession, user: TutorUser) -> TodayView:
    # Reuses the today-lessons handler rather than restating its timezone rule:
    # "today" is the organization's today, and one copy of that logic is what
    # keeps the aggregate and the standalone endpoint from drifting apart.
    lessons = await my_today_lessons(db, user)
    return await build_today(db, user, lessons)


@router.get("/classes/{group_id}", response_model=ClassOverview)
async def class_overview(group_id: int, db: DbSession, user: TutorUser) -> ClassOverview:
    group = await db.get(Group, group_id, options=[selectinload(Group.subject)])
    # 404, not 403, for a class the caller may not know exists (API-7 / SEC-9).
    #
    # The organization check binds *before* the role check and applies to admins
    # too. An admin is a tutor with wider reach inside their own organization,
    # not across organizations: without this, `user.role != admin` short-circuits
    # the ownership test and an admin in one organization reads another
    # organization's learners — the exact failure SEC-7 exists to prevent, since
    # the org must come from the authenticated user and never from the fetched row.
    if (
        group is None
        or group.organization_id != user.organization_id
        or (group.tutor_id != user.id and user.role != UserRole.admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return await build_class_overview(db, user, group)
