"""AI extraction: read a classified PDF (and optional mark scheme) and produce
the assignment's question list for the tutor to review."""

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiFeature,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Classified,
    Group,
    QuestionTopic,
    Topic,
)
from app.services import storage
from app.services.ai import file_block, record_usage, structured_complete
from app.services.knowledge import build_tutor_context


class ExtractedQuestion(BaseModel):
    number: str = Field(description="Question number/label exactly as printed, e.g. '1', '3b'")
    text_summary: str = Field(description="One-line summary of what the question asks")
    max_marks: int = Field(description="Maximum marks for this question")
    topic_codes: list[str] = Field(description="Syllabus topic codes this question tests")
    has_mark_scheme: bool = Field(
        description="True only if an official mark scheme / answer for this question is present in the provided documents"
    )


class ExtractionResult(BaseModel):
    questions: list[ExtractedQuestion]


async def _clear_questions(session: AsyncSession, assignment_id: int) -> None:
    existing = (
        await session.scalars(
            select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment_id)
        )
    ).all()
    if not existing:
        return
    await session.execute(
        delete(QuestionTopic).where(QuestionTopic.question_id.in_([q.id for q in existing]))
    )
    await session.execute(
        delete(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment_id)
    )


async def extract_assignment(session: AsyncSession, payload: dict) -> None:
    assignment_id = payload["assignment_id"]
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:
        return
    if assignment.classified_id is None:
        assignment.status = AssignmentStatus.review
        return
    # Idempotency: extraction replaces the assignment's question list rather
    # than appending to it, so a worker retry (or a tutor-triggered
    # re-extraction) can't leave the assignment with two copies of every
    # question. Extraction only ever runs on an unpublished assignment, so no
    # QuestionMark rows reference these questions yet.
    await _clear_questions(session, assignment.id)
    try:
        await _run_extraction(session, assignment)
        assignment.status = AssignmentStatus.review
        assignment.extraction_error = None
    except Exception as exc:
        assignment.status = AssignmentStatus.extraction_failed
        assignment.extraction_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _run_extraction(session: AsyncSession, assignment: Assignment) -> None:
    classified = await session.get(Classified, assignment.classified_id)
    group = await session.get(Group, assignment.group_id)
    topics = (
        await session.scalars(select(Topic).where(Topic.subject_id == group.subject_id))
    ).all()
    topic_list = "\n".join(f"- {t.code}: {t.title}" for t in topics)

    content: list[dict] = [file_block(storage.read_file(classified.file_path), classified.file_mime)]
    if classified.mark_scheme_path:
        content.append(
            file_block(storage.read_file(classified.mark_scheme_path), classified.mark_scheme_mime)
        )
    range_note = (
        f"Extract ONLY this part of the booklet: {assignment.question_range}."
        if assignment.question_range
        else "Extract ALL questions in the booklet."
    )
    content.append(
        {
            "type": "text",
            "text": (
                f"{range_note}\n\nSyllabus topics for this subject:\n{topic_list}\n\n"
                "Return the full question list."
            ),
        }
    )

    kb_context = await build_tutor_context(session, group.tutor_id, group.subject_id)

    response = await structured_complete(
        surface="extraction",
        content=content,
        output_format=ExtractionResult,
        max_tokens=16000,
        extra_system=[kb_context] if kb_context else [],
    )
    await record_usage(
        session,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=None,
        feature=AiFeature.extraction,
    )
    result: ExtractionResult = response.parsed
    if not result.questions:
        raise ValueError("No questions were found in the document")

    topic_by_code = {t.code: t for t in topics}
    for position, q in enumerate(result.questions):
        question = AssignmentQuestion(
            assignment_id=assignment.id,
            position=position,
            number=q.number[:16],
            text_summary=q.text_summary,
            max_marks=max(1, q.max_marks),
            has_mark_scheme=q.has_mark_scheme,
        )
        session.add(question)
        await session.flush()
        for code in q.topic_codes:
            topic = topic_by_code.get(code)
            if topic is not None:
                session.add(QuestionTopic(question_id=question.id, topic_id=topic.id))
