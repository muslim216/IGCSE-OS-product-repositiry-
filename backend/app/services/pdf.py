"""Cutting a page range out of a PDF.

A booklet is one upload holding several whole past papers. Approving it splits
that file so each paper becomes its own document, and every step downstream —
download, question extraction, marking — then sees an ordinary single paper and
needs to know nothing about page ranges. Splitting once at approval is what buys
that; the alternative was teaching ranges to four separate places.

**Only `services/pdf_child.py` calls these.** pypdf is synchronous and
CPU-bound, and a crafted file can make it use memory or time without bound. Run
in the API process, that stalls or kills it for every user, not only the tutor
who uploaded (`BE-13`, `PERF-1`). So every caller goes through
`services/pdf_sandbox.py`, which runs them in a separate, limited process, and
`tests/test_pdf_guards.py` fails if anything else imports this module.

Pure by `BE-4`: bytes in, bytes or an int out. No session, no storage, no
logging of file contents.

Passing our upload validation does not make a file parseable here:
`storage.content_matches_mime` checks magic bytes, and `b"%PDF-1.4 "` followed
by rubbish satisfies it. A caller must expect `ValueError` on a real tutor
upload rather than treating it as impossible.
"""

import logging
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from app.services.job_errors import DocumentProblem

log = logging.getLogger(__name__)


class PdfEncrypted(DocumentProblem):
    """The PDF is password-protected. Its own type so that the sandbox's child
    can report it as such without reading the sentence."""


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
            raise PdfEncrypted("This PDF is password-protected, so its pages cannot be read.")
        return reader, len(reader.pages)
    # Only our own refusals pass through as they are. pypdf also raises plain
    # `ValueError`s of its own on a corrupt file ("invalid literal for int()"),
    # which are unreadable like any other library error below.
    except DocumentProblem:
        raise
    # Not "could not be read": running out of memory or stack is the sandbox's
    # "too complex", which is never retried, where an unreadable file is the
    # tutor's ordinary problem to fix.
    except (MemoryError, RecursionError):
        raise
    # Blind on purpose, and not suppressed with a `noqa`: BLE001 does not fire
    # on a handler that re-raises, so one here would be a comment pretending to
    # be a directive.
    except Exception as exc:
        # The library's own text stays in the log: it is not ours to show.
        log.warning("a PDF could not be read: %s: %s", type(exc).__name__, exc)
        raise DocumentProblem("This file could not be read as a PDF.") from exc


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
        raise DocumentProblem(f"Pages start at 1, but the range starts at {first_page}.")
    if last_page < first_page:
        raise DocumentProblem(f"Page range {first_page}-{last_page} ends before it starts.")
    if last_page > total:
        raise DocumentProblem(
            f"Page range {first_page}-{last_page} runs past the last page ({total})."
        )

    # pypdf parses lazily, so a page's content streams are only touched here —
    # a file that survived `_read` can still blow up on the page it is asked
    # for. Same funnel into `ValueError` as `_read`, for the same reason.
    try:
        writer = PdfWriter()
        for index in range(first_page - 1, last_page):
            writer.add_page(reader.pages[index])
        out = BytesIO()
        writer.write(out)
    except (MemoryError, RecursionError):  # too complex, not unreadable, as in `_read`
        raise
    except Exception as exc:  # blind on purpose, as in `_read`
        log.warning(
            "pages %s-%s of a PDF could not be read: %s: %s",
            first_page,
            last_page,
            type(exc).__name__,
            exc,
        )
        raise DocumentProblem(
            f"Pages {first_page}-{last_page} of this PDF could not be read."
        ) from exc
    return out.getvalue()
