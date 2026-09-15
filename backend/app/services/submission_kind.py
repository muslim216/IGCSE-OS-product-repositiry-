"""What kind of thing a `Submission` is, in one place.

A submission answers one piece of work, named by `work_id`, and the parent row
says which kind of work that is. Four call sites need the same four answers off
the back of it — which question table the marks hang off, which topic-tag
table, which `QuestionMark` column points at the question, and which
`EvidenceSource` the finalized marks become. The branch is written once here
and the answers travel as data.

How it used to be, because the shape of the code still carries the scars: a
submission held three nullable foreign keys — `assignment_id`, `past_paper_id`,
`mock_id` — with exactly one set, and every reader worked the kind out from
whichever was filled in. Each site started by writing that test itself, as
`past_paper_id is not None`. Two arms fit in an `if`/`else`; three did not, and
four copies of a three-way branch were four chances to add the next arm in only
three of them. Worse, the chain ended in homework as the leftover, so an arm
nobody added came back as homework with nothing raising.

The cross-kind queries had the matching problem and it was the expensive one.
`review_queue` and `review_queue_predicate`, `today.pending_review_count` and
`activity.tutor_scope` each joined all three arms and ORed three
`organization_id` columns. An arm missing from one of those ORs did not fail —
it silently vanished from that queue, count or feed. That is how the third arm
shipped broken in five places at once.

`assessable_work` (migrations `0046`–`0049`) is what closed it. Whose work it
is comes from the parent's one `organization_id` (D4); what kind it is comes
from the parent's `kind` (D5); and the three old keys are gone (D6), so there
is no second answer to disagree with. A fourth kind of work needs a `WorkKind`
member, an arm here, and nothing else — no column on `submissions`, no edit to
any cross-kind query.

What is still per-kind is *display*: `activity._polymorphic_submissions` and
the review queue left-join all three to read each kind's own title, and
`_work_title` branches. That branch does not fail loudly — a kind it does not
know renders as the word "Work", and a past paper with no extracted title as
"Untitled paper". Wrong in front of a tutor rather than silently inside a
scope, which is why it is what remains.

The arm-to-parent mapping is deliberately NOT here. The D2 backfill is a
migration, and no migration in this repo imports app code (`DB-15`) — it
spells the three arms out in literal SQL. This module gains a field when a
service-layer reader actually needs one, not before — `parent_model` was
deliberately absent until D3's `open_attempt` needed to read a parent's
`work_id`.

Pure by `BE-4`: model classes and strings in, no session, no I/O.
"""

from dataclasses import dataclass
from typing import Any

from app.models import (
    Assignment,
    AssignmentQuestion,
    EvidenceSource,
    Mock,
    MockQuestion,
    MockQuestionTopic,
    PastPaper,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    QuestionTopic,
    Submission,
    WorkKind,
)


@dataclass(frozen=True)
class SubmissionKind:
    """The tables and the evidence source behind one arm of `Submission`."""

    name: str
    #: The parent table's word for this arm. Since D5 this is what picks the
    #: arm — `kind_of` reads it off the parent row rather than working out
    #: which of the three foreign keys happens to be set.
    work_kind: WorkKind
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
    #: The column on `question_model` naming this arm's parent — the one
    #: string that filters a question list to the piece of work it belongs to.
    #: It named a `Submission` column of the same spelling too, until D6 took
    #: the three old keys off submissions; the value it is compared against now
    #: comes from the parent row (`services/work.parent_of`).
    parent_fk: str
    #: What finalized marks from this kind weigh as in readiness. A mock counts
    #: as a mock whether the tutor typed the score in or the AI marked the
    #: paper — the weight follows the exam, not the marking channel.
    evidence_source: EvidenceSource
    #: The model holding this arm's parent row — `Assignment`, `PastPaper` or
    #: `Mock`. `open_attempt` loads it to read its `work_id`, and
    #: `services/work.parent_of` loads it back again from that `work_id` —
    #: which is the whole of how a submission and its paper find each other
    #: since D6. `type[Any]` for the same reason as `question_model`: the three
    #: already agree on the shape used here.
    parent_model: type[Any]


HOMEWORK = SubmissionKind(
    name="homework",
    work_kind=WorkKind.homework,
    question_model=AssignmentQuestion,
    topic_model=QuestionTopic,
    mark_fk="question_id",
    evidence_source=EvidenceSource.homework,
    parent_fk="assignment_id",
    parent_model=Assignment,
)

PAST_PAPER = SubmissionKind(
    name="past paper",
    work_kind=WorkKind.past_paper,
    question_model=PastPaperQuestion,
    topic_model=PastPaperQuestionTopic,
    mark_fk="past_paper_question_id",
    evidence_source=EvidenceSource.past_paper,
    parent_fk="past_paper_id",
    parent_model=PastPaper,
)

MOCK = SubmissionKind(
    name="mock",
    work_kind=WorkKind.mock,
    question_model=MockQuestion,
    topic_model=MockQuestionTopic,
    mark_fk="mock_question_id",
    evidence_source=EvidenceSource.mock,
    parent_fk="mock_id",
    parent_model=Mock,
)


_BY_WORK_KIND = {arm.work_kind: arm for arm in (HOMEWORK, PAST_PAPER, MOCK)}


def kind_of(submission: Submission) -> SubmissionKind:
    """Which arm this submission is, read off its parent row.

    This used to be a fallback chain over the three foreign keys — past paper,
    then mock, then homework for everything left. That made homework the answer
    for a row that was none of the three, which was right for the Classroom
    rows created before the past-paper arm existed, and wrong for a fourth kind
    of work nobody added to the chain: it would have been marked as homework in
    silence, its marks written to the wrong column and its evidence given the
    wrong weight.

    A parent row names its kind outright, so there is nothing to fall back to.
    A kind with no arm here raises instead, which is the loud failure the chain
    could not give (`PROD-1`). `Submission.work` is eagerly loaded, so this
    stays a plain attribute read with no session (`BE-4`).

    One edge to know about: the eager load fills `work` when a submission is
    read back from the database. A submission built in Python with `work_id`
    alone has nothing there yet, and reading it under async raises
    `MissingGreenlet` rather than answering. Building it with `work=<the parent
    row>` is fine, and so is re-reading the submission — which is what every
    caller here does.
    """
    arm = _BY_WORK_KIND.get(submission.work.kind)
    if arm is None:
        raise ValueError(
            f"no submission arm for work kind {submission.work.kind!r} — add one to "
            "services/submission_kind.py alongside its question and topic tables"
        )
    return arm
