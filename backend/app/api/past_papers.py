"""Past papers: tutor uploads the paper once, students self-log their attempts.

A past paper rides the same pipeline as homework — extract questions, AI-mark
the student's pages, auto-finalize what's confident, queue the rest for the
tutor — because a student's attempt *is* a Submission (see models/homework.py).
That means the review queue, mark-override audit and remark requests all apply
here with no extra code.

Two rules specific to past papers:
- **The official mark scheme is optional at upload.** It used to be mandatory,
  on the reasoning that past-paper marks feed a predicted grade and may not rest
  on the AI's own judgement. That reasoning is enforced by marking, not by this
  endpoint: with no scheme file attached nothing auto-finalizes (see
  `upload_past_paper`), so the tutor rules on every mark by hand.
- **The mark scheme is tutor-only.** Students can read the question paper.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import and_, false, func, or_, select

from app.api.deps import CurrentUser, DbSession, StudentUser, TutorUser, owned_subject
from app.api.file_responses import FILE_RESPONSES, signed_or_proxied_file
from app.models import (
    SETTLED_STATUSES,
    Booklet,
    BookletStatus,
    Group,
    GroupMember,
    PastPaper,
    PastPaperAttempt,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    Subject,
    Submission,
    SubmissionFile,
    Topic,
    User,
    UserRole,
    WorkKind,
)
from app.models.base import utcnow
from app.schemas.groups import TopicOut
from app.schemas.past_paper import (
    PastPaperAttemptOut,
    PastPaperDetail,
    PastPaperOut,
    PastPaperQuestionOut,
)
from app.services import storage
from app.services.attempts import open_attempt
from app.services.extraction import queue_past_paper_read, read_in_progress
from app.services.submission_kind import PAST_PAPER
from app.services.work import create_work, parent_of
from app.workers.jobs import enqueue

log = logging.getLogger("api")

router = APIRouter(prefix="/past-papers", tags=["past-papers"])


async def _enrolled_scope(db, student_id: int) -> set[tuple[int, int]]:
    """The (organization_id, subject_id) pairs a student is actually taught in.

    Subjects are global — every organization shares the same five built-in
    syllabuses — so enrollment alone does not bound what a student may see.
    Scoping on the pair keeps one tutor's uploads inside that tutor's
    organization; matching on subject alone would show a student every past
    paper any tutor anywhere had uploaded for their subject.

    The pair comes from the groups the student is in rather than from
    `user.organization_id`, so a student who joined a second tutor's group with
    an invite (which does not move their organization) still sees that tutor's
    papers, and only that tutor's.
    """
    rows = (
        await db.execute(
            select(Group.organization_id, Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            # A deleted class gives no access to the organization's papers; a
            # student with another live class in the subject keeps them.
            .where(GroupMember.student_id == student_id, Group.deleted_at.is_(None))
        )
    ).all()
    return {(org_id, subject_id) for org_id, subject_id in rows}


async def _visible_paper(
    db, user: User, past_paper_id: int, *, own_attempt_ok: bool = False
) -> PastPaper:
    """A tutor sees their organization's papers; a student sees papers uploaded
    in an organization that teaches them, for a subject they're enrolled in."""
    paper = await db.get(PastPaper, past_paper_id)
    if paper is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")
    if user.role in (UserRole.tutor, UserRole.admin):
        # Admins included: wider reach inside their organization, not across
        # organizations (`SEC-7`). This check used to be waived for them.
        if paper.organization_id != user.organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")
        return paper
    # Left nested rather than collapsed into one `and`: this is the
    # (organization, subject) scoping rule that decides which tutor's papers a
    # student can see. Nested, it reads as two named steps — is this a student,
    # and are they in scope. Collapsed, it is a 110-character boolean, and the
    # cost of nobody checking that line twice is a student seeing another
    # tutor's material.
    if user.role == UserRole.student:  # noqa: SIM102
        if (paper.organization_id, paper.subject_id) in await _enrolled_scope(db, user.id):
            return paper
        # History: a student whose class was deleted can still read their own
        # attempt and its marks (`own_attempt_ok`), never open the paper again.
        if own_attempt_ok and await db.scalar(
            select(Submission.id).where(
                Submission.work_id == paper.work_id, Submission.student_id == user.id
            )
        ):
            return paper
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")


