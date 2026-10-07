"""A tutor setting a locked attempt aside so the student can hand the work in again.

Since #145 a student cannot replace an attempt once it is locked (`attempts.
attempt_is_locked`): replacing it would delete marks that already count. That is
right, and it left no way out when the wrong file was uploaded. This is the way
out, and it is the tutor's alone.

**The old attempt is moved, not flagged.** Its whole state is written to an
append-only `AttemptRedo` row and the live rows are deleted. Every reader of
submissions, marks, mistakes and evidence then stops counting it with no new
filter, and — more to the point — a reader written next year cannot forget one.
Only the new attempt is ever in the live tables, so only the new attempt counts
toward readiness (the owner's decision).

Everything happens in the caller's transaction and is flushed, not committed, so
a failure part-way leaves the old attempt exactly as it was.
"""

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AssessableWork,
    AttemptRedo,
    Evidence,
    MarkOverrideAudit,
    Mistake,
    MistakeCategory,
    MistakeTopic,
    MockOpening,
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    User,
)
from app.schemas.attempt_redo import AttemptRedoOut
from app.services.attempts import attempt_is_locked
from app.services.narrative import enqueue_class_narratives_for_student_subject
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced
from app.services.submission_kind import (
    HOMEWORK,
    MOCK,
    PAST_PAPER,
    SubmissionKind,
    kind_of,
)
from app.services.work import parent_of

#: Bumped when the shape of `AttemptRedo.record` changes, so a reader months
#: from now knows which shape it is holding.
RECORD_VERSION = 1


class RedoRefused(Exception):
    """The attempt may not be redone. `str(exc)` is a message fit for a tutor."""


class AttemptGone(RedoRefused):
    """The submission no longer exists — most likely it was already redone."""


class AttemptNotLocked(RedoRefused):
    """The student can already replace this attempt, so there is nothing to set aside."""


class AttemptBeingMarked(RedoRefused):
    """A marking job is mid-flight on it; deleting the rows under that job is unsafe."""


# ---- the snapshot ------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _row(obj: Any) -> dict[str, Any]:
    """Every column of a row, so a column added later is carried without anyone
    remembering to list it here."""
    return {
        attr.key: _jsonable(getattr(obj, attr.key)) for attr in sa_inspect(obj).mapper.column_attrs
    }


async def _audit_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, list[dict]]:
    rows = await session.scalars(
        select(MarkOverrideAudit)
        .where(MarkOverrideAudit.question_mark_id.in_(mark_ids))
        .order_by(MarkOverrideAudit.id)
    )
    grouped: dict[int, list[dict]] = {}
    for audit in rows:
        grouped.setdefault(audit.question_mark_id, []).append(_row(audit))
    return grouped


async def _remark_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, dict]:
    rows = await session.scalars(
        select(RemarkRequest).where(RemarkRequest.question_mark_id.in_(mark_ids))
    )
    return {remark.question_mark_id: _row(remark) for remark in rows}


async def _mistakes_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, list[dict]]:
    rows = (
        await session.execute(
            select(Mistake, MistakeCategory.name)
            .join(MistakeCategory, MistakeCategory.id == Mistake.category_id)
            .where(Mistake.question_mark_id.in_(mark_ids))
            .order_by(Mistake.id)
        )
    ).all()
    topics: dict[int, list[int]] = {}
    mistake_ids = [mistake.id for mistake, _ in rows]
    if mistake_ids:
        links = await session.execute(
            select(MistakeTopic.mistake_id, MistakeTopic.topic_id)
            .where(MistakeTopic.mistake_id.in_(mistake_ids))
            .order_by(MistakeTopic.id)
        )
        for mistake_id, topic_id in links:
            topics.setdefault(mistake_id, []).append(topic_id)
    grouped: dict[int, list[dict]] = {}
    for mistake, category_name in rows:
        entry = {
            **_row(mistake),
            "category_name": category_name,
            "topic_ids": topics.get(mistake.id, []),
        }
        grouped.setdefault(mistake.question_mark_id, []).append(entry)
    return grouped


async def _questions_by_mark(
    session: AsyncSession, kind: SubmissionKind, marks: list[QuestionMark]
) -> dict[int, Any]:
    ids = {getattr(mark, kind.mark_fk) for mark in marks} - {None}
    rows = await session.scalars(select(kind.question_model).where(kind.question_model.id.in_(ids)))
    by_id = {question.id: question for question in rows}
    return {mark.id: by_id.get(getattr(mark, kind.mark_fk)) for mark in marks}


def _question_entry(question: Any) -> dict[str, Any] | None:
    if question is None:
        return None
    return {
        "id": question.id,
        "number": question.number,
        "max_marks": question.max_marks,
        "text_summary": question.text_summary,
    }


