"""T-027: bounding how much PDF work one workspace can cause.

Reading a booklet's file is now done in a limited child process, and these are
the rules around it: a booklet holds at most 60 papers, a file found too
complex stays refused rather than being queued again, approving and retrying
spend the daily upload allowance, and one workspace has at most one booklet
being read or cut at a time.

The one-at-a-time check locks the workspace's row before it looks. SQLite
ignores `FOR UPDATE`, so on SQLite these tests prove the rule (a second request
after the first is refused, and another workspace is not) but not the race
between two requests at the same instant; that part holds only on Postgres,
where the lock is real. `test_two_uploads_at_the_same_moment_let_only_one_through`
sends two at once, and runs in CI's Postgres run of the suite.
"""

import asyncio
import os

import pytest
from sqlalchemy import delete, func, select, update

from app.db import async_session
from app.models import Booklet, BookletStatus, Job, JobStatus, PastPaper
from app.services import booklets as booklets_service
from app.services import extraction as extraction_service
from app.services import pdf_sandbox
from app.services.extraction import BookletExtractionResult, ExtractedPaper, extract_booklet
from app.services.pdf_sandbox import PdfTooComplex
from app.services.rate_limit import upload_daily_limiter
from app.workers.jobs import process_one_job
from tests.factories import other_org_subject
from tests.test_booklets import _draft, _pdf, _reviewed, _upload
from tests.test_daily_workspace_limits import _allow

TOO_COMPLEX = "This PDF is too complex to read safely."
BUSY = "A booklet is already being read. Try again when it finishes."


def _many(n: int) -> dict:
    return _draft(*[(i, i) for i in range(1, n + 1)])


async def _set(booklet_id: int, **values) -> None:
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        for key, value in values.items():
            setattr(booklet, key, value)
        await session.execute(delete(Job))
        await session.commit()


async def _jobs() -> list[Job]:
    async with async_session() as session:
        return list((await session.scalars(select(Job))).all())


# --- 60 papers ------------------------------------------------------------------


