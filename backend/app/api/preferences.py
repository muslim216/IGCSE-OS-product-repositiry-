from sqlalchemy import select

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import Group, GroupMember, TutorPreferences, User, UserRole
from app.schemas.readiness import PreferencesOut, PreferencesUpdate
from app.workers.jobs import enqueue

router = APIRouter(prefix="/me/preferences", tags=["preferences"])


def _require_tutor(user: User) -> None:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


def _out(p: TutorPreferences | None) -> PreferencesOut:
    if p is None:
        return PreferencesOut(
            weight_mock=1.5, weight_homework=1.0, weight_quiz=0.8, weight_observation=0.5,
            half_life_days=45.0,
        )
    return PreferencesOut(
        weight_mock=p.weight_mock,
        weight_homework=p.weight_homework,
        weight_quiz=p.weight_quiz,
        weight_observation=p.weight_observation,
        half_life_days=p.half_life_days,
    )


@router.get("", response_model=PreferencesOut)
async def get_preferences(db: DbSession, user: CurrentUser) -> PreferencesOut:
    _require_tutor(user)
    prefs = await db.scalar(select(TutorPreferences).where(TutorPreferences.tutor_id == user.id))
    return _out(prefs)


@router.put("", response_model=PreferencesOut)
async def update_preferences(
    body: PreferencesUpdate, db: DbSession, user: CurrentUser
) -> PreferencesOut:
    _require_tutor(user)
    prefs = await db.scalar(select(TutorPreferences).where(TutorPreferences.tutor_id == user.id))
    if prefs is None:
        prefs = TutorPreferences(tutor_id=user.id)
        db.add(prefs)
    prefs.weight_mock = body.weight_mock
    prefs.weight_homework = body.weight_homework
    prefs.weight_quiz = body.weight_quiz
    prefs.weight_observation = body.weight_observation
    prefs.half_life_days = body.half_life_days
    await db.flush()

    student_ids = (
        await db.scalars(
            select(GroupMember.student_id.distinct())
            .join(Group, Group.id == GroupMember.group_id)
            .where(Group.tutor_id == user.id)
        )
    ).all()
    for student_id in student_ids:
        await enqueue(db, "recompute_readiness", {"student_id": student_id})
    await db.commit()
    return _out(prefs)
