"""Teaching-plan inputs on a class (task 6.2, AV-15).

Tutor-only: a plan and its exam date are never shown to students or parents (AV-19).
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, TutorUser
from app.api.groups import _owned_group
from app.models import Organization, TeachingPlan
from app.schemas.teaching_plan import (
    PlanBreakCreate,
    PlanBreakOut,
    PlanInputsIn,
    PlanInputsOut,
    PlanOverview,
    TimetableDefaultsOut,
)
from app.services import teaching_plan as plans
from app.services.timezones import effective_timezone, now_in

router = APIRouter(prefix="/groups/{group_id}/plan", tags=["teaching-plan"])


def _inputs(plan: TeachingPlan | None) -> PlanInputsOut | None:
    return PlanInputsOut.model_validate(plan) if plan else None


async def _overview(db: DbSession, group_id: int) -> PlanOverview:
    defaults = await plans.timetable_defaults(db, group_id)
    return PlanOverview(
        draft=_inputs(await plans.draft_plan_for_group(db, group_id)),
        accepted=_inputs(await plans.accepted_plan_for_group(db, group_id)),
        timetable_defaults=TimetableDefaultsOut(
            lessons_per_week=defaults.lessons_per_week, lesson_minutes=defaults.lesson_minutes
        ),
    )


@router.get("", response_model=PlanOverview)
async def get_plan(group_id: int, db: DbSession, user: TutorUser) -> PlanOverview:
    group = await _owned_group(db, user, group_id)
    return await _overview(db, group.id)


@router.put("/inputs", response_model=PlanOverview)
async def save_inputs(
    group_id: int, body: PlanInputsIn, db: DbSession, user: TutorUser
) -> PlanOverview:
    group = await _owned_group(db, user, group_id)
    # "In the future" is the tutor's calendar, not the server's.
    org = await db.get(Organization, group.organization_id)
    today = now_in(effective_timezone(user.time_zone, org.timezone if org else None)).date()
    try:
        await plans.save_plan_inputs(
            db,
            # From the class, never from the request (6.1, `PROD-3`).
            organization_id=group.organization_id,
            group_id=group.id,
            today=today,
            **body.model_dump(),
        )
    except plans.PlanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _overview(db, group.id)


@router.post("/breaks", response_model=PlanBreakOut, status_code=status.HTTP_201_CREATED)
async def add_break(
    group_id: int, body: PlanBreakCreate, db: DbSession, user: TutorUser
) -> PlanBreakOut:
    group = await _owned_group(db, user, group_id)
    draft = await plans.draft_plan_for_group(db, group.id)
    if draft is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save the plan inputs before adding breaks")
    try:
        created = await plans.add_break(db, plan=draft, **body.model_dump())
    except plans.PlanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return PlanBreakOut.model_validate(created)


@router.delete("/breaks/{break_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_break(group_id: int, break_id: int, db: DbSession, user: TutorUser) -> None:
    group = await _owned_group(db, user, group_id)
    draft = await plans.draft_plan_for_group(db, group.id)
    # A break on the accepted plan is not deletable here either: that is a re-plan.
    if draft is None or not await plans.remove_break(db, plan=draft, break_id=break_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Break not found")