async def _question_counts(db, past_paper_ids: Sequence[int]) -> dict[int, int]:
    """Question counts for a page of papers in one round trip, not one per row.

    The same shape as `_question_counts` in `api/mocks.py`, added here when the
    tutor's list grew a 3s poll while any paper is mid-extraction: the per-row
    count that cost one extra query per page load now costs one per paper every
    three seconds, for as long as the extraction job runs.
    """
    if not past_paper_ids:
        return {}
    rows = await db.execute(
        select(PastPaperQuestion.past_paper_id, func.count(PastPaperQuestion.id))
        .where(PastPaperQuestion.past_paper_id.in_(past_paper_ids))
        .group_by(PastPaperQuestion.past_paper_id)
    )
    return dict(rows.all())


async def _question_topics(db, question_ids: Sequence[int]) -> dict[int, list[TopicOut]]:
    """Every question's syllabus topics in one round trip, not one per question.

    The same answer `_question_rows` in `api/assignments.py` gives homework:
    which topics a question's marks count towards. A question missing from the
    result was classified under none, so its marks count towards no topic.
    """
    if not question_ids:
        return {}
    rows = await db.execute(
        select(PastPaperQuestionTopic.question_id, Topic)
        .join(Topic, Topic.id == PastPaperQuestionTopic.topic_id)
        .where(PastPaperQuestionTopic.question_id.in_(question_ids))
        .order_by(Topic.id)
    )
    topics: dict[int, list[TopicOut]] = {}
    for question_id, topic in rows.all():
        topics.setdefault(question_id, []).append(TopicOut.model_validate(topic))
    return topics


def _out(paper: PastPaper, count: int, *, for_tutor: bool) -> PastPaperOut:
    return PastPaperOut(
        id=paper.id,
        subject_id=paper.subject_id,
        title=paper.title,
        display_title=paper.display_title,
        session_label=paper.session_label,
        paper_number=paper.paper_number,
        total_marks=paper.total_marks,
        duration_minutes=paper.duration_minutes,
        paper_name=paper.paper_name,
        mark_scheme_name=paper.mark_scheme_name if for_tutor else None,
        extraction_error=paper.extraction_error if for_tutor else None,
        question_count=count,
    )


