"""Booklets — one upload holding several whole past papers (task 3.5, AV-117).

The flow is `SyllabusUpload`'s, because it is the same flow: upload, the AI
reads a list off the document, the tutor corrects it, and only then does
anything real get created (`PROD-7`). Nothing here invents a second pattern.

A single paper does not come through here at all — `POST /past-papers` makes it
a booklet of one and skips extraction entirely, which is what lets one paper and
twelve travel the same road afterwards.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import and_, false, func, or_, select

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.api.file_responses import FILE_RESPONSES, signed_or_proxied_file
from app.api.past_papers import _enrolled_scope
from app.models import Booklet, BookletStatus, PastPaper, Subject, User, UserRole
from app.schemas.booklet import BookletDetail, BookletDraft, BookletOut
from app.services import storage
from app.workers.jobs import enqueue

router = APIRouter(prefix="/booklets", tags=["past-papers"])

#: One wording for every refusal in this file. A booklet a caller may not see
#: and a booklet that does not exist must be indistinguishable (`API-7`), and
#: three separately-typed strings are three chances for them to drift apart.
NOT_FOUND = "Booklet not found"


async def _visible_booklet(db, user: User, booklet_id: int, *, for_update: bool = False) -> Booklet:
    """A tutor sees their organization's booklets; a student sees an applied
    booklet in an organization that teaches them, for a subject they are
    enrolled in (`SEC-8`).

    A student is deliberately shown the booklet and not only its papers: a
    booklet is the thing they recognise off a shelf, and hiding the parent would
    leave twelve unrelated-looking papers in a flat list.

    `404` rather than `403` throughout — a booklet id is an integer and
    enumerable, so a caller must not learn that one exists (`API-7`).
    """
    booklet = await db.get(Booklet, booklet_id, with_for_update=for_update)
    if booklet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    if user.role in (UserRole.tutor, UserRole.admin):
        # An admin gets no cross-tenant exemption here, deliberately. The older
        # `_visible_paper` grants one and `list_booklets` does not, so the pair
        # disagreed: an admin could not *list* another tenant's booklets but
        # could open and approve one by id. Scoped, the two agree, and `SEC-7`
        # reads the organization off the authenticated user with no exception.
        if booklet.organization_id != user.organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        return booklet
    # Nested rather than collapsed for the same reason as `_visible_paper`:
    # this is the rule deciding which tutor's material a student can see, and
    # it should read as two named steps.
    if user.role == UserRole.student:  # noqa: SIM102
        if booklet.status is BookletStatus.applied and (
            booklet.organization_id,
            booklet.subject_id,
        ) in await _enrolled_scope(db, user.id):
            return booklet
    raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)


async def _paper_counts(db, booklet_ids: list[int]) -> dict[int, int]:
    """Paper counts for a whole page of booklets in one round trip, not one
    query per row — the tutor's list polls while a split is running."""
    if not booklet_ids:
        return {}
    rows = await db.execute(
        select(PastPaper.booklet_id, func.count(PastPaper.id))
        .where(PastPaper.booklet_id.in_(booklet_ids))
        .group_by(PastPaper.booklet_id)
    )
    return dict(rows.all())


def _out(booklet: Booklet, paper_count: int, *, for_tutor: bool) -> BookletOut:
    return BookletOut(
        id=booklet.id,
        subject_id=booklet.subject_id,
        title=booklet.title,
        display_title=booklet.display_title,
        status=booklet.status.value,
        file_name=booklet.file_name,
        # Withheld from students, like the mark scheme route itself: knowing a
        # scheme exists is the first half of asking for it.
        mark_scheme_name=booklet.mark_scheme_name if for_tutor else None,
        error=booklet.error if for_tutor else None,
        paper_count=paper_count,
        created_at=booklet.created_at,
    )


def _detail(booklet: Booklet, paper_count: int, *, for_tutor: bool) -> BookletDetail:
    base = _out(booklet, paper_count, for_tutor=for_tutor)
    return BookletDetail(
        **base.model_dump(),
        # The draft is the tutor's working copy of the AI's reading; a student
        # has no business in it, and it carries the mark scheme's page ranges.
        draft=BookletDraft.model_validate(booklet.draft) if (for_tutor and booklet.draft) else None,
    )


