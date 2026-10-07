"""A tutor setting a locked attempt aside so the student can hand the work in again.

Since #145 a student cannot replace an attempt once it is locked (`attempts.
attempt_is_locked`): replacing it would delete marks that already count. That is
right, and it left no way out when the wrong file was uploaded. This is the way
out, and it is the tutor's alone.

**The old attempt is moved, not flagged.** Its whole state is written to an
append-only `AttemptRedo` row (`attempt_redo_record`) and the live rows are
deleted. Every reader of submissions, marks, mistakes and evidence then stops
counting it with no new filter, and — more to the point — a reader written next
year cannot forget one. Only the new attempt is ever in the live tables, so only
the new attempt counts toward readiness (the owner's decision).

**One rule for "may this be redone"** (`redo_refusal`), used by the endpoint and
by the review page's `can_redo`, so the button cannot offer what the endpoint
would refuse. It is destructive, so it asks more than `_tutor_owns` does: the
tutor must teach this student (a past paper is organization-wide for marking,
which is tolerable for an audited override and not for this), the attempt must
be locked, nothing may be marking or tagging it, and the student must still be
able to hand the work in again — a redo that leaves them no way to replace what
it deleted destroys marks for nothing (`services/hand_in_gate`).

**Concurrency.** The submission row and every one of its mark rows are locked
(`FOR UPDATE`) before the snapshot is taken, so a tutor override committing in
another tab cannot add an audit row between snapshot and delete. After the
deletes each count is compared with what the snapshot holds, and any difference
raises and rolls back. The residual race is an insert by a path that takes no
such lock — `request_remark`, or a `tag_mistakes` run that started before the
job check — landing between the snapshot and the delete; on Postgres that
either changes a count or violates a foreign key, and both fail closed: nothing
is deleted and the tutor is asked to try again.

Everything happens in the caller's transaction and is flushed, not committed, so
a failure part-way leaves the old attempt exactly as it was.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Delete, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AssessableWork,
    AttemptRedo,
    Evidence,
    Job,
    JobStatus,
    MarkOverrideAudit,
    Mistake,
    MistakeTopic,
    MockOpening,
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    Submission,
    SubmissionFile,
    User,
)
from app.schemas.attempt_redo import AttemptRedoOut
from app.services.attempt_redo_record import Snapshot, SnapshotCounts, build_snapshot, evidence_ref
from app.services.attempts import HasFinalMarks, attempt_is_locked
from app.services.groups import tutor_teaches_student
from app.services.hand_in_gate import open_to
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

#: Jobs that read or write an attempt's marks. While one is queued or running,
#: deleting those rows under it is unsafe.
MARKING_JOBS = ("mark_submission", "tag_mistakes")

TRY_AGAIN = "This attempt is being marked right now. Try again in a moment."


class RedoRefused(Exception):
    """The attempt may not be redone. `str(exc)` is a message fit for a tutor."""


class AttemptGone(RedoRefused):
    """Not there as far as this tutor is concerned: the submission no longer
    exists (most likely already redone) or is not one they may act on. The
    router answers `404` — an enumerable id says nothing (`API-7`)."""


class AttemptNotLocked(RedoRefused):
    """The student can already replace this attempt, so there is nothing to set aside."""


class AttemptBeingMarked(RedoRefused):
    """A marking or tagging job is queued or running for it."""


class AttemptNotOpen(RedoRefused):
    """The student could not hand this work in again, so a redo would only
    delete their marks."""


class AttemptChanged(RedoRefused):
    """Something wrote to the attempt while it was being set aside; nothing was
    deleted. A retry sees the new state."""


# ---- may this be redone ------------------------------------------------------


async def _marking_in_flight(session: AsyncSession, submission_id: int) -> bool:
    """A queued or running job for this submission. Compared in Python rather
    than SQL because `payload` is a JSON column and Postgres' json type has no
    equality operator — the same pattern `marking.record_marks_as_evidence`
    uses to find a pending `tag_mistakes`."""
    payloads = await session.scalars(
        select(Job.payload).where(
            Job.type.in_(MARKING_JOBS),
            Job.status.in_((JobStatus.pending, JobStatus.running)),
        )
    )
    return any(p.get("submission_id") == submission_id for p in payloads)


async def redo_refusal(
    session: AsyncSession,
    submission: Submission,
    tutor: User,
    marks: Sequence[HasFinalMarks],
    parent: Any | None = None,
) -> RedoRefused | None:
    """Why this attempt may not be redone, or `None` when it may.

    Ordered so the first answer a caller outside the tutor's reach gets is the
    `404` one, and so an unlocked attempt costs one query to answer. `marks` are
    whatever rows the caller already holds (`attempt_is_locked`).
    """
    student = await session.get(User, submission.student_id)
    if student is None or not await tutor_teaches_student(session, tutor, student):
        return AttemptGone("Submission not found")
    if not attempt_is_locked(submission, marks):
        return AttemptNotLocked(
            "This attempt has no final mark yet, so the student can already replace it."
        )
    if await _marking_in_flight(session, submission.id):
        return AttemptBeingMarked(TRY_AGAIN)
    kind = kind_of(submission)
    parent = parent if parent is not None else await parent_of(session, submission)
    if parent is None:
        return AttemptGone("Submission not found")
    if not await open_to(session, kind, parent, submission.student_id):
        return AttemptNotOpen(
            f"This {kind.name} is no longer open to this student, so they could not "
            "hand it in again."
        )
    return None


# ---- the removal -------------------------------------------------------------


async def _delete_expecting(session: AsyncSession, stmt: Delete, expected: int) -> None:
    """Run a delete and insist it removed exactly what the snapshot recorded."""
    result = await session.execute(stmt)
    if result.rowcount != expected:  # type: ignore[attr-defined]
        raise AttemptChanged("This attempt changed while it was being set aside. " + TRY_AGAIN)


async def _delete_marks_and_what_hangs_off_them(
    session: AsyncSession, mark_ids: list[int], counts: SnapshotCounts
) -> None:
    """In foreign-key order: none of these keys cascades, and the override audit
    is append-only everywhere *except* here, where the snapshot already holds
    every row verbatim. `mistake_revision_audit` is left alone on purpose: its
    ids are plain integers precisely so it outlives the mistake it explains."""
    if not mark_ids:
        return
    mistake_ids = (
        await session.scalars(select(Mistake.id).where(Mistake.question_mark_id.in_(mark_ids)))
    ).all()
    await _delete_expecting(
        session,
        delete(MistakeTopic).where(MistakeTopic.mistake_id.in_(mistake_ids)),
        counts.topic_links,
    )
    await _delete_expecting(
        session, delete(Mistake).where(Mistake.question_mark_id.in_(mark_ids)), counts.mistakes
    )
    await _delete_expecting(
        session,
        delete(RemarkRequest).where(RemarkRequest.question_mark_id.in_(mark_ids)),
        counts.remarks,
    )
    await _delete_expecting(
        session,
        delete(MarkOverrideAudit).where(MarkOverrideAudit.question_mark_id.in_(mark_ids)),
        counts.audit,
    )
    await _delete_expecting(
        session, delete(QuestionMark).where(QuestionMark.id.in_(mark_ids)), counts.marks
    )


async def _delete_kind_extras(
    session: AsyncSession, kind: SubmissionKind, submission: Submission, parent: Any
) -> None:
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


async def _delete_attempt(
    session: AsyncSession,
    kind: SubmissionKind,
    submission: Submission,
    marks: Sequence[QuestionMark],
    parent: Any,
    counts: SnapshotCounts,
) -> None:
    await _delete_marks_and_what_hangs_off_them(session, [mark.id for mark in marks], counts)
    # Rows only: the stored pages stay on disk, exactly as `open_attempt` leaves
    # them, so nothing here can fail on a storage error half-way through.
    await session.execute(
        delete(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
    )
    await _delete_kind_extras(session, kind, submission, parent)
    await _delete_expecting(
        session,
        delete(Evidence).where(Evidence.source_ref == evidence_ref(submission.id)),
        counts.evidence,
    )
    await session.execute(delete(Submission).where(Submission.id == submission.id))


# ---- the entry point ---------------------------------------------------------


async def _lock(session: AsyncSession, submission_id: int) -> tuple[Submission, list[QuestionMark]]:
    """The submission and every one of its marks, locked and freshly read.

    `populate_existing`: the router has already loaded these rows to check
    ownership, and a lock is worthless if what we then read is that earlier copy.
    """
    submission = await session.get(
        Submission,
        submission_id,
        options=[selectinload(Submission.files)],
        with_for_update=True,
        populate_existing=True,
    )
    if submission is None:
        raise AttemptGone("Submission not found")
    marks = list(
        await session.scalars(
            select(QuestionMark)
            .where(QuestionMark.submission_id == submission_id)
            .order_by(QuestionMark.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return submission, marks


async def redo_attempt(session: AsyncSession, submission_id: int, tutor: User) -> AttemptRedo:
    """Move a locked attempt into an `AttemptRedo` record and delete its live rows.

    The caller commits afterwards. Raises `RedoRefused` subclasses; nothing has
    been changed when it does (the caller rolls back).
    """
    submission, marks = await _lock(session, submission_id)
    parent = await parent_of(session, submission)
    refusal = await redo_refusal(session, submission, tutor, marks, parent)
    if refusal is not None:
        raise refusal
    kind = kind_of(submission)
    snapshot: Snapshot = await build_snapshot(session, kind, submission, marks, parent)
    redo = AttemptRedo(
        organization_id=submission.work.organization_id,
        work_id=submission.work_id,
        student_id=submission.student_id,
        allowed_by_id=tutor.id,
        previous_submission_id=submission.id,
        previous_final_marks=snapshot.final_marks,
        previous_max_marks=snapshot.max_marks,
        record=snapshot.record,
    )
    session.add(redo)
    subject_id = submission.work.subject_id
    student_id = submission.student_id
    await _delete_attempt(session, kind, submission, marks, parent, snapshot.counts)
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


def _question_tallies(redo: AttemptRedo) -> tuple[int, int]:
    """(questions marked, questions on the attempt), read from the snapshot so no
    column was needed: a score over some of the questions must not read like a
    score over all of them."""
    entries = redo.record.get("marks", [])
    return sum(1 for e in entries if e.get("final_marks") is not None), len(entries)


async def _summaries(
    session: AsyncSession, rows: list[tuple[AttemptRedo, str, AssessableWork]]
) -> list[AttemptRedoOut]:
    titles = await _titles_by_work(session, [work for _, _, work in rows])
    out = []
    for redo, name, work in rows:
        marked, total = _question_tallies(redo)
        out.append(
            AttemptRedoOut(
                id=redo.id,
                created_at=redo.created_at,
                allowed_by_id=redo.allowed_by_id,
                allowed_by_name=name,
                work_kind=work.kind.value,
                work_title=titles.get(work.id) or work.title or "Untitled",
                previous_final_marks=redo.previous_final_marks,
                previous_max_marks=redo.previous_max_marks,
                previous_questions_marked=marked,
                previous_question_count=total,
            )
        )
    return out


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