@router.post("", response_model=PastPaperOut, status_code=status.HTTP_201_CREATED)
async def upload_past_paper(
    db: DbSession,
    user: TutorUser,
    subject_id: Annotated[int, Form()],
    paper: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
    total_marks: Annotated[int | None, Form()] = None,
    duration_minutes: Annotated[int | None, Form()] = None,
) -> PastPaperOut:
    subject = await owned_subject(db, subject_id, user)

    # The mark scheme used to be mandatory here, rejected with a 422. The
    # product owner removed that: a tutor who has the paper but not the scheme
    # could upload nothing at all, which is worse than uploading a paper whose
    # marks a human checks.
    #
    # Dropping the 422 is safe because it was never the control. Marking gates
    # auto-finalize on `scheme_backed(q) = q.has_mark_scheme and
    # source.mark_scheme is not None` (services/marking.py), so a paper stored
    # with these three columns NULL marks normally and auto-finalizes *nothing*
    # — every question lands in the tutor's review queue and no mark becomes
    # Evidence until they rule on it. That is already how mocks behave
    # (models/mocks.py). AI-11/ADR-0009 — scheme-backed *and* confident — is
    # therefore still honoured; it is honoured one layer down.
    #
    # An empty file part (a browser form submitted with no file chosen) arrives
    # as an UploadFile with an empty filename, so it is treated as absent too.
    # Every past paper belongs to a booklet, and a single upload is a booklet
    # of one (task 3.5). That is what lets one paper and ten papers travel the
    # same path: nothing downstream has to ask whether a parent exists, and
    # `PastPaper.booklet_id` can be NOT NULL.
    #
    # It is `applied` immediately and carries no draft: there is no list of
    # papers to read off a single upload and nothing for the tutor to review,
    # so the extract-then-review screen a multi-paper booklet goes through is
    # skipped entirely. A photographed paper reaches here too, and a photo
    # cannot be split — a booklet of one never needs to be.
    #
    # The booklet keeps the file as uploaded; the paper keeps its own. For a
    # booklet of one they are the same file, which is not duplication worth
    # removing: the booklet records what arrived, the paper records what gets
    # marked, and for a multi-paper booklet those genuinely differ.
    # The files reach disk before any row exists, so from here on every path
    # that fails owns their cleanup — a stored object with no row pointing at it
    # is invisible and can never be found again. `_discard` in `api/mocks.py`
    # is the same guard for the same reason; this handler wrote two rows and had
    # none.
    #
    # Rolling the transaction back is not the expensive part: nothing written
    # here is worth keeping on its own. A booklet with no paper in it is exactly
    # the orphan `booklet_id`'s NOT NULL exists to prevent.
    saved: list[str] = []
    try:
        paper_path, paper_name, paper_mime = await storage.save_upload(
            paper, organization_id=user.organization_id
        )
        # Tracked the moment it exists, not once both uploads are through: a
        # mark scheme that is oversize or of the wrong type is rejected *after*
        # the paper is already on disk, and that rejection must take the paper
        # with it.
        saved.append(paper_path)
        ms_path, ms_name, ms_mime = (None, None, None)
        if mark_scheme is not None and mark_scheme.filename:
            ms_path, ms_name, ms_mime = await storage.save_upload(
                mark_scheme, organization_id=user.organization_id
            )
            saved.append(ms_path)

        booklet = Booklet(
            organization_id=user.organization_id,
            tutor_id=user.id,
            subject_id=subject.id,
            status=BookletStatus.applied,
            file_path=paper_path,
            file_name=paper_name,
            file_mime=paper_mime,
            mark_scheme_path=ms_path,
            mark_scheme_name=ms_name,
            mark_scheme_mime=ms_mime,
        )
        db.add(booklet)
        # Needed before the paper: `PastPaper.booklet_id` is NOT NULL and there
        # is no relationship for the ORM to order the inserts by.
        await db.flush()

        work = await create_work(
            db,
            kind=WorkKind.past_paper,
            # NULL, exactly like `PastPaper.title`: extraction has not read the
            # document yet and `PROD-2` forbids inventing a name. Kept in step
            # by `services/extraction.py`, which fills both.
            title=None,
            organization_id=user.organization_id,
            subject_id=subject.id,
        )
        past_paper = PastPaper(
            work_id=work.id,
            organization_id=user.organization_id,
            booklet_id=booklet.id,
            # The only paper in it. `first_page`/`last_page` stay NULL: this
            # paper is the whole document, and working out its page count would
            # mean parsing the PDF here, on the event loop (`BE-13`).
            booklet_index=1,
            tutor_id=user.id,
            subject_id=subject.id,
            total_marks=total_marks,
            duration_minutes=duration_minutes,
            paper_path=paper_path,
            paper_name=paper_name,
            paper_mime=paper_mime,
            mark_scheme_path=ms_path,
            mark_scheme_name=ms_name,
            mark_scheme_mime=ms_mime,
        )
        db.add(past_paper)
        # And before the enqueue: the job payload carries the id (`BE-9`).
        await db.flush()
        await enqueue(db, "extract_past_paper", {"past_paper_id": past_paper.id})
        await db.commit()
    except Exception:
        # Deliberately not just HTTPException. A rejected mark scheme raises
        # one; the database and the queue raise other things. All of them leave
        # the same orphans.
        await db.rollback()
        for path in saved:
            await storage.delete_file(path)
        raise
    # Extraction was only just enqueued, so the count is 0 by construction —
    # no point asking the database.
    return _out(past_paper, 0, for_tutor=True)


