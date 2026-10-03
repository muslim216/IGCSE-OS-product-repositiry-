"""Teaching-plan inputs on a class (task 6.2, AV-15).

Tutor-only: a plan and its exam date are never shown to students or parents (AV-19).
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, TutorUser
from app.api.groups import _owned_group
from app.models import Organization
from app.schemas.teaching_plan import (
    NextLessonChapterOut,
    NextLessonOut,
    NextLessonTopicOut,
    PlanBreakCreate,
    PlanBreakOut,
    PlanInputsIn,
    PlanOverview,
    PlanProgressOut,
    PlanSlotOut,
    PlanSlotPatch,
    TimetableDefaultsOut,
)
from app.services import plan_progress
from app.services import teaching_plan as plans
from app.services.plan_replan import replan
from app.services.timezones import effective_timezone, now_in

router = APIRouter(prefix="/groups/{group_id}/plan", tags=["teaching-plan"])


async def _progress(db: DbSession, user: TutorUser, group_id: int) -> PlanProgressOut:
    today = await plan_progress.tutor_today(db, user)
    found = (
        await plan_progress.class_progress(db, user, today, group_id, own_classes_only=False)
    ).get(group_id)
    p = found[1] if found else plan_progress.NO_PROGRESS
    chapter = p.earliest_missed_chapter
    return PlanProgressOut(
        planned_to_date=p.planned_to_date,
        taught_to_date=p.taught_to_date,
        missed=p.missed,
        earliest_missed_date=p.earliest_missed_date,
        earliest_missed_chapter=(
            NextLessonChapterOut(id=chapter[0], code=chapter[1], title=chapter[2])
            if chapter
            else None
        ),
    )


async def _overview(db: DbSession, user: TutorUser, group_id: int) -> PlanOverview:
    defaults = await plans.timetable_defaults(db, group_id)
    draft = await plans.draft_plan_for_group(db, group_id)
    accepted = await plans.accepted_plan_for_group(db, group_id)
    views = await plans.plan_views(db, [p for p in (draft, accepted) if p is not None])
    return PlanOverview(
        draft=views[draft.id] if draft else None,
        accepted=views[accepted.id] if accepted else None,
        timetable_defaults=TimetableDefaultsOut(
            lessons_per_week=defaults.lessons_per_week, lesson_minutes=defaults.lesson_minutes
        ),
        # Only an accepted plan has a schedule to be behind (never a draft).
        progress=await _progress(db, user, group_id) if accepted else None,
    )


@router.get("", response_model=PlanOverview)
async def get_plan(group_id: int, db: DbSession, user: TutorUser) -> PlanOverview:
    group = await _owned_group(db, user, group_id)
    return await _overview(db, user, group.id)


@router.get("/next-lesson", response_model=NextLessonOut | None)
async def next_lesson(group_id: int, db: DbSession, user: TutorUser) -> NextLessonOut | None:
    """What the accepted plan says to teach next, to pre-fill the add-lesson form
    (task 6.5, AV-17). A suggestion: it creates nothing. `null` when there is no
    accepted plan or no unstarted slot."""
    group = await _owned_group(db, user, group_id)
    nxt = await plans.next_unstarted_slot(db, group.id)
    if nxt is None:
        return None
    return NextLessonOut(
        slot_id=nxt.slot.id,
        scheduled_date=nxt.slot.scheduled_date,
        chapter=NextLessonChapterOut(
            id=nxt.chapter.id, code=nxt.chapter.code, title=nxt.chapter.title
        ),
        topics=[NextLessonTopicOut(id=t.id, code=t.code, title=t.title) for t in nxt.topics],
    )


@router.post("/draft", response_model=PlanOverview, status_code=status.HTTP_202_ACCEPTED)
async def draft_plan(group_id: int, db: DbSession, user: TutorUser) -> PlanOverview:
    """Queue the drafting job (never run in the request, `BE-13`); the tutor
    polls `GET /plan` for `drafting` and the outcome."""
    group = await _owned_group(db, user, group_id)
    try:
        await plans.request_draft(db, group.id)
    except plans.PlanStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _overview(db, user, group.id)


@router.post("/replan", response_model=PlanOverview, status_code=status.HTTP_202_ACCEPTED)
async def replan_plan(group_id: int, db: DbSession, user: TutorUser) -> PlanOverview:
    """Draft a fresh plan from today and wait for the tutor to accept it (task
    6.6). The live plan is untouched; drafting runs as a job (`BE-13`)."""
    group = await _owned_group(db, user, group_id)
    org = await db.get(Organization, group.organization_id)
    today = now_in(effective_timezone(user.time_zone, org.timezone if org else None)).date()
    try:
        await replan(db, group=group, today=today)
    except plans.PlanStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _overview(db, user, group.id)


@router.post("/accept", response_model=PlanOverview)
async def accept_plan(group_id: int, db: DbSession, user: TutorUser) -> PlanOverview:
    group = await _owned_group(db, user, group_id)
    try:
        await plans.accept_plan(db, group=group, user=user)
    except plans.PlanStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _overview(db, user, group.id)


@router.patch("/slots/{slot_id}", response_model=PlanSlotOut)
async def edit_slot(
    group_id: int, slot_id: int, body: PlanSlotPatch, db: DbSession, user: TutorUser
) -> PlanSlotOut:
    group = await _owned_group(db, user, group_id)
    try:
        return await plans.edit_slot(
            db,
            group=group,
            slot_id=slot_id,
            scheduled_date=body.scheduled_date,
            chapter_id=body.chapter_id,
        )
    except plans.PlanSlotNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found") from exc
    except plans.PlanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


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
    return await _overview(db, user, group.id)


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
    except plans.PlanStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
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