async def _mark_entries(
    session: AsyncSession, kind: SubmissionKind, marks: list[QuestionMark]
) -> list[dict[str, Any]]:
    if not marks:
        return []
    ids = [mark.id for mark in marks]
    audits = await _audit_by_mark(session, ids)
    remarks = await _remark_by_mark(session, ids)
    mistakes = await _mistakes_by_mark(session, ids)
    questions = await _questions_by_mark(session, kind, marks)
    return [
        {
            **_row(mark),
            "question": _question_entry(questions[mark.id]),
            # Verbatim and in order: this is the carried-over `PROD-7` trail.
            "override_audit": audits.get(mark.id, []),
            "remark_request": remarks.get(mark.id),
            "mistakes": mistakes.get(mark.id, []),
        }
        for mark in sorted(marks, key=lambda mark: mark.id)
    ]


def _final_totals(entries: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Marks earned and marks available, over the questions that had a final
    mark only — a fair fraction, and both `None` when none did (`PROD-2`)."""
    decided = [
        entry
        for entry in entries
        if entry["final_marks"] is not None and entry["question"] is not None
    ]
    if not decided:
        return None, None
    return (
        sum(entry["final_marks"] for entry in decided),
        sum(entry["question"]["max_marks"] for entry in decided),
    )


async def _kind_extras(
    session: AsyncSession, kind: SubmissionKind, submission: Submission, parent: Any
) -> dict[str, Any]:
    """What only one arm has: a mock's clock, a past paper's roll-up."""
    extras: dict[str, Any] = {}
    if kind is MOCK:
        opening = await session.scalar(
            select(MockOpening).where(
                MockOpening.mock_id == parent.id, MockOpening.student_id == submission.student_id
            )
        )
        extras["mock_opening"] = _row(opening) if opening is not None else None
    if kind is PAST_PAPER:
        rollup = await session.scalar(
            select(PastPaperAttempt).where(
                PastPaperAttempt.past_paper_id == parent.id,
                PastPaperAttempt.student_id == submission.student_id,
            )
        )
        extras["past_paper_attempt"] = _row(rollup) if rollup is not None else None
    return extras


async def _snapshot(
    session: AsyncSession, kind: SubmissionKind, submission: Submission, parent: Any
) -> tuple[dict[str, Any], int | None, int | None]:
    entries = await _mark_entries(session, kind, list(submission.marks))
    got, available = _final_totals(entries)
    record = {
        "version": RECORD_VERSION,
        "kind": kind.work_kind.value,
        "work": {"id": submission.work_id, "title": submission.work.title},
        "submission": _row(submission),
        "files": [_row(file) for file in submission.files],
        "marks": entries,
        **await _kind_extras(session, kind, submission, parent),
    }
    return record, got, available


# ---- the removal -------------------------------------------------------------


async def _delete_marks_and_what_hangs_off_them(session: AsyncSession, mark_ids: list[int]) -> None:
    """In foreign-key order: none of these keys cascades, and the override audit
    is append-only everywhere *except* here, where the snapshot already holds
    every row verbatim. `mistake_revision_audit` is left alone on purpose: its
    ids are plain integers precisely so it outlives the mistake it explains."""
    if not mark_ids:
        return
    mistake_ids = (
        await session.scalars(select(Mistake.id).where(Mistake.question_mark_id.in_(mark_ids)))
    ).all()
    if mistake_ids:
        await session.execute(delete(MistakeTopic).where(MistakeTopic.mistake_id.in_(mistake_ids)))
    await session.execute(delete(Mistake).where(Mistake.question_mark_id.in_(mark_ids)))
    await session.execute(delete(RemarkRequest).where(RemarkRequest.question_mark_id.in_(mark_ids)))
    await session.execute(
        delete(MarkOverrideAudit).where(MarkOverrideAudit.question_mark_id.in_(mark_ids))
    )
    await session.execute(delete(QuestionMark).where(QuestionMark.id.in_(mark_ids)))


async def _delete_attempt(
    session: AsyncSession, kind: SubmissionKind, submission: Submission, parent: Any
) -> None:
    mark_ids = [mark.id for mark in submission.marks]
    await _delete_marks_and_what_hangs_off_them(session, mark_ids)
    # Rows only: the stored pages stay on disk, exactly as `open_attempt` leaves
    # them, so nothing here can fail on a storage error half-way through.
    await session.execute(
        delete(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
    )
    if kind is MOCK:
        # The clock starts again when the student reopens the paper.
        await session.execute(
            delete(MockOpening).where(
                MockOpening.mock_id == parent.id, MockOpening.student_id == submission.student_id
            )
        )
    if kind is PAST_PAPER:
        # The roll-up the Past Paper Performance factor reads is derived from
        # this attempt; left behind it would keep counting after the attempt is gone.
        await session.execute(
            delete(PastPaperAttempt).where(
                PastPaperAttempt.past_paper_id == parent.id,
                PastPaperAttempt.student_id == submission.student_id,
            )
        )
    await session.execute(
        delete(Evidence).where(Evidence.source_ref == f"submission:{submission.id}")
    )
    await session.execute(delete(Submission).where(Submission.id == submission.id))


# ---- the entry point ---------------------------------------------------------


async def _locked_submission(session: AsyncSession, submission_id: int) -> Submission:
    # `populate_existing`: the router has already loaded this row to check
    # ownership, and the lock is worthless if what we then read is that earlier copy.
    submission = await session.get(
        Submission,
        submission_id,
        options=[selectinload(Submission.files), selectinload(Submission.marks)],
        with_for_update=True,
        populate_existing=True,
    )
    if submission is None:
        raise AttemptGone("Submission not found")
    return submission


def _check_redoable(submission: Submission) -> None:
    if not attempt_is_locked(submission):
        raise AttemptNotLocked(
            "This attempt has no final mark yet, so the student can already replace it."
        )
    if submission.status == SubmissionStatus.marking:
        raise AttemptBeingMarked(
            "This attempt is being marked right now. Try again once marking has finished."
        )


async def redo_attempt(session: AsyncSession, submission_id: int, tutor: User) -> AttemptRedo:
    """Move a locked attempt into an `AttemptRedo` record and delete its live rows.

    The caller has already proved this tutor owns the submission (`_tutor_owns`)
    and commits afterwards. Raises `RedoRefused` subclasses; nothing has been
    changed when it does.
    """
    submission = await _locked_submission(session, submission_id)
    _check_redoable(submission)
    kind = kind_of(submission)
    parent = await parent_of(session, submission)
    if parent is None:
        raise AttemptGone("Submission not found")

    record, got, available = await _snapshot(session, kind, submission, parent)
    redo = AttemptRedo(
        organization_id=submission.work.organization_id,
        work_id=submission.work_id,
        student_id=submission.student_id,
        allowed_by_id=tutor.id,
        previous_submission_id=submission.id,
        previous_final_marks=got,
        previous_max_marks=available,
        record=record,
    )
    session.add(redo)
    subject_id = submission.work.subject_id
    student_id = submission.student_id
    await _delete_attempt(session, kind, submission, parent)
    await session.flush()

    # The same two calls `record_marks_as_evidence` ends with, minus the evidence
    # build — there is nothing left to build from. A pending run reads live state
    # when it fires, so it picks this change up whichever queued it.
    await enqueue_readiness_v2_debounced(session, student_id, subject_id)
    await enqueue_class_narratives_for_student_subject(session, student_id, subject_id)
    return redo


# ---- reading the record --------------------------------------------------------


async def _titles_by_work(session: AsyncSession, works: list[AssessableWork]) -> dict[int, str]:
    """The name each kind of work is shown under, read from its own parent row —
    `assessable_work.title` is a copy that extraction does not refresh for a
    past paper, so it can be empty where the paper has a title."""
    titles: dict[int, str] = {}
    for kind in (HOMEWORK, PAST_PAPER, MOCK):
        ids = [work.id for work in works if work.kind == kind.work_kind]
        if not ids:
            continue
        parents = await session.scalars(
            select(kind.parent_model).where(kind.parent_model.work_id.in_(ids))
        )
        for parent in parents:
            titles[parent.work_id] = (
                parent.display_title if isinstance(parent, PastPaper) else parent.title
            )
    return titles


async def _summaries(
    session: AsyncSession, rows: list[tuple[AttemptRedo, str, AssessableWork]]
) -> list[AttemptRedoOut]:
    titles = await _titles_by_work(session, [work for _, _, work in rows])
    return [
        AttemptRedoOut(
            id=redo.id,
            created_at=redo.created_at,
            allowed_by_id=redo.allowed_by_id,
            allowed_by_name=name,
            work_kind=work.kind.value,
            work_title=titles.get(work.id) or work.title or "Untitled",
            previous_final_marks=redo.previous_final_marks,
            previous_max_marks=redo.previous_max_marks,
        )
        for redo, name, work in rows
    ]


def _redo_rows():
    return (
        select(AttemptRedo, User.name, AssessableWork)
        .join(User, User.id == AttemptRedo.allowed_by_id)
        .join(AssessableWork, AssessableWork.id == AttemptRedo.work_id)
    )


async def redos_for_student(
    session: AsyncSession, *, student_id: int, organization_id: int
) -> list[AttemptRedoOut]:
    """Every attempt set aside for this student in this organization, newest first."""
    rows = (
        await session.execute(
            _redo_rows()
            .where(
                AttemptRedo.student_id == student_id,
                AttemptRedo.organization_id == organization_id,
            )
            .order_by(AttemptRedo.created_at.desc(), AttemptRedo.id.desc())
        )
    ).all()
    return await _summaries(session, [(redo, name, work) for redo, name, work in rows])


async def redo_summary(session: AsyncSession, redo: AttemptRedo) -> AttemptRedoOut:
    """The receipt for one redo, in the same shape the list uses."""
    redo_row, name, work = (
        await session.execute(_redo_rows().where(AttemptRedo.id == redo.id))
    ).one()
    return (await _summaries(session, [(redo_row, name, work)]))[0]