@router.get("", response_model=list[PastPaperOut])
async def list_past_papers(
    db: DbSession, user: CurrentUser, subject_id: int | None = None
) -> list[PastPaperOut]:
    query = select(PastPaper)
    if user.role in (UserRole.tutor, UserRole.admin):
        query = query.where(
            PastPaper.organization_id == user.organization_id,
            # Hidden on the tutor's own shelf only. The student filter below
            # deliberately does not repeat this: a paper a student can already
            # see must not disappear from under them mid-attempt, which is the
            # product owner's decision and the reason this is a flag and not a
            # delete.
            PastPaper.hidden_at.is_(None),
        )
        for_tutor = True
    elif user.role == UserRole.student:
        # One OR'd (organization, subject) pair per group the student is in.
        # Filtering the two columns independently would let a student in
        # org A + Chemistry see org B's Chemistry papers the moment they were
        # also in any org B group. `false()` keeps a student with no groups
        # seeing nothing rather than everything.
        pairs = [
            and_(PastPaper.organization_id == org_id, PastPaper.subject_id == subj_id)
            for org_id, subj_id in await _enrolled_scope(db, user.id)
        ]
        query = query.where(or_(*pairs) if pairs else false())
        for_tutor = False
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    if subject_id is not None:
        query = query.where(PastPaper.subject_id == subject_id)
    papers = (await db.scalars(query.order_by(PastPaper.id.desc()))).all()
    counts = await _question_counts(db, [p.id for p in papers])
    return [_out(p, counts.get(p.id, 0), for_tutor=for_tutor) for p in papers]


@router.get("/{past_paper_id}", response_model=PastPaperDetail)
async def past_paper_detail(
    past_paper_id: int, db: DbSession, user: CurrentUser
) -> PastPaperDetail:
    paper = await _visible_paper(db, user, past_paper_id)
    for_tutor = user.role in (UserRole.tutor, UserRole.admin)
    base = _out(
        paper, (await _question_counts(db, [paper.id])).get(paper.id, 0), for_tutor=for_tutor
    )
    questions = (
        await db.scalars(
            select(PastPaperQuestion)
            .where(PastPaperQuestion.past_paper_id == paper.id)
            .order_by(PastPaperQuestion.position)
        )
    ).all()
    topics = await _question_topics(db, [q.id for q in questions])
    return PastPaperDetail(
        **base.model_dump(),
        questions=[
            PastPaperQuestionOut(
                id=q.id,
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                has_mark_scheme=q.has_mark_scheme,
                topics=topics.get(q.id, []),
            )
            for q in questions
        ],
    )


@router.get("/{past_paper_id}/paper", response_class=Response, responses=FILE_RESPONSES)
async def past_paper_paper(past_paper_id: int, db: DbSession, user: CurrentUser) -> Response:
    """The question paper — readable by enrolled students so they can sit it."""
    paper = await _visible_paper(db, user, past_paper_id)
    if paper.paper_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No paper uploaded")
    # paper_mime/_name are nullable, so fall back rather than 500 on a row
    # that does have a file to serve (same reason as classifieds.py).
    return await signed_or_proxied_file(
        paper.paper_path,
        mime=paper.paper_mime or "application/octet-stream",
        filename=paper.paper_name or "paper",
    )


@router.get("/{past_paper_id}/mark-scheme", response_class=Response, responses=FILE_RESPONSES)
async def past_paper_mark_scheme(past_paper_id: int, db: DbSession, user: TutorUser) -> Response:
    """Tutor-only — handing this to a student would defeat the exercise."""
    paper = await _visible_paper(db, user, past_paper_id)
    if paper.mark_scheme_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mark scheme uploaded")
    return await signed_or_proxied_file(
        paper.mark_scheme_path,
        mime=paper.mark_scheme_mime or "application/octet-stream",
        filename=paper.mark_scheme_name or "mark-scheme",
    )


async def _attempt_out(db, submission: Submission) -> PastPaperAttemptOut:
    paper = await parent_of(db, submission)
    subject = await db.get(Subject, paper.subject_id)
    attempt = await db.scalar(
        select(PastPaperAttempt).where(
            PastPaperAttempt.past_paper_id == paper.id,
            PastPaperAttempt.student_id == submission.student_id,
        )
    )
    return PastPaperAttemptOut(
        submission_id=submission.id,
        past_paper_id=paper.id,
        title=paper.display_title,
        session_label=paper.session_label,
        paper_number=paper.paper_number,
        subject_name=subject.name if subject else "",
        status="marked" if submission.status in SETTLED_STATUSES else "being_marked",
        timed=submission.timed,
        time_taken_minutes=submission.time_taken_minutes,
        attempted_at=submission.attempted_at,
        submitted_at=submission.submitted_at,
        raw_marks=attempt.raw_marks if attempt else None,
        max_marks=attempt.max_marks if attempt else paper.total_marks,
    )


