"""AI marking: read a student's handwritten pages against the mark scheme and
produce a per-question draft (transcription, proposed marks, feedback,
confidence) for the tutor to review. The AI never proposes marks for questions
without official mark-scheme coverage."""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import (
    AiFeature,
    Assignment,
    AssignmentQuestion,
    Classified,
    Group,
    MarkConfidence,
    QuestionMark,
    Submission,
    SubmissionStatus,
)
from app.services import storage
from app.services.ai import file_block, get_client, record_usage
from app.services.knowledge import build_tutor_context


class QuestionMarkDraft(BaseModel):
    number: str = Field(description="Question number, matching the assignment's question list")
    transcription: str = Field(
        description="Faithful transcription of the student's written answer (or 'No answer found')"
    )
    proposed_marks: int | None = Field(
        description="Marks to award per the official mark scheme; null when has_mark_scheme is false"
    )
    feedback: str = Field(description="Short, constructive feedback for the student")
    confidence: Literal["high", "medium", "low", "tutor_only"] = Field(
        description="Marking confidence; 'tutor_only' when no official mark scheme covers the question"
    )


class MarkingResult(BaseModel):
    questions: list[QuestionMarkDraft]


SYSTEM_PROMPT = """You are drafting the first marking pass of IGCSE/O Level homework for a \
tutor who will review every mark before anything counts. The student's answers are \
handwritten pages photographed or scanned.

Rules:
- Transcribe each answer faithfully from the student's pages. If you cannot find or read \
an answer, say so in the transcription and use confidence 'low' (or 'tutor_only' if unmarkable).
- Award marks STRICTLY per the official mark scheme in the provided documents — follow its \
mark allocation points exactly. Never award marks the scheme does not justify.
- For questions flagged has_mark_scheme=false you MUST set proposed_marks to null and \
confidence to 'tutor_only'; still transcribe the answer to save the tutor time.
- confidence 'high' = clearly legible answer, unambiguous scheme application; 'medium' = \
minor doubt; 'low' = hard to read or ambiguous — the tutor must look closely.
- Feedback is for the student: brief, specific, encouraging, and references what the mark \
scheme wanted."""


async def mark_submission(session: AsyncSession, payload: dict) -> None:
    submission_id = payload["submission_id"]
    submission = await session.get(
        Submission, submission_id, options=[selectinload(Submission.files)]
    )
    if submission is None or submission.status == SubmissionStatus.finalized:
        return
    try:
        await _run_marking(session, submission)
        submission.status = SubmissionStatus.ai_marked
        submission.ai_error = None
    except Exception as exc:
        submission.status = SubmissionStatus.ai_failed
        submission.ai_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _run_marking(session: AsyncSession, submission: Submission) -> None:
    assignment = await session.get(Assignment, submission.assignment_id)
    classified = (
        await session.get(Classified, assignment.classified_id)
        if assignment.classified_id
        else None
    )
    questions = (
        await session.scalars(
            select(AssignmentQuestion)
            .where(AssignmentQuestion.assignment_id == assignment.id)
            .order_by(AssignmentQuestion.position)
        )
    ).all()
    files = sorted(submission.files, key=lambda f: f.position)
    if not files:
        raise ValueError("The submission has no uploaded files")

    question_list = "\n".join(
        f"- Q{q.number}: {q.text_summary} (max {q.max_marks} marks, "
        f"has_mark_scheme={'true' if q.has_mark_scheme else 'false'})"
        for q in questions
    )

    content: list[dict] = []
    # The classified/mark scheme is shared across every submission in the class —
    # cache it so marking a batch reuses the prefix.
    if classified is not None:
        content.append(
            file_block(storage.read_file(classified.file_path), classified.file_mime, cache=True)
        )
        if classified.mark_scheme_path:
            content.append(
                file_block(
                    storage.read_file(classified.mark_scheme_path),
                    classified.mark_scheme_mime,
                    cache=True,
                )
            )
    for f in files:
        content.append(file_block(storage.read_file(f.path), f.mime))

    if classified is not None:
        intro = (
            "The documents above are: (1) the question booklet, "
            + ("(2) the mark scheme, " if classified.mark_scheme_path else "")
            + "followed by the student's handwritten answer pages."
        )
    else:
        intro = (
            "No question booklet is attached to this assignment — mark from the question "
            "list below and the student's handwritten answer pages above only."
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"{intro}\n\n"
                f"Questions to mark:\n{question_list}\n\n"
                "Produce the marking draft for every question in the list."
            ),
        }
    )

    group = await session.get(Group, assignment.group_id)
    system: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    kb_context = await build_tutor_context(session, group.tutor_id, group.subject_id)
    if kb_context:
        system.append({"type": "text", "text": kb_context, "cache_control": {"type": "ephemeral"}})

    client = get_client()
    response = await client.messages.parse(
        model=get_settings().anthropic_model,
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=MarkingResult,
    )
    await record_usage(
        session,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=submission.student_id,
        feature=AiFeature.marking,
    )
    result: MarkingResult = response.parsed_output

    drafts_by_number = {d.number.lstrip("Qq"): d for d in result.questions}
    for q in questions:
        draft = drafts_by_number.get(q.number) or drafts_by_number.get(q.number.lstrip("Qq"))
        mark = QuestionMark(submission_id=submission.id, question_id=q.id)
        if draft is None:
            mark.ai_transcription = "The AI did not return a result for this question."
            mark.ai_confidence = MarkConfidence.tutor_only
        else:
            mark.ai_transcription = draft.transcription
            mark.ai_feedback = draft.feedback
            if q.has_mark_scheme and draft.proposed_marks is not None:
                # Clamp to the question's mark range; trust nothing blindly.
                mark.ai_marks = max(0, min(q.max_marks, draft.proposed_marks))
                mark.ai_confidence = MarkConfidence(draft.confidence)
            else:
                # Hard rule: no official mark scheme -> no AI marks.
                mark.ai_marks = None
                mark.ai_confidence = MarkConfidence.tutor_only
        session.add(mark)
