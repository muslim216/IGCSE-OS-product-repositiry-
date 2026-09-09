"""The tutor's marking rules for one subject — the "AI marking agreement".

`AV-75`: written once for a subject, applying to every chapter, classified and
piece of work in it, **in addition to** board, level and chapter notes rather
than instead of them. There is deliberately no account-wide layer.

`AV-111`: this is what Library calls the AI marking agreement, and it describes
**how** the AI marks, never **when a mark counts**. `AV-25`'s auto-finalize rule
— scheme-backed *and* confident — is not reachable from anything written here,
and no text a tutor saves changes it.

Nothing consumes this yet. Phase 3's context assembler is the single function
that will (`E16`), applying `AV-76`'s precedence: mark scheme → chapter notes →
subject rules → exam board and level. Storing it now is what lets that task be
about precedence rather than about plumbing.

Tutor-only and organization-scoped through `owned_subject`, so another tenant's
subject id is a 404 rather than a 403 (`API-7`, `SEC-9`); the role gate is a
signature dependency (`SEC-11`, `BE-17`).
"""

from fastapi import APIRouter

from app.api.deps import DbSession, TutorUser, owned_subject
from app.models import Subject
from app.schemas.marking_rules import MarkingRulesIn, MarkingRulesOut
from app.services.marking_rules import SUMMARISE_JOB
from app.workers.jobs import enqueue

router = APIRouter(prefix="/subjects", tags=["marking-rules"])


def _out(subject: Subject) -> MarkingRulesOut:
    return MarkingRulesOut(
        subject_id=subject.id,
        subject_name=subject.name,
        rules=subject.marking_rules or "",
        configured=bool(subject.marking_rules),
        summary=subject.marking_rules_summary,
    )


@router.get("/{subject_id}/marking-rules", response_model=MarkingRulesOut)
async def read_marking_rules(subject_id: int, db: DbSession, user: TutorUser) -> MarkingRulesOut:
    return _out(await owned_subject(db, subject_id, user))


@router.put("/{subject_id}/marking-rules", response_model=MarkingRulesOut)
async def write_marking_rules(
    subject_id: int, body: MarkingRulesIn, db: DbSession, user: TutorUser
) -> MarkingRulesOut:
    """Replace this subject's rules. Saving an empty body clears them.

    Clearing is a real action, not an edge case: these rules are the one
    onboarding step a tutor may skip (`AV-87`), so "I do not want any" has to be
    reachable from the editor and has to survive. Stored as NULL rather than an
    empty string so the two states cannot drift apart in the column.
    """
    subject = await owned_subject(db, subject_id, user)
    subject.marking_rules = body.rules or None
    # Cleared in the same transaction as the write, so the summary is absent or
    # current and never stale (task 3.2c). Until the job lands,
    # `build_marking_context` falls back to the full text — marking stays
    # correct, it just costs more.
    subject.marking_rules_summary = None
    if subject.marking_rules:
        await enqueue(db, SUMMARISE_JOB, {"subject_id": subject.id, "tutor_id": user.id})
    await db.commit()
    return _out(subject)