@router.post(
    "/{past_paper_id}/attempts",
    response_model=PastPaperAttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def log_attempt(
    past_paper_id: int,
    db: DbSession,
    user: StudentUser,
    files: Annotated[list[UploadFile], File()],
    attempted_at: Annotated[date, Form()],
    timed: Annotated[bool, Form()] = False,
    time_taken_minutes: Annotated[int | None, Form()] = None,
) -> PastPaperAttemptOut:
    """A student logging a paper they sat. Creates a Submission, so marking,
    review and evidence all work exactly as they do for homework."""
    paper = await _visible_paper(db, user, past_paper_id)
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload at least one file")

    submission, settled = await open_attempt(db, PAST_PAPER, paper.id, user.id)
    if settled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This paper has marks that are already final, so it can't be logged again",
        )

    submission.timed = timed
    submission.time_taken_minutes = time_taken_minutes
    submission.attempted_at = attempted_at
    for position, upload in enumerate(files):
        path, name, mime = await storage.save_upload(upload, organization_id=user.organization_id)
        db.add(
            SubmissionFile(
                submission_id=submission.id, position=position, path=path, name=name, mime=mime
            )
        )
    await enqueue(db, "mark_submission", {"submission_id": submission.id})
    await db.commit()
    return await _attempt_out(db, submission)


@router.get("/{past_paper_id}/my-attempt", response_model=PastPaperAttemptOut | None)
async def my_attempt(
    past_paper_id: int, db: DbSession, user: StudentUser
) -> PastPaperAttemptOut | None:
    paper = await _visible_paper(db, user, past_paper_id, own_attempt_ok=True)
    submission = await db.scalar(
        select(Submission).where(
            Submission.work_id == paper.work_id, Submission.student_id == user.id
        )
    )
    return await _attempt_out(db, submission) if submission else None


@router.delete("/{past_paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def hide_past_paper(past_paper_id: int, db: DbSession, user: TutorUser) -> Response:
    """Take a paper off the tutor's shelf. **Students keep it.**

    Named `DELETE` because that is what the tutor is doing — removing it from
    their list — but it is a flag, not a row deletion, and the product owner
    settled that on purpose. A paper carries attempts, marks and the `Evidence`
    those produced; deleting it would either cascade through a student's record
    or fail on the foreign keys, and a student mid-attempt would watch the paper
    vanish. `PROD-5` makes finalized outcomes permanent, so the row has to stay.

    Idempotent: hiding an already-hidden paper keeps the first timestamp, since
    "when did this leave my shelf" has one answer.
    """
    paper = await _visible_paper(db, user, past_paper_id)
    # `_visible_paper` already refuses another organization's paper, admins
    # included. It once exempted them on its eight read routes and this route
    # carried its own check, because hiding another tenant's paper is a change
    # to their shelf (`SEC-7`, `PROD-4`); the exemption is gone, so the check
    # lives in the helper alone.
    if paper.hidden_at is None:
        paper.hidden_at = utcnow()
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _discard(key: str, *, why: str) -> None:
    """Delete a stored file nothing points at any more, never fatally.

    The same guard as `_discard` in `api/teaching_guidance.py`, for the same
    reason: by the time this runs the request's outcome is decided. A storage
    backend that will not delete must not turn a committed replacement into a
    500 — the tutor would be told the copy didn't upload, and the retry they
    then make is refused, because the paper is already being read — nor bury
    a failed request's own error under a second one.
    """
    try:
        await storage.delete_file(key)
    except Exception:  # noqa: BLE001 — cleanup must not decide the response
        log.exception("could not delete an unreferenced past-paper file (%s): %s", why, key)


def _require_unread(paper: PastPaper) -> None:
    """Reading again and swapping the file are for a paper the AI could not
    read, and only that.

    A paper still being read has its extraction job in flight; a second would
    race it for the same question list — harmless by `BE-6`, but two model
    calls billed for one paper. A paper that was read has questions students
    may already have been marked against, and changing the file under those
    marks would leave them scored against a paper nobody can open.
    """
    if paper.extraction_error is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a paper that couldn't be read can be read again or replaced",
        )


