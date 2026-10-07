"""The snapshot a tutor's redo writes into `AttemptRedo.record`.

Built from the *locked* mark rows the redo hands in, never from a collection
loaded earlier, so what is recorded is exactly what is then deleted. Every
column of every row is carried (`row`) rather than a hand-picked list, so a
column added to one of these tables later is recorded without anyone having to
remember this module.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Evidence,
    MarkOverrideAudit,
    Mistake,
    MistakeCategory,
    MistakeTopic,
    MockOpening,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    Submission,
)
from app.services.submission_kind import MOCK, PAST_PAPER, SubmissionKind

#: Bumped when the shape of `AttemptRedo.record` changes, so a reader months
#: from now knows which shape it is holding.
RECORD_VERSION = 1


def evidence_ref(submission_id: int) -> str:
    """The `source_ref` evidence built from a submission carries (`services/evidence.py`)."""
    return f"submission:{submission_id}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def row(obj: Any) -> dict[str, Any]:
    """Every column of a row, datetimes as ISO strings."""
    return {
        attr.key: _jsonable(getattr(obj, attr.key)) for attr in sa_inspect(obj).mapper.column_attrs
    }


@dataclass(frozen=True)
class SnapshotCounts:
    """How many rows the snapshot holds of each kind the redo then deletes, so
    the deletes can be checked against it: a different count means something
    wrote to the attempt between the snapshot and the delete."""

    marks: int
    audit: int
    remarks: int
    mistakes: int
    topic_links: int
    evidence: int


@dataclass(frozen=True)
class Snapshot:
    record: dict[str, Any]
    final_marks: int | None
    max_marks: int | None
    counts: SnapshotCounts


async def _audit_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, list[dict]]:
    rows = await session.scalars(
        select(MarkOverrideAudit)
        .where(MarkOverrideAudit.question_mark_id.in_(mark_ids))
        .order_by(MarkOverrideAudit.id)
    )
    grouped: dict[int, list[dict]] = {}
    for audit in rows:
        grouped.setdefault(audit.question_mark_id, []).append(row(audit))
    return grouped


async def _remark_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, dict]:
    rows = await session.scalars(
        select(RemarkRequest).where(RemarkRequest.question_mark_id.in_(mark_ids))
    )
    return {remark.question_mark_id: row(remark) for remark in rows}


async def _mistakes_by_mark(session: AsyncSession, mark_ids: list[int]) -> dict[int, list[dict]]:
    rows = (
        await session.execute(
            select(Mistake, MistakeCategory.name)
            .join(MistakeCategory, MistakeCategory.id == Mistake.category_id)
            .where(Mistake.question_mark_id.in_(mark_ids))
            .order_by(Mistake.id)
        )
    ).all()
    links: dict[int, list[MistakeTopic]] = {}
    mistake_ids = [mistake.id for mistake, _ in rows]
    if mistake_ids:
        for link in await session.scalars(
            select(MistakeTopic)
            .where(MistakeTopic.mistake_id.in_(mistake_ids))
            .order_by(MistakeTopic.id)
        ):
            links.setdefault(link.mistake_id, []).append(link)
    grouped: dict[int, list[dict]] = {}
    for mistake, category_name in rows:
        mine = links.get(mistake.id, [])
        entry = {
            **row(mistake),
            "category_name": category_name,
            "topic_ids": [link.topic_id for link in mine],
            "topic_links": [row(link) for link in mine],
        }
        grouped.setdefault(mistake.question_mark_id, []).append(entry)
    return grouped


async def _questions_by_mark(
    session: AsyncSession, kind: SubmissionKind, marks: Sequence[QuestionMark]
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
    session: AsyncSession, kind: SubmissionKind, marks: Sequence[QuestionMark]
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
            **row(mark),
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
        extras["mock_opening"] = row(opening) if opening is not None else None
    if kind is PAST_PAPER:
        rollup = await session.scalar(
            select(PastPaperAttempt).where(
                PastPaperAttempt.past_paper_id == parent.id,
                PastPaperAttempt.student_id == submission.student_id,
            )
        )
        extras["past_paper_attempt"] = row(rollup) if rollup is not None else None
    return extras


def _counts(entries: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> SnapshotCounts:
    mistakes = [m for entry in entries for m in entry["mistakes"]]
    return SnapshotCounts(
        marks=len(entries),
        audit=sum(len(entry["override_audit"]) for entry in entries),
        remarks=sum(1 for entry in entries if entry["remark_request"] is not None),
        mistakes=len(mistakes),
        topic_links=sum(len(m["topic_links"]) for m in mistakes),
        evidence=len(evidence),
    )


async def build_snapshot(
    session: AsyncSession,
    kind: SubmissionKind,
    submission: Submission,
    marks: Sequence[QuestionMark],
    parent: Any,
) -> Snapshot:
    entries = await _mark_entries(session, kind, marks)
    evidence = [
        row(item)
        for item in await session.scalars(
            select(Evidence)
            .where(Evidence.source_ref == evidence_ref(submission.id))
            .order_by(Evidence.id)
        )
    ]
    final_marks, max_marks = _final_totals(entries)
    record = {
        "version": RECORD_VERSION,
        "kind": kind.work_kind.value,
        "work": {"id": submission.work_id, "title": submission.work.title},
        "submission": row(submission),
        "files": [row(file) for file in submission.files],
        "marks": entries,
        "evidence": evidence,
        **await _kind_extras(session, kind, submission, parent),
    }
    return Snapshot(record, final_marks, max_marks, _counts(entries, evidence))
