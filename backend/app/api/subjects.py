from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Subject, Topic
from app.schemas.groups import SubjectOut, TopicOut

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("", response_model=list[SubjectOut])
async def list_subjects(db: DbSession, _: CurrentUser) -> list[SubjectOut]:
    subjects = (await db.scalars(select(Subject).order_by(Subject.exam_board, Subject.code))).all()
    return [SubjectOut.model_validate(s) for s in subjects]


@router.get("/{subject_id}/topics", response_model=list[TopicOut])
async def list_topics(subject_id: int, db: DbSession, _: CurrentUser) -> list[TopicOut]:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    topics = (
        await db.scalars(select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.id))
    ).all()
    return [TopicOut.model_validate(t) for t in topics]
