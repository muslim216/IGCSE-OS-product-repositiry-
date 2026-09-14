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
    Subject,
    Submission,
    SubmissionFile,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.schemas.past_paper import (
    PastPaperAttemptOut,
    PastPaperDetail,
    PastPaperOut,
    PastPaperQuestionOut,
)
from app.services import storage
from app.services.attempts import open_attempt
from app.services.submission_kind import PAST_PAPER
from app.workers.jobs import enqueue

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
            .where(GroupMember.student_id == student_id)
        )
    ).all()
    return {(org_id, subject_id) for org_id, subject_id in rows}


async def _visible_paper(db, user: User, past_paper_id: int) -> PastPaper:
    """A tutor sees their organization's papers; a student sees papers uploaded
    in an organization that teaches them, for a subject they're enrolled in."""
    paper = await db.get(PastPaper, past_paper_id)
    if paper is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Past paper not found")
    if user.role in (UserRole.tutor, UserRole.admin):
        if paper.organization_id != user.organization_id and user.role != UserRole.admin:
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

        past_paper = PastPaper(
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
    return PastPaperDetail(
        **base.model_dump(),
        questions=[
            PastPaperQuestionOut(
                id=q.id,
                number=q.number,
                text_summary=q.text_summary,
                max_marks=q.max_marks,
                has_mark_scheme=q.has_mark_scheme,
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
    paper = await db.get(PastPaper, submission.past_paper_id)
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
            status.HTTP_409_CONFLICT, "You've already logged this paper and it's been marked"
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
    paper = await _visible_paper(db, user, past_paper_id)
    submission = await db.scalar(
        select(Submission).where(
            Submission.past_paper_id == paper.id, Submission.student_id == user.id
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
    if paper.hidden_at is None:
        paper.hidden_at = utcnow()
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
