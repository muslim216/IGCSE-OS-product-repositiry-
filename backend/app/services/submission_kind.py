"""What kind of thing a `Submission` is, in one place.

`Submission` is polymorphic (`API-20`): exactly one of `assignment_id`,
`past_paper_id` and `mock_id` is set. Four call sites need the same four
answers off the back of that discriminator — which question table the marks
hang off, which topic-tag table, which `QuestionMark` column points at the
question, and which `EvidenceSource` the finalized marks become.

Before task 3.4 each site rewrote the test as `past_paper_id is not None` and
picked its own answers inline. Two arms fit in an `if`/`else`; three do not,
and four copies of a three-way branch is four chances to add the next arm in
three places. So the branch is written once here and the answers travel as
data. A fourth kind is a new constant and one line in `kind_of` — nothing in
marking, evidence or the router changes.

Pure by `BE-4`: model classes and strings in, no session, no I/O.
"""

from dataclasses import dataclass
from typing import Any

from app.models import (
    AssignmentQuestion,
    EvidenceSource,
    MockQuestion,
    MockQuestionTopic,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    QuestionTopic,
    Submission,
)


@dataclass(frozen=True)
class SubmissionKind:
    """The tables and the evidence source behind one arm of `Submission`."""

    name: str
    #: The model holding this kind's questions. `type[Any]` rather than a
    #: Protocol: the three question models already agree on the shape this
    #: module needs — `id`, `max_marks`, and a `<parent_fk>` column — and the
    #: tests that mark each kind are what prove it, not a second declaration of
    #: the same four attributes.
    question_model: type[Any]
    #: The model tagging those questions with topics. Every one of the three
    #: names its foreign key `question_id`, which is what lets the evidence
    #: builder query them without knowing which it has.
    topic_model: type[Any]
    #: The `QuestionMark` column that points at `question_model`.
    mark_fk: str
    #: The column naming this arm's parent. Deliberately one name for two
    #: columns: `Submission.<parent_fk>` and `question_model.<parent_fk>` are
    #: always spelt the same, so one string filters a question list by the
    #: submission that owns it.
    parent_fk: str
    #: What finalized marks from this kind weigh as in readiness. A mock counts
    #: as a mock whether the tutor typed the score in or the AI marked the
    #: paper — the weight follows the exam, not the marking channel.
    evidence_source: EvidenceSource


HOMEWORK = SubmissionKind(
    name="homework",
    question_model=AssignmentQuestion,
    topic_model=QuestionTopic,
    mark_fk="question_id",
    evidence_source=EvidenceSource.homework,
    parent_fk="assignment_id",
)

PAST_PAPER = SubmissionKind(
    name="past paper",
    question_model=PastPaperQuestion,
    topic_model=PastPaperQuestionTopic,
    mark_fk="past_paper_question_id",
    evidence_source=EvidenceSource.past_paper,
    parent_fk="past_paper_id",
)

MOCK = SubmissionKind(
    name="mock",
    question_model=MockQuestion,
    topic_model=MockQuestionTopic,
    mark_fk="mock_question_id",
    evidence_source=EvidenceSource.mock,
    parent_fk="mock_id",
)


def kind_of(submission: Submission) -> SubmissionKind:
    """Which arm this submission is. Homework is the fallback because it is the
    only arm whose key can be absent on a legitimately old row — Classroom sync
    once created submissions before the past-paper arm existed."""
    if submission.past_paper_id is not None:
        return PAST_PAPER
    if submission.mock_id is not None:
        return MOCK
    return HOMEWORK
