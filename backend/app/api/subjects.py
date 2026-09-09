from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Chapter, Subject, Topic
from app.schemas.groups import ChapterOut, SubjectOut, TopicOut
from app.services.subjects import visible_subject_ids

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("", response_model=list[SubjectOut])
async def list_subjects(db: DbSession, user: CurrentUser) -> list[SubjectOut]:
    # Every role reaches this route, and until task 2.2 it returned every
    # subject in the database to all of them — harmless while the five
    # syllabuses were global built-ins, a cross-tenant leak the moment they
    # became tutor-owned (AV-6, PROD-4, SEC-7).
    visible = await visible_subject_ids(db, user)
    if not visible:
        return []
    subjects = (
        await db.scalars(
            select(Subject)
            .where(Subject.id.in_(visible))
            .order_by(Subject.exam_board, Subject.code)
        )
    ).all()
    return [SubjectOut.model_validate(s) for s in subjects]


@router.get("/{subject_id}/topics", response_model=list[TopicOut])
async def list_topics(subject_id: int, db: DbSession, user: CurrentUser) -> list[TopicOut]:
    # 404 rather than 403 for a subject in someone else's account: ids are
    # enumerable, and "not yours" and "does not exist" must look identical
    # (API-7, SEC-9).
    if subject_id not in await visible_subject_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    topics = (
        await db.scalars(select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.id))
    ).all()
    return [TopicOut.model_validate(t) for t in topics]


@router.get("/{subject_id}/chapters", response_model=list[ChapterOut])
async def list_chapters(subject_id: int, db: DbSession, user: CurrentUser) -> list[ChapterOut]:
    """This subject's chapters, in teaching order.

    Same visibility rule and same 404 as `/topics` above: a subject in another
    account is indistinguishable from one that does not exist (`API-7`,
    `SEC-9`). A subject whose syllabus was never extracted chapter-first
    legitimately has none, and an empty list is that answer — not an error and
    not something to invent structure for (`PROD-2`).

    Ordered by `position`, which is teaching order and is deliberately not
    derived from `code`: a tutor may teach chapter 4 before chapter 3.
    """
    if subject_id not in await visible_subject_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    chapters = (
        await db.scalars(
            select(Chapter).where(Chapter.subject_id == subject_id).order_by(Chapter.position)
        )
    ).all()
    return [ChapterOut.model_validate(c) for c in chapters]
