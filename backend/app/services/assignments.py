"""Assignment creation from an uploaded question paper.

One call stores the paper (and optional mark scheme), creates the `Classified`
and the `Assignment` that points at it, and queues extraction — replacing the
two-request flow where a failure in between left an orphaned classified.
"""

from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Assignment, AssignmentStatus, Classified, Group, User
from app.services import storage
from app.workers.jobs import enqueue


async def create_from_upload(
    session: AsyncSession,
    *,
    group: Group,
    tutor: User,
    file: UploadFile,
    mark_scheme: UploadFile | None = None,
    title: str | None = None,
    instructions: str | None = None,
    due_at: datetime | None = None,
    question_range: str | None = None,
) -> Assignment:
    """Store the paper and set it as homework. Commits on success.

    Files land on disk before the rows that reference them exist, so anything
    that fails afterwards (a rejected mark scheme, a DB error) must take the
    already-written files with it — an unreferenced file is invisible and can
    never be cleaned up.
    """
    written: list[str] = []
    try:
        path, name, mime = await storage.save_upload(file)
        written.append(path)
        # "4CH1 June 2023 Paper 1.pdf" -> "4CH1 June 2023 Paper 1"
        resolved_title = (title or Path(name).stem or name)[:255]
        classified = Classified(
            organization_id=group.organization_id,
            tutor_id=tutor.id,
            subject_id=group.subject_id,
            title=resolved_title,
            file_path=path,
            file_name=name,
            file_mime=mime,
        )
        if mark_scheme is not None:
            ms_path, ms_name, ms_mime = await storage.save_upload(mark_scheme)
            written.append(ms_path)
            classified.mark_scheme_path = ms_path
            classified.mark_scheme_name = ms_name
            classified.mark_scheme_mime = ms_mime
        session.add(classified)
        await session.flush()

        assignment = Assignment(
            group_id=group.id,
            classified_id=classified.id,
            title=resolved_title,
            instructions=instructions or None,
            due_at=due_at,
            question_range=question_range or None,
            status=AssignmentStatus.extracting,
        )
        session.add(assignment)
        await session.flush()
        await enqueue(session, "extract_assignment", {"assignment_id": assignment.id})
        await session.commit()
    except Exception:
        await session.rollback()
        for rel_path in written:
            storage.delete_file(rel_path)
        raise

    return assignment
