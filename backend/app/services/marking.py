"""AI marking.

The AI reads a student's handwritten pages and marks every question. A mark
the AI is confident about *and* that an official mark scheme covers is
recorded as final immediately — the student sees it and it becomes readiness
evidence with no tutor action. Everything else (no scheme, low confidence, a
question the AI didn't answer for) is flagged into the tutor's review queue
with the AI's suggestion pre-filled.

That trade is deliberate (see CLAUDE.md): a tutor cannot review every mark for
every student, and a mark that never gets confirmed never becomes evidence,
which leaves readiness empty. The tutor keeps override authority over any mark
at any time, every override is audited, and a student can contest any
finalized mark through a remark request.
"""

from datetime import datetime, timezone
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
from app.services.evidence import build_homework_evidence
from app.services.knowledge import build_tutor_context
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced
from app.workers.jobs import enqueue

# Confidence levels good enough for a scheme-backed mark to stand without a
# tutor. Anything else goes to the review queue.
AUTO_FINALIZE_CONFIDENCE = (MarkConfidence.high, MarkConfidence.medium)


class QuestionMarkDraft(BaseModel):
    number: str = Field(description="Question number, matching the assignment's question list")
    transcription: str = Field(
        description="Faithful transcription of the student's written answer (or 'No answer found')"
    )
    proposed_marks: int | None = Field(
        description="Marks to award; null only if the answer cannot be marked at all"
    )
    feedback: str = Field(description="Short, constructive feedback for the student")
    confidence: Literal["high", "medium", "low", "unsure"] = Field(
        description="Marking confidence; 'unsure' whenever no official mark scheme covers "
        "the question, regardless of how clear the answer is"
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
            existing_marks[q.id] = mark
        mark.ai_model = response.model
        mark.ai_prompt_version = response.prompt_version
        if draft is None:
            # The AI skipped this question — never silently score it 0.
            mark.ai_transcription = "The AI did not return a result for this question."
            mark.ai_marks = None
            mark.ai_confidence = MarkConfidence.unsure
        else:
            mark.ai_transcription = draft.transcription
            mark.ai_feedback = draft.feedback
            mark.ai_confidence = MarkConfidence(draft.confidence)
            # Clamp to the question's mark range; trust nothing blindly.
            mark.ai_marks = (
                max(0, min(q.max_marks, draft.proposed_marks))
                if draft.proposed_marks is not None
                else None
            )

        confident = mark.ai_confidence in AUTO_FINALIZE_CONFIDENCE
        if q.has_mark_scheme and confident and mark.ai_marks is not None:
            # Scheme-backed and confident: the mark counts now.
            mark.final_marks = mark.ai_marks
            mark.final_feedback = mark.ai_feedback
            mark.auto_finalized = True
            mark.needs_review = False
        else:
            # No official scheme, low confidence, or nothing to mark: the AI's
            # number is a suggestion for the tutor, not a result.
            mark.auto_finalized = False
            mark.needs_review = True

    await _settle_submission(session, submission, group)


async def _settle_submission(
    session: AsyncSession, submission: Submission, group: Group
) -> None:
    """Decide what happens to the submission once every question is marked.

    If anything needs a tutor, the submission waits in the review queue. If
    nothing does, it auto-finalizes: the marks become readiness evidence and a
    recompute is scheduled, with no tutor step at all.
    """
    await session.flush()
    pending_review = await session.scalar(
        select(QuestionMark.id).where(
            QuestionMark.submission_id == submission.id,
            QuestionMark.needs_review.is_(True),
        )
    )
    if pending_review is not None:
        submission.status = SubmissionStatus.needs_review
        return

    submission.status = SubmissionStatus.auto_finalized
    submission.finalized_at = datetime.now(timezone.utc)
    # finalized_by_id stays null: nobody signed this off, the AI did.
    await session.flush()
    await record_marks_as_evidence(session, submission, group.subject_id)


async def record_marks_as_evidence(
    session: AsyncSession, submission: Submission, subject_id: int
) -> None:
    """Turn a submission's final marks into readiness evidence and schedule the
    recomputes. Shared by auto-finalize and the tutor's finalize endpoint;
    build_homework_evidence is idempotent by source_ref, so running it again
    after a tutor override replaces rather than duplicates."""
    await build_homework_evidence(session, submission)
    await enqueue(
        session,
        "recompute_readiness",
        {"student_id": submission.student_id, "subject_id": subject_id},
    )
    await enqueue_readiness_v2_debounced(session, submission.student_id, subject_id)
