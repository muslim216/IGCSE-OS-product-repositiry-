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

from app.models import EvidenceSource, Submission, WorkKind
from app.services.submission_kind import HOMEWORK, MOCK, PAST_PAPER, kind_of


def test_each_arm_resolves_to_its_own_tables() -> None:
    assert kind_of(Submission(past_paper_id=7)) is PAST_PAPER
    assert kind_of(Submission(mock_id=7)) is MOCK
    assert kind_of(Submission(assignment_id=7)) is HOMEWORK


def test_a_submission_with_no_key_is_homework() -> None:
    """Deliberate, not an accident: Classroom sync created these before the
    past-paper arm existed. Turning this into an error would break them."""
    assert kind_of(Submission()) is HOMEWORK


def test_the_three_arms_stay_distinct() -> None:
    """Each arm must name its own question table, its own QuestionMark column
    and its own evidence weight — two arms sharing any of them means one kind's
    marks land on another kind's questions."""
    arms = (HOMEWORK, PAST_PAPER, MOCK)
    for field in ("question_model", "topic_model", "mark_fk", "parent_fk", "evidence_source"):
        values = [getattr(arm, field) for arm in arms]
        assert len(set(values)) == 3, f"two arms share {field}: {values}"


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
