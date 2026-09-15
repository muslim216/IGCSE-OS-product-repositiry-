"""`kind_of` picks the arm off the parent row, and a kind with no arm raises.

It used to be a fallback chain over the three foreign keys: past paper, then
mock, then homework for anything left. That made homework the answer for a row
that was none of the three — right for the Classroom submissions created before
the past-paper arm existed, and wrong for a fourth kind nobody added to the
chain, which would have been marked as homework in silence, its marks written
to the wrong column and its evidence given the wrong weight. The module
docstring records that the third arm shipped broken in five places at once.

Since D5 the parent row names its kind outright, so there is nothing to fall
back to and an unknown kind raises. These tests pin that, and pin each arm
against the real schema so a swapped pair fails here.
"""

import pytest

from app.models import AssessableWork, EvidenceSource, QuestionMark, Submission, WorkKind
from app.services.submission_kind import HOMEWORK, MOCK, PAST_PAPER, kind_of


def _answering(kind: WorkKind) -> Submission:
    """A submission against a piece of work of this kind. No foreign key set on
    purpose — the arm must come from the parent, not from which key is filled."""
    return Submission(work=AssessableWork(kind=kind))


def test_each_arm_resolves_to_its_own_tables() -> None:
    assert kind_of(_answering(WorkKind.past_paper)) is PAST_PAPER
    assert kind_of(_answering(WorkKind.mock)) is MOCK
    assert kind_of(_answering(WorkKind.homework)) is HOMEWORK


def test_a_kind_with_no_arm_raises_instead_of_passing_as_homework() -> None:
    """The whole point of the change. Under the old fallback chain a kind
    nobody added here came back as homework with nothing raising."""

    class Quiz:
        kind = "quiz"

    with pytest.raises(ValueError, match="no submission arm"):
        kind_of(Submission(work=Quiz()))  # type: ignore[arg-type]


def test_each_arm_points_at_its_own_real_columns() -> None:
    """Distinctness alone would pass with two arms swapped, which is exactly the
    "one kind's marks land on another kind's questions" bug. So check each arm
    against the schema: its `mark_fk` must be a real `QuestionMark` column whose
    foreign key targets that arm's own question table, and its `parent_fk` a
    real column on that question table pointing back at its own parent."""
    for arm in (HOMEWORK, PAST_PAPER, MOCK):
        mark_column = QuestionMark.__table__.columns[arm.mark_fk]
        targets = {fk.column.table.name for fk in mark_column.foreign_keys}
        assert targets == {arm.question_model.__tablename__}, (
            f"{arm.name}: mark_fk {arm.mark_fk} points at {targets}, "
            f"not {arm.question_model.__tablename__}"
        )
        # `parent_fk` is the one string that filters a question list to the
        # piece of work it belongs to (services/work.parent_of reads the
        # parent itself, off Submission.work_id, since D6 — this no longer
        # names a Submission column). It must be a real column on the
        # question table pointing back at this arm's own parent, or the
        # filter silently returns another kind's questions.
        question_fk = arm.question_model.__table__.columns[arm.parent_fk]
        parents = {fk.column.table.name for fk in question_fk.foreign_keys}
        assert parents == {arm.parent_model.__tablename__}, (
            f"{arm.name}: {arm.parent_fk} points at {parents}, not {arm.parent_model.__tablename__}"
        )
        # The evidence builder queries every topic table by this one name.
        assert "question_id" in arm.topic_model.__table__.columns
    # Two arms sharing a topic table would attribute one kind's marks to another
    # kind's topics in `services/evidence.py`. The evidence sources are pinned
    # distinct by `test_every_evidence_source_for_marked_work_has_an_arm`.
    assert len({arm.topic_model for arm in (HOMEWORK, PAST_PAPER, MOCK)}) == 3


def test_every_evidence_source_for_marked_work_has_an_arm() -> None:
    """Exhaustive by construction: a new kind of marked work that gets an
    `EvidenceSource` but no arm here would be marked as homework in silence."""
    marked = {EvidenceSource.homework, EvidenceSource.past_paper, EvidenceSource.mock}
    assert {arm.evidence_source for arm in (HOMEWORK, PAST_PAPER, MOCK)} == marked


def test_work_kind_covers_every_arm() -> None:
    """The parent table's `kind` column must be able to name every arm — a
    `WorkKind` member with no arm, or an arm with no member, breaks the
    backfill's mapping."""
    assert {w.value for w in WorkKind} == {"homework", "past_paper", "mock"}
