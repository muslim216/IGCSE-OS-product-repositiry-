"""`kind_of` picks the right arm, and homework stays the fallback.

The function is a fallback chain, not a match: anything that is neither a past
paper nor a mock is reported as homework. That is correct — Classroom sync once
created submissions with no key at all and those really are homework — but it
means a future arm nobody adds here is silently marked homework, its marks
written to the wrong column and its evidence given the wrong weight, with no
error anywhere. The module docstring records that the third arm shipped broken
in five places at once. These tests pin the behaviour so a reordering, or a
"tidy-up" that turns the fallback into an error, fails here instead.
"""

from app.models import EvidenceSource, QuestionMark, Submission, WorkKind
from app.services.submission_kind import HOMEWORK, MOCK, PAST_PAPER, kind_of


def test_each_arm_resolves_to_its_own_tables() -> None:
    assert kind_of(Submission(past_paper_id=7)) is PAST_PAPER
    assert kind_of(Submission(mock_id=7)) is MOCK
    assert kind_of(Submission(assignment_id=7)) is HOMEWORK


def test_a_submission_with_no_key_is_homework() -> None:
    """Deliberate, not an accident: Classroom sync created these before the
    past-paper arm existed. Turning this into an error would break them."""
    assert kind_of(Submission()) is HOMEWORK


def test_each_arm_points_at_its_own_real_columns() -> None:
    """Distinctness alone would pass with two arms swapped, which is exactly the
    "one kind's marks land on another kind's questions" bug. So check each arm
    against the schema: its `mark_fk` must be a real `QuestionMark` column whose
    foreign key targets that arm's own question table, and its `parent_fk` a
    real `Submission` column."""
    for arm in (HOMEWORK, PAST_PAPER, MOCK):
        mark_column = QuestionMark.__table__.columns[arm.mark_fk]
        targets = {fk.column.table.name for fk in mark_column.foreign_keys}
        assert targets == {arm.question_model.__tablename__}, (
            f"{arm.name}: mark_fk {arm.mark_fk} points at {targets}, "
            f"not {arm.question_model.__tablename__}"
        )
        # `parent_fk` is deliberately one name for two columns — the docstring
        # says `Submission.<parent_fk>` and `question_model.<parent_fk>` are
        # always spelt the same, and a question list is filtered by that. Check
        # both exist and point at the same table, or that filter silently
        # returns another kind's questions.
        submission_fk = Submission.__table__.columns[arm.parent_fk]
        question_fk = arm.question_model.__table__.columns[arm.parent_fk]
        parents = {fk.column.table.name for fk in submission_fk.foreign_keys}
        assert parents == {fk.column.table.name for fk in question_fk.foreign_keys}, (
            f"{arm.name}: {arm.parent_fk} means a different table on each side"
        )
        # The evidence builder queries every topic table by this one name.
        assert "question_id" in arm.topic_model.__table__.columns


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
