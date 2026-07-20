"""AI extraction: read a classified PDF (and optional mark scheme) and produce
the assignment's question list for the tutor to review."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Classified,
    Group,
    QuestionTopic,
    Topic,
)
from app.services import storage
from app.services.ai import file_block, get_client


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


SYSTEM_PROMPT = """You are extracting the question list from an IGCSE/O Level 'classified' \
(a booklet of past-paper questions compiled by topic) so a tutor can assign it as homework.

Rules:
- List every question in the requested range, in the order they appear.
- Use the question numbering exactly as printed in the booklet.
- max_marks comes from the printed marks (e.g. '[3]'); if no marks are printed, estimate \
conservatively from the question's demands.
- topic_codes must come from the provided syllabus topic list only.
- has_mark_scheme is true ONLY when an official mark scheme or answer for that specific \
question appears in the provided documents. Never guess."""


async def extract_assignment(session: AsyncSession, payload: dict) -> None:
    assignment_id = payload["assignment_id"]
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:
        return
    if assignment.classified_id is None:
        assignment.status = AssignmentStatus.review
        return
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

    client = get_client()
    response = await client.messages.parse(
        model=get_settings().anthropic_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=ExtractionResult,
    )
    result: ExtractionResult = response.parsed_output
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
