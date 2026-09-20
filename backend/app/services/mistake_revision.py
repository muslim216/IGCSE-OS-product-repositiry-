"""A tutor changing a mistake the tagging job wrote (task 4.3, `AV-38`).

No prompt, no queue, no blocking step: the tutor is never asked to review a
tag, and nothing waits on them doing it. `tag_mistakes` proposes, this module
is the only way a human changes what it proposed, and either way the mistake
counts towards readiness immediately (`AV-37`).

**A revision edits the row in place and flips `source` to `tutor`.** It does
not write a second row. That is E17's whole mechanism: the next run of
`tag_mistakes` deletes only its own `source="ai"` rows, so flipping the column
is what puts this mistake out of the job's reach for good — no extra flag, and
no reader anywhere has to learn a rule about which of two rows on one question
wins (`_mistake_points_and_analysed` still counts every mistake it finds, and
still must not filter on `source`).

Scope is deliberately narrow: the category and the severity of a mistake that
already exists. There is no way here to tag a question the job left alone, or
to remove a tag — `AV-38` is "the tutor may revise any of them", and neither
of the others has been asked for.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssessableWork,
    Mistake,
    MistakeCategory,
    MistakeRevisionAudit,
    MistakeSource,
    QuestionMark,
    Submission,
    User,
)


class RevisionRejected(Exception):
    """The revision names something this tutor may not revise, or may not
    revise it to. The router turns this into a 404 — every id involved is an
    enumerable integer, and "this category exists but is not yours" is not a
    thing to confirm to a caller (`API-7`, `SEC-9`)."""


async def revise_mistake(
    session: AsyncSession,
    submission: Submission,
    mistake_id: int,
    category_id: int,
    severity: int,
    tutor: User,
) -> bool:
    """Repoint one mistake at a different category and/or severity. Returns
    whether anything actually changed.

    `submission` is the row the caller has already proved this tutor owns; the
    mistake is re-read here against it rather than trusted from the path, so a
    mistake id belonging to another student's work cannot be revised through a
    submission this tutor does happen to own (`SEC-7`).
    """
    mistake = await session.scalar(
        select(Mistake)
        .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
        .where(Mistake.id == mistake_id, QuestionMark.submission_id == submission.id)
        # Locked for the rest of the transaction, because the audit row below
        # records the values read *here* as the "old" ones. Two revisions of
        # one mistake landing together would otherwise both read the same
        # state, both claim to have moved it from there, and the second write
        # would erase the first with nothing in the trail saying so — the
        # append-only record `PROD-7` requires would be quietly wrong rather
        # than merely incomplete. `of=Mistake` keeps the lock off the joined
        # `question_marks` row, which a tutor saving marks holds at the same
        # time. SQLite renders no `FOR UPDATE` at all, so this is exercised
        # only by CI's Postgres job (`RISK-3`).
        .with_for_update(of=Mistake)
    )
    if mistake is None:
        raise RevisionRejected("Mistake not found")

    work = await session.get(AssessableWork, submission.work_id)
    assert work is not None, f"submission {submission.id} has no work row"
    category = await session.scalar(
        select(MistakeCategory).where(
            MistakeCategory.id == category_id,
            # The organization comes from the authenticated tutor, never from
            # the work row (`SEC-7`). `assessable_work.organization_id` is a
            # copy, and the mock arm of `_tutor_owns` authorizes on
            # `parent.tutor_id` with no organization check at all — so a work
            # row whose org had drifted from its tutor's would resolve
            # categories in the other tenant. The subject does come off the
            # work: a subject is global, and (organization, subject) together
            # are what scopes a category (`SEC-8`).
            MistakeCategory.organization_id == tutor.organization_id,
            MistakeCategory.subject_id == work.subject_id,
            # Archived categories are hidden from new tagging and from the
            # editor, so moving a mistake *onto* one would put it on a word the
            # tutor has retired and can no longer see in any list.
            #
            # Staying on one is different, and is allowed: a mistake tagged
            # before the category was archived keeps it and keeps counting —
            # archiving is not deletion (glossary) — so the tutor must be able
            # to revise that mistake's *severity* without being forced to move
            # it onto some other category they did not want to change it to.
            # That is only expressible if resending the current category is
            # accepted.
            (MistakeCategory.archived_at.is_(None)) | (MistakeCategory.id == mistake.category_id),
        )
    )
    if category is None:
        raise RevisionRejected("Mistake category not found")

    if mistake.category_id == category_id and mistake.severity == severity:
        # Nothing changed. Returning early rather than writing an X -> X audit
        # row keeps the trail to actual decisions; a re-sent save or a
        # double-click is not one.
        #
        # It also means a tutor cannot express "the AI got this right, leave
        # it alone" — endorsing a tag without changing it would need
        # `Mistake.confirmed_by_tutor`, which nothing in the codebase reads or
        # writes. Out of scope for `AV-38`, which is about revising.
        return False

    session.add(
        MistakeRevisionAudit(
            mistake_id=mistake.id,
            old_category_id=mistake.category_id,
            new_category_id=category_id,
            old_severity=mistake.severity,
            new_severity=severity,
            changed_by_id=tutor.id,
        )
    )
    mistake.category_id = category_id
    mistake.severity = severity
    # The tutor's judgement now, not the AI's proposal — and past the reach of
    # `_delete_own_mistakes` (E17). Set even when only the severity moved:
    # what makes a row the tutor's is that a human decided it, not which of
    # its columns they touched.
    mistake.source = MistakeSource.tutor
    await session.flush()
    return True
