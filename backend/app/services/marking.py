"""AI marking: read a student's handwritten pages against the mark scheme and
produce a per-question draft (transcription, proposed marks, feedback,
confidence) for the tutor to review. The AI never proposes marks for questions
without official mark-scheme coverage."""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.services.ai import file_block, record_usage, structured_complete
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

    # Idempotency: a worker retry (or a re-queued marking job) must not append
    # a second set of QuestionMark rows or re-charge an AI call for work
    # already done. Existing drafts are updated in place; anything the tutor
    # has already finalized is left untouched, and if every question is
    # finalized there is nothing left to ask the AI.
    existing_marks = {
        m.question_id: m
        for m in (
            await session.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission.id)
            )
        ).all()
    }
    if questions and all(
        (m := existing_marks.get(q.id)) is not None and m.final_marks is not None
        for q in questions
    ):
        return

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
    kb_context = await build_tutor_context(session, group.tutor_id, group.subject_id)

    response = await structured_complete(
        surface="marking",
        content=content,
        output_format=MarkingResult,
        max_tokens=32000,
        extra_system=[kb_context] if kb_context else [],
        cache_extra_system=True,
    )
    await record_usage(
        session,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=submission.student_id,
        feature=AiFeature.marking,
    )
    result: MarkingResult = response.parsed

    drafts_by_number = {d.number.lstrip("Qq"): d for d in result.questions}
    for q in questions:
        draft = drafts_by_number.get(q.number) or drafts_by_number.get(q.number.lstrip("Qq"))
        mark = existing_marks.get(q.id)
        if mark is not None and mark.final_marks is not None:
            continue  # the tutor has already ruled on this one
        if mark is None:
            mark = QuestionMark(submission_id=submission.id, question_id=q.id)
            session.add(mark)
        mark.ai_model = response.model
        mark.ai_prompt_version = response.prompt_version
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
