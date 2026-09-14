"""The page splitter behind booklets.

Pages are told apart by width rather than by text: pypdf can write a blank page
of a given size with no extra dependency, and the width survives a round-trip
through `extract_pages` exactly. Asserting only on page *counts* would pass just
as happily if the function returned the wrong slice, which is the bug that
actually matters here.
"""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from app.services.pdf import extract_pages, page_count

# Page n is (100 + 10n) wide, so a page's width names which page it came from.
WIDTH_STEP = 10


def _pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for n in range(1, pages + 1):
        writer.add_blank_page(width=100 + WIDTH_STEP * n, height=200)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _widths(data: bytes) -> list[int]:
    return [round(float(page.mediabox.width)) for page in PdfReader(BytesIO(data)).pages]


def test_page_count_reads_the_real_number() -> None:
    assert page_count(_pdf(7)) == 7


def test_a_middle_range_returns_exactly_those_pages() -> None:
    extracted = extract_pages(_pdf(10), 4, 6)

    assert page_count(extracted) == 3
    # Pages 4, 5 and 6 — not the first three, which is what an off-by-one gives.
    assert _widths(extracted) == [140, 150, 160]


def test_a_single_page_range_is_allowed() -> None:
    extracted = extract_pages(_pdf(5), 3, 3)

    assert page_count(extracted) == 1
    assert _widths(extracted) == [130]


def test_the_full_range_returns_every_page_in_order() -> None:
    source = _pdf(4)

    assert _widths(extract_pages(source, 1, 4)) == _widths(source)


def test_the_last_page_is_included() -> None:
    """The bounds are inclusive, so asking for the last page must return it
    rather than stopping one short."""
    assert _widths(extract_pages(_pdf(3), 3, 3)) == [130]


def test_a_range_starting_below_one_is_refused() -> None:
    data = _pdf(3)
    with pytest.raises(ValueError, match="start at 1"):
        extract_pages(data, 0, 2)


def test_a_backwards_range_is_refused() -> None:
    data = _pdf(5)
    with pytest.raises(ValueError, match="ends before it starts"):
        extract_pages(data, 4, 2)


def test_a_range_past_the_end_is_refused_rather_than_clamped() -> None:
    """Clamping would hand back a shorter paper than the list promised, and
    nothing downstream would notice."""
    data = _pdf(3)
    with pytest.raises(ValueError, match="runs past the last page"):
        extract_pages(data, 2, 9)


def test_a_file_that_is_not_a_pdf_is_refused() -> None:
    with pytest.raises(ValueError, match="could not be read as a PDF"):
        page_count(b"this is not a pdf at all")


def test_a_file_that_only_looks_like_a_pdf_is_refused() -> None:
    """`storage.content_matches_mime` passes this — magic bytes are all it
    checks — so the splitter is where a rubbish upload gets caught. These are
    `conftest.PDF_BYTES`, the exact bytes the upload tests post."""
    with pytest.raises(ValueError, match="could not be read as a PDF"):
        page_count(b"%PDF-1.4 fake test pdf")


def test_a_password_protected_pdf_is_refused() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=110, height=200)
    writer.encrypt("hunter2")
    out = BytesIO()
    writer.write(out)

    data = out.getvalue()
    with pytest.raises(ValueError, match="password-protected"):
        page_count(data)


def test_a_page_that_fails_while_being_copied_is_refused(monkeypatch) -> None:
    """pypdf parses lazily, so a file can pass `_read` and still fail on the
    page it is asked for — the content streams are not touched until then.
    Forced here rather than crafted, because a file that breaks at exactly that
    point depends on pypdf internals that change between releases; what matters
    to a caller is that it is still a `ValueError`."""

    data = _pdf(3)  # built before the patch, which would break the builder too

    def _explode(*args, **kwargs):
        raise KeyError("/Contents")

    monkeypatch.setattr("app.services.pdf.PdfWriter.add_page", _explode)

    with pytest.raises(ValueError, match="could not be read"):
        extract_pages(data, 1, 2)
