"""Task 3.5: the AI pass that reads an uploaded booklet into its list of papers.

The job type is not registered yet, so the handler is called directly — every
other rule still binds (`QA-7`: patch the *calling* module; `QA-8`: no real
provider).
"""

import pytest

from app.db import async_session
from app.models import Booklet, BookletStatus
from app.services import storage
from app.services.extraction import BookletExtractionResult, ExtractedPaper, extract_booklet
from tests.conftest import PDF_BYTES
from tests.factories import make_subject, org_id

pytestmark = pytest.mark.anyio


def _paper(n: int, session_label: str = "November 2026") -> ExtractedPaper:
    return ExtractedPaper(
        title=f"Cambridge IGCSE Chemistry 0620/{n}1 Paper {n}",
        session_label=session_label,
        paper_number=f"Paper {n}",
        first_page=(n - 1) * 10 + 1,
        last_page=n * 10,
    )


def _double(fake_ai, *results):
    """A structured_complete stand-in that answers each call in turn — the
    booklet file first, then the mark scheme. `results` may hold an exception to
    raise instead of a result."""
    calls = list(results)

    async def _call(**kwargs):
        nonlocal calls
        item = calls.pop(0)
        if isinstance(item, Exception):
            raise item
        return await fake_ai(item)(**kwargs)

    return _call


async def _make_booklet(*, with_scheme: bool = False, **kwargs) -> int:
    async with async_session() as session:
        oid = await org_id(session)
        subject = await make_subject(session, organization_id=oid)
        path, name, mime = await storage.save_bytes(
            PDF_BYTES, "application/pdf", "booklet.pdf", organization_id=oid
        )
        scheme = (
            await storage.save_bytes(PDF_BYTES, "application/pdf", "ms.pdf", organization_id=oid)
            if with_scheme
            else (None, None, None)
        )
        booklet = Booklet(
            organization_id=oid,
            subject_id=subject.id,
            file_path=path,
            file_name=name,
            file_mime=mime,
            mark_scheme_path=scheme[0],
            mark_scheme_name=scheme[1],
            mark_scheme_mime=scheme[2],
            **kwargs,
        )
        session.add(booklet)
        await session.commit()
        return booklet.id


async def _run(booklet_id: int):
    async with async_session() as session:
        await extract_booklet(session, {"booklet_id": booklet_id})
        await session.commit()
    async with async_session() as session:
        return await session.get(Booklet, booklet_id)


async def test_a_three_paper_booklet_becomes_a_three_entry_draft(monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(fake_ai, BookletExtractionResult(papers=[_paper(1), _paper(2), _paper(3)])),
    )
    booklet = await _run(await _make_booklet())

    assert booklet.status is BookletStatus.review
    assert booklet.error is None
    assert [p["paper_number"] for p in booklet.draft["papers"]] == ["Paper 1", "Paper 2", "Paper 3"]
    assert booklet.draft["papers"][1]["first_page"] == 11
    # No mark scheme: no second list, and nothing to disagree about (`PROD-2`).
    assert booklet.draft["scheme_papers"] is None
    assert booklet.draft["scheme_mismatch"] is None


async def test_a_failed_extraction_records_the_error(monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(fake_ai, RuntimeError("model timed out")),
    )
    booklet_id = await _make_booklet()
    with pytest.raises(RuntimeError):
        await _run(booklet_id)

    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
    assert booklet.status is BookletStatus.extraction_failed
    assert booklet.error == "model timed out"
    assert booklet.draft is None


async def test_an_empty_paper_list_is_an_error_not_an_empty_draft(monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(fake_ai, BookletExtractionResult(papers=[])),
    )
    booklet_id = await _make_booklet()
    with pytest.raises(ValueError):
        await _run(booklet_id)

    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
    assert booklet.status is BookletStatus.extraction_failed
    assert booklet.draft is None


