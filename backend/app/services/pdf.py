"""Cutting a page range out of a PDF.

A booklet is one upload holding several whole past papers. Approving it splits
that file so each paper becomes its own document, and every step downstream —
download, question extraction, marking — then sees an ordinary single paper and
needs to know nothing about page ranges. Splitting once at approval is what buys
that; the alternative was teaching ranges to four separate places.

**These functions block.** pypdf is synchronous and CPU-bound, and the worker
shares the API's event loop (`BE-13`, `PERF-1`) — one call on the loop stalls
request serving for every user, not just the tutor who uploaded. An async caller
must go through `asyncio.to_thread`, or sit inside a job handler that does.

Pure by `BE-4`: bytes in, bytes or an int out. No session, no storage, no
logging of file contents.

Passing our upload validation does not make a file parseable here:
`storage.content_matches_mime` checks magic bytes, and `b"%PDF-1.4 "` followed
by rubbish satisfies it. A caller must expect `ValueError` on a real tutor
upload rather than treating it as impossible.
"""

from io import BytesIO

from pypdf import PdfReader, PdfWriter


def _read(data: bytes) -> tuple[PdfReader, int]:
    """The reader and its page count, or `ValueError` explaining why not.

    pypdf raises a wide and undocumented spread of types for a broken file —
    `PdfReadError`, `KeyError`, `struct.error` and `OSError` among them — and
    its parsing is lazy, so a corrupt file often survives construction and fails
    only on first page access. Both are funnelled into one `ValueError` here so
    every caller has a single thing to catch.
    """
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected, so its pages cannot be read.")
        return reader, len(reader.pages)
    except ValueError:
        raise
    # Blind on purpose, and not suppressed with a `noqa`: BLE001 does not fire
    # on a handler that re-raises, so one here would be a comment pretending to
    # be a directive.
    except Exception as exc:
        raise ValueError(f"This file could not be read as a PDF: {exc}") from exc


def page_count(data: bytes) -> int:
    """How many pages the PDF has. Raises `ValueError` if it cannot be read."""
    return _read(data)[1]


def extract_pages(data: bytes, first_page: int, last_page: int) -> bytes:
    """A new PDF holding only pages `first_page`..`last_page` of `data`.

    Both bounds are 1-based and inclusive, because that is what a page range
    read off a booklet means to a tutor, and what the extraction prompt returns.

    An out-of-range request raises rather than clamping. A range that does not
    fit means the extracted paper list is wrong, and quietly returning the
    nearest valid slice would hand a student someone else's questions.
    """
    reader, total = _read(data)
    if first_page < 1:
        raise ValueError(f"Pages start at 1, but the range starts at {first_page}.")
    if last_page < first_page:
        raise ValueError(f"Page range {first_page}-{last_page} ends before it starts.")
    if last_page > total:
        raise ValueError(f"Page range {first_page}-{last_page} runs past the last page ({total}).")

    # pypdf parses lazily, so a page's content streams are only touched here —
    # a file that survived `_read` can still blow up on the page it is asked
    # for. Same funnel into `ValueError` as `_read`, for the same reason.
    try:
        writer = PdfWriter()
        for index in range(first_page - 1, last_page):
            writer.add_page(reader.pages[index])
        out = BytesIO()
        writer.write(out)
    except Exception as exc:  # blind on purpose, as in `_read`
        raise ValueError(
            f"Pages {first_page}-{last_page} of this PDF could not be read: {exc}"
        ) from exc
    return out.getvalue()