async def test_a_draft_of_61_papers_is_refused_and_60_is_not(client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))

    resp = await client.put(
        f"/api/v1/booklets/{booklet_id}/draft", json=_many(61), headers=tutor["headers"]
    )
    assert resp.status_code == 422, resp.text
    assert "60 papers" in resp.json()["detail"]

    resp = await client.put(
        f"/api/v1/booklets/{booklet_id}/draft", json=_many(60), headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text


async def test_approving_61_papers_is_refused_even_if_the_ai_wrote_them(client, tutor, subject):  # noqa: F811
    """Extraction writes the draft directly, never through `PUT /draft`."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    await _set(booklet_id, draft=_many(61))

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 422, resp.text
    assert "60 papers" in resp.json()["detail"]
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.review
    assert await _jobs() == []


# --- too complex ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [("post", "/retry"), ("post", "/approve"), ("put", "/draft")],
)
async def test_a_too_complex_booklet_is_never_queued_again(client, tutor, subject, method, path):  # noqa: F811
    """Editing is refused too: an edit moves the booklet back to review, and
    approving from there would queue the same file again."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    await _set(booklet_id, status=BookletStatus.too_complex, error=TOO_COMPLEX)

    kwargs = {"json": _draft((1, 2))} if method == "put" else {}
    resp = await getattr(client, method)(
        f"/api/v1/booklets/{booklet_id}{path}", headers=tutor["headers"], **kwargs
    )
    assert resp.status_code == 409, resp.text
    assert "too complex" in resp.json()["detail"]
    assert await _jobs() == []
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.too_complex


async def test_a_too_complex_read_fails_the_booklet_for_good(monkeypatch, client, tutor, subject):  # noqa: F811
    """It used to leave `page_count` empty and carry on, so a hostile file
    reached approval and was cut. Refused before the AI is paid to read it."""

    async def _refuse(data):
        raise PdfTooComplex()

    async def _no_ai(**kwargs):
        raise AssertionError("the AI read a file the sandbox refused")

    monkeypatch.setattr(extraction_service.pdf_sandbox, "page_count", _refuse)
    monkeypatch.setattr(extraction_service, "structured_complete", _no_ai)

    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201, resp.text
    booklet_id = resp.json()["id"]
    assert await process_one_job() is True

    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.too_complex
        assert booklet.error == TOO_COMPLEX
        job = (await session.scalars(select(Job))).one()
        # Not retried: the same file would be refused the same way.
        assert job.status is JobStatus.failed

    # And a re-run of the same payload (an orphan reclaim) leaves it alone.
    async with async_session() as session:
        await extract_booklet(session, {"booklet_id": booklet_id})
        await session.commit()
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.too_complex


async def test_a_plain_unreadable_booklet_still_reaches_review(
    monkeypatch, fake_ai, client, tutor, subject
):  # noqa: F811
    """Today's behaviour, kept: a file the library cannot parse is not hostile,
    and the AI may still read its list. The count is left absent (`PROD-2`)."""
    monkeypatch.setattr(
        extraction_service,
        "structured_complete",
        fake_ai(
            BookletExtractionResult(
                papers=[
                    ExtractedPaper(
                        title="Paper 1",
                        session_label="November 2026",
                        paper_number="Paper 1",
                        first_page=1,
                        last_page=2,
                    )
                ]
            )
        ),
    )
    resp = await client.post(
        "/api/v1/booklets",
        data={"subject_id": str(subject["id"])},
        files=[("file", ("booklet.pdf", b"%PDF-1.4 not really a pdf", "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True
    async with async_session() as session:
        booklet = await session.get(Booklet, resp.json()["id"])
        assert booklet.status is BookletStatus.review
        assert booklet.page_count is None


async def test_a_real_booklet_read_counts_its_pages_in_the_sandbox(
    monkeypatch, fake_ai, client, tutor, subject
):  # noqa: F811
    monkeypatch.setattr(
        extraction_service,
        "structured_complete",
        fake_ai(
            BookletExtractionResult(
                papers=[
                    ExtractedPaper(
                        title="Paper 1",
                        session_label="November 2026",
                        paper_number="Paper 1",
                        first_page=1,
                        last_page=6,
                    )
                ]
            )
        ),
    )
    resp = await _upload(client, tutor, subject, pages=6)
    assert await process_one_job() is True
    async with async_session() as session:
        assert (await session.get(Booklet, resp.json()["id"])).page_count == 6


async def test_a_too_complex_split_fails_the_booklet_for_good(monkeypatch, client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 2), (3, 6))

    async def _refuse(data, ranges):
        raise PdfTooComplex()

    monkeypatch.setattr(booklets_service.pdf_sandbox, "split", _refuse)
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    assert await process_one_job() is True

    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.too_complex
        assert booklet.error == TOO_COMPLEX
        assert (await session.scalars(select(Job))).one().status is JobStatus.failed
        assert (await session.scalars(select(PastPaper))).all() == []


async def test_a_split_reads_each_file_once_for_all_its_ranges(monkeypatch, client, tutor, subject):  # noqa: F811
    """One child per file, not one per paper: twelve papers used to be twelve
    parses of the same booklet."""
    resp = await _upload(client, tutor, subject, pages=6, scheme_pages=6)
    booklet_id = resp.json()["id"]
    draft = _draft((1, 2), (3, 4), (5, 6))
    draft["scheme_papers"] = _draft((1, 2), (3, 4), (5, 6))["papers"]
    await _set(booklet_id, draft=draft, status=BookletStatus.review)

    calls: list[list[tuple[int, int]]] = []
    real = pdf_sandbox.split

    async def _counting(data, ranges):
        calls.append(list(ranges))
        return await real(data, ranges)

    monkeypatch.setattr(booklets_service.pdf_sandbox, "split", _counting)
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    assert await process_one_job() is True

    assert calls == [[(1, 2), (3, 4), (5, 6)], [(1, 2), (3, 4), (5, 6)]]
    async with async_session() as session:
        papers = (
            await session.scalars(select(PastPaper).where(PastPaper.booklet_id == booklet_id))
        ).all()
        assert len(papers) == 3
        assert all(p.mark_scheme_path for p in papers)


# --- the upload allowance -------------------------------------------------------------


async def test_approving_spends_the_upload_allowance(monkeypatch, client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    _allow(monkeypatch, upload_daily_limiter, 0)

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 429, resp.text
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.review
    assert await _jobs() == []

    _allow(monkeypatch, upload_daily_limiter, 1)
    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    # The one place left was spent by that approve.
    await _set(booklet_id, status=BookletStatus.review)
    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 429, resp.text


async def test_retrying_spends_the_upload_allowance(monkeypatch, client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    await _set(booklet_id, status=BookletStatus.extraction_failed, error="failed")
    _allow(monkeypatch, upload_daily_limiter, 0)

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/retry", headers=tutor["headers"])
    assert resp.status_code == 429, resp.text
    assert await _jobs() == []
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.extraction_failed


async def test_a_refused_approve_does_not_spend_the_allowance(monkeypatch, client, tutor, subject):  # noqa: F811
    """Counted only once everything else has passed, so a tutor fixing an
    overlap is not charged for each attempt."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    await _set(booklet_id, draft=_draft((1, 4), (3, 6)))
    _allow(monkeypatch, upload_daily_limiter, 1)

    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 422
    await _set(booklet_id, draft=_draft((1, 3)))
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200


# --- one booklet at a time per workspace ---------------------------------------------


async def test_a_second_upload_waits_for_the_first_read(client, tutor, subject):  # noqa: F811
    first = await _upload(client, tutor, subject)
    assert first.status_code == 201, first.text

    second = await _upload(client, tutor, subject)
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == BUSY
    async with async_session() as session:
        assert await session.scalar(select(func.count(Booklet.id))) == 1


async def _live_job(booklet_id: int, job_type: str, status: JobStatus = JobStatus.pending):
    async with async_session() as session:
        session.add(Job(type=job_type, payload={"booklet_id": booklet_id}, status=status))
        await session.commit()


async def test_a_busy_refusal_spends_nothing(monkeypatch, client, tutor, subject):  # noqa: F811
    assert (await _upload(client, tutor, subject)).status_code == 201
    _allow(monkeypatch, upload_daily_limiter, 1)
    assert (await _upload(client, tutor, subject)).status_code == 409
    # The place is still there for the upload after the read finishes.
    async with async_session() as session:
        await session.execute(update(Booklet).values(status=BookletStatus.review))
        await session.execute(update(Job).values(status=JobStatus.done))
        await session.commit()
    assert (await _upload(client, tutor, subject)).status_code == 201


@pytest.mark.parametrize(
    "job_type,job_status",
    [
        ("extract_booklet", JobStatus.pending),
        ("extract_booklet", JobStatus.running),
        ("split_booklet", JobStatus.pending),
        ("split_booklet", JobStatus.running),
    ],
)
async def test_a_live_job_holds_up_upload_approve_and_retry(  # noqa: F811
    client, tutor, subject, job_type, job_status
):
    waiting = await _reviewed(client, tutor, subject, (1, 3))
    failed = await _reviewed(client, tutor, subject, (1, 3))
    await _set(failed, status=BookletStatus.extraction_failed, error="failed")
    other = await _reviewed(client, tutor, subject, (1, 3))
    await _live_job(other, job_type, job_status)

    upload = await _upload(client, tutor, subject)
    assert upload.status_code == 409, upload.text
    assert upload.json()["detail"] == BUSY
    approve = await client.post(f"/api/v1/booklets/{waiting}/approve", headers=tutor["headers"])
    assert approve.status_code == 409, approve.text
    assert approve.json()["detail"] == BUSY
    retry = await client.post(f"/api/v1/booklets/{failed}/retry", headers=tutor["headers"])
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"] == BUSY
    assert len(await _jobs()) == 1


async def test_a_booklet_stuck_in_progress_with_no_live_job_does_not_block(client, tutor, subject):  # noqa: F811
    """A booklet left `extracting` or `applying` after its job ended (its
    give-up step never ran) must not lock the workspace for good."""
    for status in (BookletStatus.extracting, BookletStatus.applying):
        stuck = await _reviewed(client, tutor, subject, (1, 3))
        await _set(stuck, status=status)
        await _live_job(stuck, "extract_booklet", JobStatus.failed)
        await _live_job(stuck, "split_booklet", JobStatus.done)
    assert (await _upload(client, tutor, subject)).status_code == 201


async def test_a_retry_waiting_out_its_backoff_blocks_a_second_retry(client, tutor, subject):  # noqa: F811
    """A read the worker will retry shows `extraction_failed` while its job is
    still pending. Retrying then would queue a second job beside it."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    await _set(booklet_id, status=BookletStatus.extraction_failed, error="failed")
    await _live_job(booklet_id, "extract_booklet", JobStatus.pending)

    retry = await client.post(f"/api/v1/booklets/{booklet_id}/retry", headers=tutor["headers"])
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"] == BUSY
    upload = await _upload(client, tutor, subject)
    assert upload.status_code == 409, upload.text
    assert len(await _jobs()) == 1


async def test_another_workspaces_live_jobs_do_not_block_this_one(client, tutor, subject):  # noqa: F811
    """The negative tenancy case (`QA-12`): the rule is per workspace."""
    async with async_session() as session:
        foreign = await other_org_subject(session)
        reading = Booklet(
            organization_id=foreign.organization_id,
            subject_id=foreign.id,
            status=BookletStatus.extracting,
        )
        cutting = Booklet(
            organization_id=foreign.organization_id,
            subject_id=foreign.id,
            status=BookletStatus.applying,
        )
        session.add_all([reading, cutting])
        await session.commit()
        reading_id, cutting_id = reading.id, cutting.id
    await _live_job(reading_id, "extract_booklet", JobStatus.running)
    await _live_job(cutting_id, "split_booklet", JobStatus.pending)

    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201, resp.text
    await _set(resp.json()["id"], status=BookletStatus.review, draft=_draft((1, 3)))
    await _live_job(reading_id, "extract_booklet", JobStatus.running)
    await _live_job(cutting_id, "split_booklet", JobStatus.pending)
    approve = await client.post(
        f"/api/v1/booklets/{resp.json()['id']}/approve", headers=tutor["headers"]
    )
    assert approve.status_code == 200, approve.text


async def test_a_job_with_an_unexpected_payload_is_ignored(client, tutor, subject):  # noqa: F811
    async with async_session() as session:
        session.add(
            Job(type="extract_booklet", payload={"booklet_id": "7"}, status=JobStatus.pending)
        )
        session.add(Job(type="split_booklet", payload={}, status=JobStatus.pending))
        await session.commit()
    assert (await _upload(client, tutor, subject)).status_code == 201


async def test_a_finished_or_failed_booklet_does_not_block(client, tutor, subject):  # noqa: F811
    for status in (
        BookletStatus.review,
        BookletStatus.applied,
        BookletStatus.extraction_failed,
        BookletStatus.split_failed,
        BookletStatus.too_complex,
    ):
        booklet_id = await _reviewed(client, tutor, subject, (1, 3))
        await _set(booklet_id, status=status)
    assert (await _upload(client, tutor, subject)).status_code == 201


async def test_a_single_paper_upload_is_not_held_up(client, tutor, subject):  # noqa: F811
    """`POST /past-papers` never reads or cuts anything, so it is not a booklet
    job and does not wait for one."""
    assert (await _upload(client, tutor, subject)).status_code == 201
    resp = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"])},
        files=[("paper", ("paper.pdf", _pdf(1), "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="SQLite ignores FOR UPDATE; CI's Postgres run of the suite runs this",
)
async def test_two_uploads_at_the_same_moment_let_only_one_through(client, tutor, subject):  # noqa: F811
    """The race the workspace lock is for. Without it both requests check,
    both find nothing in progress, and both start a read."""
    first, second = await asyncio.gather(
        _upload(client, tutor, subject), _upload(client, tutor, subject)
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    async with async_session() as session:
        assert await session.scalar(select(func.count(Booklet.id))) == 1