@router.post("", response_model=BookletDetail, status_code=status.HTTP_201_CREATED)
async def upload_booklet(
    db: DbSession,
    user: TutorUser,
    subject_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> BookletDetail:
    """Upload a booklet and queue the AI read of what is inside it."""
    subject = await db.get(Subject, subject_id)
    if subject is None or subject.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    # A booklet has to be splittable, and only a PDF is. A photographed paper
    # is a perfectly good upload — it just goes through `POST /past-papers` as a
    # booklet of one, which never splits anything. Refusing here is better than
    # accepting it and failing at approval, after the tutor has done the review.
    if (file.content_type or "") != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "A booklet must be a PDF so it can be split into its papers. "
            "For a single paper or a photo, add it as one past paper instead.",
        )

    # Same guard as `upload_past_paper`: the files are on disk before any row
    # exists, so every failure after that point owns their cleanup or leaves a
    # stored object nothing points at.
    saved: list[str] = []
    try:
        path, name, mime = await storage.save_upload(file, organization_id=user.organization_id)
        saved.append(path)
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
            status=BookletStatus.extracting,
            file_path=path,
            file_name=name,
            file_mime=mime,
            mark_scheme_path=ms_path,
            mark_scheme_name=ms_name,
            mark_scheme_mime=ms_mime,
        )
        db.add(booklet)
        await db.flush()  # the job payload carries the id (`BE-9`)
        await enqueue(db, "extract_booklet", {"booklet_id": booklet.id})
        await db.commit()
    except Exception:
        await db.rollback()
        for stored in saved:
            await storage.delete_file(stored)
        raise
    return _detail(booklet, 0, for_tutor=True)


@router.get("", response_model=list[BookletOut])
async def list_booklets(
    db: DbSession, user: CurrentUser, subject_id: int | None = None
) -> list[BookletOut]:
    query = select(Booklet)
    if user.role in (UserRole.tutor, UserRole.admin):
        query = query.where(Booklet.organization_id == user.organization_id)
        for_tutor = True
    elif user.role == UserRole.student:
        # One OR'd (organization, subject) pair per group, exactly as the past
        # paper list does — filtering the two columns independently would show a
        # student another tenant's booklets for a subject they happen to share.
        # `false()` keeps a student in no groups seeing nothing, not everything.
        pairs = [
            and_(Booklet.organization_id == org_id, Booklet.subject_id == subj_id)
            for org_id, subj_id in await _enrolled_scope(db, user.id)
        ]
        query = query.where(or_(*pairs) if pairs else false())
        # A booklet mid-extraction or mid-review is the tutor's working state;
        # a student sees it once its papers exist.
        query = query.where(Booklet.status == BookletStatus.applied)
        for_tutor = False
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    if subject_id is not None:
        query = query.where(Booklet.subject_id == subject_id)
    booklets = (await db.scalars(query.order_by(Booklet.id.desc()))).all()
    counts = await _paper_counts(db, [b.id for b in booklets])
    return [_out(b, counts.get(b.id, 0), for_tutor=for_tutor) for b in booklets]


@router.get("/{booklet_id}", response_model=BookletDetail)
async def booklet_detail(booklet_id: int, db: DbSession, user: CurrentUser) -> BookletDetail:
    booklet = await _visible_booklet(db, user, booklet_id)
    counts = await _paper_counts(db, [booklet.id])
    return _detail(
        booklet,
        counts.get(booklet.id, 0),
        for_tutor=user.role in (UserRole.tutor, UserRole.admin),
    )


@router.get("/{booklet_id}/file", response_class=Response, responses=FILE_RESPONSES)
async def booklet_file(booklet_id: int, db: DbSession, user: CurrentUser) -> Response:
    """The booklet as uploaded. Students may read it — they can already read
    every paper cut from it, so withholding the parent protects nothing."""
    booklet = await _visible_booklet(db, user, booklet_id)
    if booklet.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No booklet file")
    return await signed_or_proxied_file(
        booklet.file_path,
        mime=booklet.file_mime or "application/octet-stream",
        filename=booklet.file_name or "booklet",
    )


@router.get("/{booklet_id}/mark-scheme", response_class=Response, responses=FILE_RESPONSES)
async def booklet_mark_scheme(booklet_id: int, db: DbSession, user: TutorUser) -> Response:
    """Tutor-only, like every mark scheme."""
    booklet = await _visible_booklet(db, user, booklet_id)
    if booklet.mark_scheme_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mark scheme uploaded")
    return await signed_or_proxied_file(
        booklet.mark_scheme_path,
        mime=booklet.mark_scheme_mime or "application/octet-stream",
        filename=booklet.mark_scheme_name or "mark-scheme",
    )


def _first_problem(exc: ValidationError) -> str:
    """The first validation message, without pydantic's framing — the tutor is
    reading this on a screen, not in a stack trace."""
    first = exc.errors()[0]["msg"]
    return first.removeprefix("Value error, ")


async def _editable(db, booklet: Booklet) -> None:
    """Everything after the papers exist is settled. Editing the list then would
    describe papers that already exist and were cut to the old ranges.

    `split_failed` is the interesting case: a cut that failed on the very first
    paper created nothing, and the tutor must be able to fix the range that
    broke it — refusing there is a dead end with no way out but re-uploading.
    Once any paper exists the list is keyed by position and is frozen.
    """
    if booklet.status in (BookletStatus.applying, BookletStatus.applied):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This booklet's papers have already been created"
        )
    if booklet.status is BookletStatus.split_failed and await db.scalar(
        select(PastPaper.id).where(PastPaper.booklet_id == booklet.id).limit(1)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Some of this booklet's papers have already been created"
        )


