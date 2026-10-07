"""One aggregate endpoint for the tutor's home, and one for the class page.

Before this, the home issued three queries plus one `groupAnalytics` per class,
and each of those looped `db.get(User)` + a TopicReadiness select **per learner**
server-side (api/analytics.py). Eight classes meant eight round trips, each
internally N+1 — the exact shape PERF-1 exists to prevent.

The aggregation itself lives in services/today.py; these handlers are
request/response wiring and authorization only (BE-1, BE-2).

group_analytics is deliberately left in place — the class page's tabs still use
it. It simply stops being on the home's path. Since 5.3a it shares the same
class_readiness() aggregation this module does (services/class_readiness.py),
so it is no longer the per-learner loop the paragraph above describes — the
home, the class page and Group Analytics now read one definition.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, TutorUser
from app.models import Group, UserRole
from app.schemas.teaching_plan import (
    LessonReminderOut,
    NextLessonChapterOut,
    NextLessonTopicOut,
)
from app.schemas.today import ClassOverview, TodayOverview, TodayView
from app.services.lesson_reminders import due_reminders
from app.services.today import build_class_overview, build_today
from app.services.today_overview import build_overview

router = APIRouter(prefix="/today", tags=["today"])


@router.get("", response_model=TodayView)
async def today_view(db: DbSession, user: TutorUser) -> TodayView:
    return await build_today(db, user)


@router.get("/overview", response_model=TodayOverview)
async def today_overview(db: DbSession, user: TutorUser) -> TodayOverview:
    """The Overview's week strip, today's agenda and class cards (coherence B).
    The tutor's own classes only, scoped by the authenticated user (SEC-7)."""
    return await build_overview(db, user)


@router.get("/reminders", response_model=list[LessonReminderOut])
async def lesson_reminders(db: DbSession, user: TutorUser) -> list[LessonReminderOut]:
    """Planned lessons starting within 15 minutes, or under way, with what the plan
    says they cover (task 7.4, AV-120). In-app only; computed at read time."""
    return [
        LessonReminderOut(
            slot_id=r.slot_id,
            group_id=r.group_id,
            group_name=r.group_name,
            scheduled_date=r.scheduled_date,
            start_time=r.start_time,
            starts_at=r.starts_at,
            chapter=NextLessonChapterOut(
                id=r.chapter.id, code=r.chapter.code, title=r.chapter.title
            ),
            topics=[NextLessonTopicOut(id=t.id, code=t.code, title=t.title) for t in r.topics],
        )
        for r in await due_reminders(db, user)
    ]


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
        or group.deleted_at is not None
        or group.organization_id != user.organization_id
        or (group.tutor_id != user.id and user.role != UserRole.admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return await build_class_overview(db, user, group)
