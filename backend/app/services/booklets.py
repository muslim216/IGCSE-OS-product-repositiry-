"""Cutting an approved booklet into the past papers it holds.

This runs as a job, not in the approve request, because splitting a PDF is
CPU-bound and the worker shares the API's event loop (`BE-13`, `PERF-1`). Every
pypdf call therefore goes through `asyncio.to_thread`, which is what
`services/pdf.py`'s docstring requires of its callers.

Splitting happens **once**, here. Each paper comes out as its own file, so
everything downstream — download, question extraction, marking — sees an
ordinary single paper and knows nothing about page ranges.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booklet, BookletStatus, PastPaper
from app.schemas.booklet import BookletDraft, DraftPaper
from app.services import pdf, storage
from app.workers.jobs import enqueue

log = logging.getLogger(__name__)


def _slice_name(booklet_name: str | None, paper: DraftPaper, suffix: str) -> str:
    """The original filename is metadata only (`SEC-16`) — the stored name is
    server-generated — but it is what a tutor sees on the download, so it says
    which paper of which booklet this is."""
    stem = (booklet_name or "booklet").rsplit(".", 1)[0]
    return f"{stem} — {paper.paper_number} {paper.session_label}{suffix}.pdf"


async def _cut(
    data: bytes, paper: DraftPaper, *, organization_id: int, name: str
) -> tuple[str, str, str]:
    """One page range, stored as its own PDF. Blocking work off the loop."""
    piece = await asyncio.to_thread(pdf.extract_pages, data, paper.first_page, paper.last_page)
    return await storage.save_bytes(piece, "application/pdf", name, organization_id=organization_id)


async def split_booklet(session: AsyncSession, payload: dict) -> None:
    """Job handler: turn an approved booklet's draft into real `PastPaper` rows.

    Safe to re-run on the same payload (`BE-6`), which matters more here than
    usual: a worker that dies halfway leaves some papers created and the rest
    not, and the reclaim hands the same payload back. The existing papers are
    read first and their `booklet_index` values skipped, so a re-run finishes
    the job instead of either duplicating it or refusing it. That is what
    `uq_past_papers_booklet_id_booklet_index` is for.
    """
    booklet = await session.get(Booklet, payload["booklet_id"])
    if booklet is None or booklet.file_path is None or not booklet.draft:
        return
    # `applied` means a previous run finished. Anything else — including a
    # booklet the tutor sent back to `review` — means this job is stale, and
    # cutting papers against a draft nobody approved would be worse than doing
    # nothing. `split_failed` is accepted because it is this handler's own
    # failure state: refusing it would turn the queue's automatic retry into a
    # silent no-op, which is the opposite of what `BE-6` is for.
    if booklet.status not in (BookletStatus.applying, BookletStatus.split_failed):
        return

    draft = BookletDraft.model_validate(booklet.draft)
    existing = {
        p.booklet_index
        for p in (
            await session.scalars(select(PastPaper).where(PastPaper.booklet_id == booklet.id))
        ).all()
    }

    try:
        data = await storage.read_file(booklet.file_path)
        scheme_data = (
            await storage.read_file(booklet.mark_scheme_path)
            if booklet.mark_scheme_path and draft.scheme_papers
            else None
        )
        # Positional, not matched by name: the tutor has just reviewed both
        # lists and a mismatch was shown to them before they approved, so the
        # nth scheme entry is the scheme for the nth paper. Guessing a pairing
        # by title would attach the wrong scheme silently, and a wrong scheme is
        # worse than none — it is what a mark auto-finalizes against (`AI-11`).
        schemes = draft.scheme_papers or []
        for index, drafted in enumerate(draft.papers, start=1):
            if index in existing:
                continue
            # Tracked per paper, because the two cuts below land on disk before
            # the row that points at them exists. The scheme's page range comes
            # from a second AI pass the tutor never corrected, so the scheme cut
            # failing while the paper cut succeeded is the ordinary case, not an
            # exotic one — and without this it leaves an unreferenced file
            # behind on every retry.
            cut: list[str] = []
            try:
                paper_path, paper_name, paper_mime = await _cut(
                    data,
                    drafted,
                    organization_id=booklet.organization_id,
                    name=_slice_name(booklet.file_name, drafted, ""),
                )
                cut.append(paper_path)
                ms_path = ms_name = ms_mime = None
                if scheme_data is not None and index <= len(schemes):
                    ms_path, ms_name, ms_mime = await _cut(
                        scheme_data,
                        schemes[index - 1],
                        organization_id=booklet.organization_id,
                        name=_slice_name(booklet.file_name, drafted, " mark scheme"),
                    )
                    cut.append(ms_path)
            except Exception:
                for stored in cut:
                    await storage.delete_file(stored)
                raise
            paper = PastPaper(
                organization_id=booklet.organization_id,
                booklet_id=booklet.id,
                booklet_index=index,
                first_page=drafted.first_page,
                last_page=drafted.last_page,
                tutor_id=booklet.tutor_id,
                subject_id=booklet.subject_id,
                # Named from the draft the tutor reviewed, not left for
                # extraction to guess a second time: they have already corrected
                # these three fields and `PROD-7` gives that correction final
                # authority over anything the AI reads later.
                title=drafted.title,
                session_label=drafted.session_label,
                paper_number=drafted.paper_number,
                paper_path=paper_path,
                paper_name=paper_name,
                paper_mime=paper_mime,
                mark_scheme_path=ms_path,
                mark_scheme_name=ms_name,
                mark_scheme_mime=ms_mime,
            )
            session.add(paper)
            await session.flush()
            # The question list is a separate job per paper, the same one a
            # single upload uses — no parallel path (`PROD-9`), and a booklet of
            # twelve does not become one enormous extraction.
            await enqueue(session, "extract_past_paper", {"past_paper_id": paper.id})
    except Exception as exc:
        # The papers created before the failure are kept, not rolled back: their
        # files are already stored and their extractions already queued, and the
        # re-run picks up from the index that failed. `extraction_failed` is
        # what the tutor's screen reads to offer a retry.
        await session.commit()
        booklet.status = BookletStatus.split_failed
        booklet.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise

    booklet.status = BookletStatus.applied
    booklet.error = None
    await session.commit()
