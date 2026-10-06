"""Hiding what the tutor's home page asks of them (owner decision 2026-10-06).

Tutor-only, and every row belongs to the caller: no id from the path or body
chooses whose dismissals these are (`SEC-7`).
"""

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import DbSession, TutorUser
from app.schemas.dismissals import DismissalsOut
from app.services import dismissals

router = APIRouter(prefix="/me/dismissals", tags=["dismissals"])


@router.get("", response_model=DismissalsOut)
async def list_dismissals(db: DbSession, user: TutorUser) -> DismissalsOut:
    return DismissalsOut(keys=await dismissals.list_keys(db, user))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_dismissals(db: DbSession, user: TutorUser) -> Response:
    await dismissals.restore_all(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(key: str, db: DbSession, user: TutorUser) -> Response:
    try:
        await dismissals.dismiss(db, user, key)
    except dismissals.InvalidKey as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except dismissals.TooManyDismissals as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many hidden items") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def restore(key: str, db: DbSession, user: TutorUser) -> Response:
    await dismissals.restore(db, user, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
