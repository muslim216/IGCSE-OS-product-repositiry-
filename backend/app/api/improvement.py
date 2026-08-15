"""The improvement tab's one endpoint.

A student reads their own improvement and nobody else's. There is deliberately
no tutor or parent variant: a ranking is shown to the person it is about, on a
surface dedicated to it, and appears on no home surface for any role. A tutor
who wants to know who is improving reads their class page, which is built on
readiness and direction rather than on a league table.

The role gate is in the signature (SEC-11 / BE-17), the subject scope comes from
the authenticated reader (SEC-7 / SEC-8), and the aggregation lives in
services/improvement.py — this file is wiring (BE-1, BE-2).
"""

from fastapi import APIRouter

from app.api.deps import DbSession, StudentUser
from app.api.readiness import visible_subject_ids
from app.schemas.improvement import SubjectImprovement
from app.services.improvement import build_improvement

router = APIRouter(prefix="/improvement", tags=["improvement"])


@router.get("/me", response_model=list[SubjectImprovement])
async def my_improvement(db: DbSession, user: StudentUser) -> list[SubjectImprovement]:
    """The reader's own placing per subject, with the reader's own history.

    Subjects come from `visible_subject_ids`, the same helper the readiness API
    uses, so this endpoint can never widen a student's reach beyond the subjects
    they are enrolled in — including into another organization's copy of the
    same global subject row (SEC-8).
    """
    subject_ids = await visible_subject_ids(db, user, user.id)
    return await build_improvement(db, user, subject_ids or [])
