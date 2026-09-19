"""Examining a settled submission for recurring mistakes (4.2, AV-40).

Its own job rather than a step of marking: `mark_submission` skips the AI
call entirely once every question is already decided
(`services/marking.py:397-400`), and the most common way a submission
becomes settled — a tutor finalizing the review queue — reaches no model at
all. Something else has to look, once, after the marks are in.

`submissions.mistakes_analysed_at` is the whole of what tells the Mistake
Analysis readiness factor "examined, nothing wrong" apart from "nobody has
looked yet" (`services/readiness_factors.py:244-275` reads `NO_DATA` from the
second). Task 4.0 exists because the factor used to read the two the same
way — a hardcoded 100.0 for an empty `mistakes` table, whether or not
anything had ever been marked. Every early return in this module either sets
that column because the submission really was examined, or leaves it null
because it was not — never the reverse, and never by omission.

This module currently stops before the AI call: every path here is one that
does not need the model, and each is a place where the wrong behaviour is
silence rather than an error. The call itself, the categories it may use, and
the topics it tags are task 4.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MistakeCategory, QuestionMark, Submission
from app.models.base import utcnow
from app.services.mistake_categories import ensure_categories, list_categories
from app.services.submission_kind import kind_of
from app.services.work import parent_of

log = logging.getLogger("mistake_tagging")


async def _categories_for_subject(
    session: AsyncSession, organization_id: int, subject_id: int
) -> list[MistakeCategory]:
    """`ensure_categories`, made safe for two tagging jobs reaching an empty
    subject at once.

    `ensure_categories` decides "this subject has never had a category" with
    a plain existence check and no lock (`services/mistake_categories.py`).
    This is its only caller anywhere — it was written for 4.2 and nothing has
    ever called it before — and `tag_mistakes` is queued from marking, so it
    can fire for two submissions in the same subject within one poll. Both jobs can pass
    that check before either commits, both try to insert the five defaults,
    and the second's flush loses to `uq_mistake_categories_org_subject_lower_name`.
    This job is that index's first production caller (nothing wrote to
    `mistakes` before 4.2), so this is where the race becomes reachable.

    Losing the insert is not losing the categories — the winner's rows are
    exactly what this call wanted — so a caught IntegrityError rolls back
    (required before the session can be used again after a failed flush) and
    re-reads rather than failing a run that has nothing wrong with it.
    """
    try:
        return await ensure_categories(session, organization_id, subject_id)
    except IntegrityError:
        await session.rollback()
        recovered = await list_categories(session, organization_id, subject_id)
        if recovered:
            # Deliberately does not say *who* won. Any committed writer can
            # take a name this insert wanted: a second tagging job, or a tutor
            # saving their own list for the first time through
            # `save_categories`. Both commit atomically, so whatever is there
            # is somebody's complete, deliberate list — and a tutor's own list
            # is the better answer than the published defaults, not a worse
            # one. Naming the winner in the log would be a guess, and a guess
            # in a log is read as a fact later.
            log.info(
                "tag_mistakes: subject %s already had %s categories committed by "
                "the time this run tried to write the defaults; using those",
                subject_id,
                len(recovered),
            )
            return recovered
        # The premise of this recovery is that somebody else's rows are already
        # there. If nothing is, it was not the race — it was some other
        # integrity failure, and returning an empty list would send the caller
        # down the "this tutor archived everything" path: analysed, tagged with
        # nothing, `mistakes_analysed_at` set, and the factor reading a clean
        # examination that never happened. That is precisely the failure 4.0
        # existed to close, so it is raised rather than absorbed. The worker
        # retries once and then records the job failed, which is a thing
        # somebody can find (`PROD-2`, `BE-6`).
        raise


async def tag_mistakes(session: AsyncSession, payload: dict) -> None:
    """Job handler. payload: {"submission_id": int}.

    Re-runnable by contract (`BE-6`): the payload names a submission and
    nothing else (`BE-9`), every read below is fresh off the database, and
    (from task 4 on) the write step replaces only `source="ai"` rows, never a
    tutor's own tags (E17, decision 8).
    """
    submission_id = payload["submission_id"]
    submission = await session.get(Submission, submission_id)
    if submission is None:
        # Deleted between enqueue and claim. Nothing to analyse and nothing
        # wrong — a raise here would retry forever against a missing row.
        return

    kind = kind_of(submission)
    work = submission.work  # AssessableWork: organization_id, subject_id
    organization_id = work.organization_id
    subject_id = work.subject_id

    parent = await parent_of(session, submission)
    # Loud, not quiet. A work row with no matching child breaks an invariant
    # `services/work.create_work` exists to make impossible (`API-20`), and
    # `services/marking.py` asserts on exactly this at all four of its call
    # sites rather than returning. The deleted-submission case above is a
    # routine race and stays silent; this is data corruption, and returning
    # quietly would leave it a permanent no-op with no trace — the same
    # argument `_categories_for_subject` makes for re-raising an integrity
    # error it cannot explain. The worker records a failed job, which is the
    # only record that a piece of a student's work stopped moving.
    assert parent is not None, f"submission {submission_id} has work with no parent row"

    questions = {
        q.id: q
        for q in (
            await session.scalars(
                select(kind.question_model).where(
                    getattr(kind.question_model, kind.parent_fk) == parent.id
                )
            )
        ).all()
    }
    marks = {
        getattr(m, kind.mark_fk): m
        for m in (
            await session.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission.id)
            )
        ).all()
    }

    settled = [m for m in marks.values() if m.final_marks is not None]
    if not settled:
        return  # still in the queue; absence stays absence (PROD-2)

    # Deliberately "any decided", not "all decided", and not a check on
    # `SETTLED_STATUSES`. Auto-finalize leaves a real mixed state — some marks
    # final, others waiting on the tutor, submission `needs_review` — and
    # tagging the decided half then is useful, not premature.
    #
    # It is safe because the readiness side gates twice. `_mistake_points_and_
    # analysed` counts a submission only when its status is in
    # SETTLED_STATUSES *and* `mistakes_analysed_at` is set, so a half-tagged
    # `needs_review` submission contributes nothing at all — not a partial
    # score, nothing. And when the tutor finalizes it, `record_marks_as_
    # evidence` enqueues this job again (task 6) and the re-run replaces its
    # own rows over the full list (E17).
    #
    # A stricter gate here would block that useful middle state without
    # closing any hole, because the hole is already closed on the reading
    # side. Worth re-checking if anything ever counts a submission that is not
    # in SETTLED_STATUSES.

    # Every settled mark that lost at least one mark against its question's
    # max — the questions this run would have something to tag. A mark whose
    # question id has no match in `questions` (a dangling FK, never expected)
    # is skipped rather than raising: there is nothing to tag it against.
    # Computed before `_categories_for_subject` below on purpose: its race
    # recovery rolls back the session on a lost race, which expires every
    # object already loaded on it (`BE-6`'s re-run safety is what makes that
    # recovery necessary at all) — reading `m`/`q` attributes afterward would
    # reload them with a synchronous lazy load async forbids
    # (`MissingGreenlet`). Reading them here, first, sidesteps that rather
    # than working around it after the fact.
    lost = [
        (m, q)
        for m in settled
        if (q := questions.get(getattr(m, kind.mark_fk))) is not None
        and m.final_marks < q.max_marks
    ]
    orphaned = [m for m in settled if questions.get(getattr(m, kind.mark_fk)) is None]
    if orphaned:
        # Should be unreachable: extraction only replaces a question list
        # before anything can have been marked against it. But this suite runs
        # SQLite with foreign keys off, so a dangling question id would raise
        # nothing here, and the mark would simply vanish from `lost` — a
        # question the student got wrong, silently never examined. Logged
        # rather than raised, because the rest of the submission is still worth
        # tagging, and a warning is the difference between "never happened" and
        # "happened and nobody could tell".
        log.warning(
            "tag_mistakes: submission %s has %s mark(s) pointing at questions "
            "that are not on its %s; they cannot be tagged",
            submission_id,
            len(orphaned),
            kind.name,
        )
    categories = await _categories_for_subject(session, organization_id, subject_id)

    if not lost or not categories:
        # Analysed, and the answer is nothing — recorded rather than left
        # blank, because the readiness factor reads a blank as "no evidence"
        # (PROD-2, the whole reason this column exists).
        if not categories:
            # A tutor who archived every category chose that
            # (`ensure_categories`'s contract) — calling the model with an
            # empty list would spend a request only to have every tag it
            # proposed dropped as unrecognised, with nothing telling anyone
            # why the factor went dark. Logged, not raised: this is the
            # subject's tutor's own choice, not a fault.
            log.info(
                "tag_mistakes: subject %s has no mistake categories; "
                "analysed submission %s with no tagging and no model call",
                subject_id,
                submission_id,
            )
        submission.mistakes_analysed_at = utcnow()
        await session.commit()
        return

    # Task 4 picks up here: the AI call over `lost`, using `categories` and
    # each question's topics (kind.topic_model), writing Mistake/MistakeTopic
    # rows with source=MistakeSource.ai, then setting mistakes_analysed_at.