async def test_an_applied_booklet_is_left_untouched_by_a_re_run(monkeypatch, fake_ai):  # noqa: F811
    """A re-run (an orphan reclaim, `BE-6`) must not overwrite the list the
    tutor already applied — the model is never even called."""
    settled = {"papers": [{"title": "Tutor's own", "paper_number": "Paper 9"}]}
    booklet_id = await _make_booklet(status=BookletStatus.applied, draft=settled)

    def _boom(**kwargs):
        raise AssertionError("the model must not be called for an applied booklet")

    monkeypatch.setattr("app.services.extraction.structured_complete", _boom)
    booklet = await _run(booklet_id)

    assert booklet.status is BookletStatus.applied
    assert booklet.draft == settled


async def test_a_mark_scheme_listing_different_papers_is_flagged(monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1), _paper(2), _paper(3)]),
            BookletExtractionResult(papers=[_paper(1), _paper(2)]),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    # Both lists are kept: which document is wrong is the tutor's call.
    assert booklet.status is BookletStatus.review
    assert len(booklet.draft["papers"]) == 3
    assert len(booklet.draft["scheme_papers"]) == 2
    assert booklet.draft["scheme_mismatch"] == (
        "The mark scheme lists 2 papers but the booklet has 3."
    )


async def test_a_matching_mark_scheme_is_not_flagged(monkeypatch, fake_ai):  # noqa: F811
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1), _paper(2)]),
            BookletExtractionResult(papers=[_paper(1), _paper(2)]),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    assert booklet.draft["scheme_mismatch"] is None
    assert len(booklet.draft["scheme_papers"]) == 2


async def test_an_unreadable_mark_scheme_still_lands_in_review(monkeypatch, fake_ai):  # noqa: F811
    """A scheme that will not parse is not a failed extraction — the tutor can
    still approve the papers, and the reason is on the record."""
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1)]),
            RuntimeError("scheme is a scan of a scan"),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    assert booklet.status is BookletStatus.review
    assert booklet.error is None
    assert len(booklet.draft["papers"]) == 1
    assert booklet.draft["scheme_papers"] is None
    assert "scheme is a scan of a scan" in booklet.draft["scheme_mismatch"]


async def test_a_same_size_scheme_listing_other_papers_is_flagged(monkeypatch, fake_ai):  # noqa: F811
    """The dangerous mismatch, because the count check cannot see it: the two
    lists are the same length, so the split pairs them positionally and every
    paper would get the wrong scheme — the document a mark auto-finalizes
    against (`AI-11`)."""
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1), _paper(2)]),
            BookletExtractionResult(papers=[_paper(1), _paper(3)]),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    assert booklet.status is BookletStatus.review
    assert booklet.draft["scheme_mismatch"], "a same-size mismatch went unflagged"
    assert "Paper 2" in booklet.draft["scheme_mismatch"]


async def test_the_same_papers_in_a_different_order_are_flagged(monkeypatch, fake_ai):  # noqa: F811
    """Also invisible to a count check, and just as wrong: pairing is
    positional, so a reversed scheme hands every paper its neighbour's."""
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1), _paper(2)]),
            BookletExtractionResult(papers=[_paper(2), _paper(1)]),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    assert booklet.draft["scheme_mismatch"], "a reordered scheme went unflagged"


async def test_a_session_that_differs_only_in_case_is_not_a_mismatch(monkeypatch, fake_ai):  # noqa: F811
    """ "November 2026" and "NOVEMBER 2026" are the same session, and crying
    mismatch over capitalisation would teach tutors to click past the warning
    that matters."""
    monkeypatch.setattr(
        "app.services.extraction.structured_complete",
        _double(
            fake_ai,
            BookletExtractionResult(papers=[_paper(1, "November 2026")]),
            BookletExtractionResult(papers=[_paper(1, " NOVEMBER 2026 ")]),
        ),
    )
    booklet = await _run(await _make_booklet(with_scheme=True))

    assert booklet.draft["scheme_mismatch"] is None