async def _paper_to_fix(db, user: User, past_paper_id: int) -> PastPaper:
    """The paper a fix is about to change, held for the rest of the request.

    Locked before it is checked, so two fixes arriving together — two presses
    of Try again, or a retry racing a replacement — cannot both pass the check:
    the second waits, then finds the paper already being read and is refused,
    instead of paying for a second read or orphaning a second uploaded file.
    """
    paper = await _visible_paper(db, user, past_paper_id)
    await db.execute(select(PastPaper.id).where(PastPaper.id == paper.id).with_for_update())
    await db.refresh(paper)
    _require_unread(paper)
    if await read_in_progress(db, paper.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This paper is being read right now — try again in a minute",
        )
    return paper


@router.post("/{past_paper_id}/retry-extraction", response_model=PastPaperOut)
async def retry_past_paper_extraction(
    past_paper_id: int, db: DbSession, user: TutorUser
) -> PastPaperOut:
    """Try reading a paper again (owner decision, 2026-10-02: an unreadable
    paper is the tutor's to check and fix).

    For a failure in the reading rather than the paper — the model was
    unavailable or timed out. A scan nobody can read fails the same way twice,
    which is what `replace_past_paper_file` below is for.

    Any tutor in the paper's organization, like the rest of the shelf
    (`_visible_paper`); another organization's paper is a 404 (`API-7`).
    """
    paper = await _paper_to_fix(db, user, past_paper_id)
    paper.extraction_error = None
    await queue_past_paper_read(db, paper.id)
    await db.commit()
    # A failed extraction keeps no questions — the job clears the list before
    # it reads — so the count is 0 until the job just queued fills it.
    return _out(paper, 0, for_tutor=True)


@router.put("/{past_paper_id}/paper", response_model=PastPaperOut)
async def replace_past_paper_file(
    past_paper_id: int,
    db: DbSession,
    user: TutorUser,
    paper: Annotated[UploadFile, File()],
) -> PastPaperOut:
    """Swap a clearer copy in for a paper the AI could not read, and read that.

    The same row carries on rather than a second upload sitting beside it.
    Students already have this one — taking it off the tutor's shelf does not
    take it off theirs (`hide_past_paper`) — and anyone who has sent answers
    for it is marked against whatever this row's questions turn out to be. A
    fresh upload would leave those answers tied to the unreadable copy for good.

    Only the question paper: it is what the questions are read from. A mark
    scheme, if there is one, stays as it is.
    """
    past_paper = await _paper_to_fix(db, user, past_paper_id)
    booklet = await db.get(Booklet, past_paper.booklet_id)
    replaced = past_paper.paper_path
    saved: str | None = None
    try:
        saved, name, mime = await storage.save_upload(paper, organization_id=user.organization_id)
        past_paper.paper_path = saved
        # The client's own filename, so nothing bounds it; clamped to the
        # column rather than left for Postgres to refuse (`RISK-3`).
        past_paper.paper_name = name[:255]
        past_paper.paper_mime = mime
        # The new file is the whole paper, not pages cut from the booklet, so
        # the page range no longer says where it came from (`PROD-1`).
        past_paper.first_page = None
        past_paper.last_page = None
        past_paper.extraction_error = None
        await queue_past_paper_read(db, past_paper.id)
        await db.commit()
    except Exception:
        # Every failure leaves the paper as it was — still unread, still on the
        # tutor's list — and takes the new file with it, for the same reason as
        # `upload_past_paper`: a stored object no row points at is lost for good.
        await db.rollback()
        if saved is not None:
            await _discard(saved, why="replacement not saved")
        raise
    # The old file goes once nothing points at it. A booklet of one shares its
    # file with its only paper — the booklet records what arrived — so that
    # copy stays. A paper cut from a larger booklet owns its slice outright,
    # and a slice no row references can never be found to clean up later.
    if replaced and (booklet is None or replaced != booklet.file_path):
        await _discard(replaced, why="replaced by a clearer copy")
    return _out(past_paper, 0, for_tutor=True)