@router.put("/{booklet_id}/draft", response_model=BookletDetail)
async def edit_draft(
    booklet_id: int, body: BookletDraft, db: DbSession, user: TutorUser
) -> BookletDetail:
    """The tutor's correction of the AI's list — full authority (`PROD-7`).

    They may rewrite every field, add a paper the AI missed and drop one it
    invented; the only rules enforced are the ones that make the split
    physically possible (a forward page range, no two papers claiming the same
    page), which `BookletDraft` checks.
    """
    booklet = await _visible_booklet(db, user, booklet_id)
    await _editable(db, booklet)
    booklet.draft = body.model_dump()
    # An edited draft is a reviewable one: correcting the list by hand is
    # exactly how a tutor recovers from a failed read, so it clears the failure
    # rather than leaving them stuck on a retry that may fail again.
    booklet.status = BookletStatus.review
    booklet.error = None
    await db.commit()
    counts = await _paper_counts(db, [booklet.id])
    return _detail(booklet, counts.get(booklet.id, 0), for_tutor=True)


@router.post("/{booklet_id}/retry", response_model=BookletDetail)
async def retry_booklet(booklet_id: int, db: DbSession, user: TutorUser) -> BookletDetail:
    """Try the step that failed again — and only that step.

    A failed *read* and a failed *cut* recover in opposite directions, and
    sending one down the other's path is worse than doing nothing: re-reading
    after a partial cut overwrites the list the tutor approved (`PROD-7`) while
    the papers already cut keep their old indexes, so the entries at those
    positions are silently never created.
    """
    booklet = await _visible_booklet(db, user, booklet_id)
    if booklet.status is BookletStatus.extraction_failed:
        booklet.status = BookletStatus.extracting
        job = "extract_booklet"
    elif booklet.status is BookletStatus.split_failed:
        booklet.status = BookletStatus.applying
        job = "split_booklet"
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is nothing to retry")
    booklet.error = None
    await enqueue(db, job, {"booklet_id": booklet.id})
    await db.commit()
    counts = await _paper_counts(db, [booklet.id])
    return _detail(booklet, counts.get(booklet.id, 0), for_tutor=True)


@router.post("/{booklet_id}/approve", response_model=BookletDetail)
async def approve_booklet(booklet_id: int, db: DbSession, user: TutorUser) -> BookletDetail:
    """Turn the reviewed list into real papers.

    The cutting itself is a job: a booklet of twelve is twelve PDF writes, which
    is CPU-bound work that must not run on the event loop the whole API shares
    (`BE-13`, `PERF-1`). So this marks the booklet `applying` and returns — the
    papers appear as the job creates them.
    """
    # Locked, so two clicks (or two tabs) cannot both move a `review` booklet to
    # `applying` and queue two splits. The second waits, sees `applying`, and is
    # refused by `_editable`. The split job is idempotent anyway, but two jobs
    # racing on the same index collide on the unique key and one fails the
    # booklet for no reason.
    booklet = await _visible_booklet(db, user, booklet_id, for_update=True)
    await _editable(db, booklet)
    if not booklet.draft:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "There is no paper list to approve yet"
        )
    # Validated here as well as on the way in: a draft written by extraction has
    # never been through `PUT /draft`, so this is the only place an AI-proposed
    # overlap or backwards range is caught before it is cut. Raised as a 422
    # rather than left to become a 500 — the tutor can fix an overlap by hand,
    # and needs to be told what it is.
    try:
        draft = BookletDraft.model_validate(booklet.draft)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"This paper list cannot be cut as it stands: {_first_problem(exc)}",
        ) from exc
    # And that every range fits the document. Caught here, the tutor edits the
    # list and tries again; caught inside the split job it is a failed cut, and
    # a half-cut booklet's list can no longer be edited. `page_count` is absent
    # on a booklet whose read never finished, and the check is then skipped
    # rather than guessed.
    if booklet.page_count is not None:
        over = [p for p in draft.papers if p.last_page > booklet.page_count]
        if over:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{over[0].title}' runs to page {over[0].last_page}, but this booklet has "
                f"{booklet.page_count} pages. Correct the list and approve again.",
            )
    booklet.status = BookletStatus.applying
    booklet.error = None
    await enqueue(db, "split_booklet", {"booklet_id": booklet.id})
    await db.commit()
    counts = await _paper_counts(db, [booklet.id])
    return _detail(booklet, counts.get(booklet.id, 0), for_tutor=True)
