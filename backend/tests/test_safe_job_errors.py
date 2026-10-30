"""A failed job stores a safe sentence, not the exception's own text.

The detail (a provider's wording, a library's message, a path) belongs in the
server log. Every test here raises something secret-looking and checks both
halves: it is not in the column a tutor reads, and it is in the log.
"""

import asyncio
import logging

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Assignment,
    Booklet,
    BookletStatus,
    Job,
    JobStatus,
    Mock,
    PastPaper,
    SyllabusUpload,
)
from app.services import storage
from app.services.ai import (
    AICallFailedError,
    AIDailyLimitError,
    AIKeyMissingError,
    AIOutputTruncatedError,
    AITimeoutError,
    AIUnavailableError,
)
from app.services.job_errors import GENERIC_JOB_ERROR, DocumentProblem, safe_job_error
from app.services.reports import NothingToReport
from app.workers.jobs import process_one_job
from tests.test_booklet_extraction import _make_booklet, _run  # noqa: F401
from tests.test_given_up_jobs import JOB, PAYLOAD, _queue, _the_job, probe  # noqa: F401
from tests.test_mocks import _create as _create_mock
from tests.test_past_papers import _upload as _upload_past_paper
from tests.test_syllabus_upload import upload_pdf

SECRET = "sk-test-LEAK-9f3 at postgres://user:hunter2@db.internal/avora"


def _leaks(*values) -> bool:
    return any(SECRET in str(v) for v in values)


def _boom(*_args, **_kwargs):
    raise RuntimeError(SECRET)


async def _aboom(*_args, **_kwargs):
    raise RuntimeError(SECRET)


# --- safe_job_error ---------------------------------------------------------


class _Model(BaseModel):
    n: int


def _validation_error() -> ValidationError:
    try:
        _Model(n=SECRET)  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


@pytest.mark.parametrize(
    "exc",
    [
        AIKeyMissingError("AI is not configured: set GEMINI_API_KEY in the backend environment"),
        AIUnavailableError("The google-genai package is not installed"),
        AIDailyLimitError("This workspace has reached today's limit for AI work."),
        AICallFailedError("The AI provider rejected the request"),
        AITimeoutError("The AI did not answer in time"),
        AIOutputTruncatedError("The AI's answer was cut off at the output limit (8 tokens)"),
        storage.ObjectNotFoundError("org/1/key.pdf"),
        NothingToReport("This student isn't in a class yet, so there is nothing to report."),
        DocumentProblem("No questions were found in the document"),
    ],
)
def test_our_own_sentences_are_kept(exc):
    assert safe_job_error(exc) == str(exc)
    assert "org/1/key.pdf" not in safe_job_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError(SECRET),
        ValueError(SECRET),
        KeyError(SECRET),
        _validation_error(),
        TimeoutError(SECRET),
    ],
    ids=["runtime", "plain value error", "key", "validation error", "timeout"],
)
def test_anything_unmarked_gets_the_generic_sentence(exc):
    assert safe_job_error(exc) == GENERIC_JOB_ERROR


def test_a_marked_exception_with_no_text_gets_the_generic_sentence():
    assert safe_job_error(DocumentProblem("")) == GENERIC_JOB_ERROR
    assert safe_job_error(DocumentProblem("   ")) == GENERIC_JOB_ERROR


def test_the_marker_can_be_set_on_one_instance():
    exc = RuntimeError("written by us")
    exc.safe_to_show = True  # type: ignore[attr-defined]
    assert safe_job_error(exc) == "written by us"


def test_a_truthy_look_alike_is_not_the_marker():
    exc = RuntimeError(SECRET)
    exc.safe_to_show = "yes"  # type: ignore[attr-defined]
    assert safe_job_error(exc) == GENERIC_JOB_ERROR


# --- the worker ------------------------------------------------------------


async def test_the_worker_stores_the_generic_sentence_and_logs_the_detail(client, probe, caplog):  # noqa: F811
    probe(_aboom)
    await _queue()
    with caplog.at_level(logging.ERROR):
        assert await process_one_job() is True

    job = await _the_job()
    assert job.error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text
    # Retry behaviour unchanged: an unmarked failure still gets its second go.
    assert job.status == JobStatus.pending
    assert job.run_after is not None


async def test_a_permanent_failure_is_still_permanent_and_keeps_its_sentence(client, probe):  # noqa: F811
    async def _no_key(session, payload):
        raise AIKeyMissingError("AI is not configured: set GEMINI_API_KEY in the backend")

    calls = probe(_no_key)
    await _queue()
    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert job.attempts == 1
    assert job.error == "AI is not configured: set GEMINI_API_KEY in the backend"
    assert calls == [(PAYLOAD, job.error)]


async def test_the_give_up_hook_is_handed_the_safe_text(client, probe, caplog):  # noqa: F811
    calls = probe(_aboom)
    await _queue()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    async with async_session() as session:
        job = await session.scalar(select(Job))
        job.run_after = None
        await session.commit()
    with caplog.at_level(logging.ERROR):
        assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert calls == [(PAYLOAD, GENERIC_JOB_ERROR)]
    assert not _leaks(job.error, calls)
    assert SECRET in caplog.text


# --- each site -------------------------------------------------------------


async def test_syllabus_extraction(client, tutor, monkeypatch, caplog):
    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", _aboom)
    with caplog.at_level(logging.ERROR):
        upload_id = await upload_pdf(client, tutor)
    async with async_session() as session:
        upload = await session.get(SyllabusUpload, upload_id)
    assert upload.status.value == "extraction_failed"
    assert upload.error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text


async def test_a_document_problem_reaches_the_tutor_in_words(client, tutor, monkeypatch):
    async def _empty(session, upload):
        raise DocumentProblem("No chapters were found in the document")

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", _empty)
    upload_id = await upload_pdf(client, tutor)
    async with async_session() as session:
        upload = await session.get(SyllabusUpload, upload_id)
    assert upload.error == "No chapters were found in the document"


async def test_assignment_extraction(
    client, tutor, group, classified, subject, monkeypatch, caplog
):
    monkeypatch.setattr("app.services.extraction._run_extraction", _aboom)
    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "Bonding", "classified_id": classified["id"]},
        headers=tutor["headers"],
    )
    with caplog.at_level(logging.ERROR):
        assert await process_one_job() is True
    async with async_session() as session:
        assignment = await session.get(Assignment, created.json()["id"])
    assert assignment.extraction_error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text


async def test_mock_extraction(client, tutor, subject, group, monkeypatch, caplog):
    monkeypatch.setattr("app.services.extraction._run_mock_extraction", _aboom)
    created = await _create_mock(client, tutor, subject, group)
    with caplog.at_level(logging.ERROR):
        await process_one_job()
    async with async_session() as session:
        mock = await session.get(Mock, created.json()["id"])
    assert mock.extraction_error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text


async def test_past_paper_extraction(client, tutor, subject, monkeypatch, caplog):
    monkeypatch.setattr("app.services.extraction._run_past_paper_extraction", _aboom)
    created = await _upload_past_paper(client, tutor, subject)
    assert created.status_code == 201, created.text
    with caplog.at_level(logging.ERROR):
        await process_one_job()
    async with async_session() as session:
        paper = await session.get(PastPaper, created.json()["id"])
    assert paper.extraction_error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text


async def test_booklet_extraction(client, monkeypatch, caplog):
    monkeypatch.setattr("app.services.extraction._run_booklet_extraction", _aboom)
    booklet_id = await _make_booklet()
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        await _run(booklet_id)
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
    assert booklet.status is BookletStatus.extraction_failed
    assert booklet.error == GENERIC_JOB_ERROR
    # Raised on, so the worker (not this call) is what logs it.


async def test_booklet_split(client, tutor, subject, monkeypatch, caplog):  # noqa: F811
    from tests.test_booklets import _reviewed

    booklet_id = await _reviewed(client, tutor, subject, (1, 2))
    monkeypatch.setattr("app.services.booklets._create_paper", _aboom)
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    with caplog.at_level(logging.ERROR):
        assert await process_one_job() is True
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
    assert booklet.status is BookletStatus.split_failed
    assert booklet.error == GENERIC_JOB_ERROR
    assert SECRET in caplog.text


async def test_the_page_range_problem_of_a_split_stays_readable(client, tutor, subject):  # noqa: F811
    from tests.test_booklets import _reviewed

    booklet_id = await _reviewed(client, tutor, subject, (1, 99))
    await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert await process_one_job() is True
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
    assert "runs past the last page" in booklet.error


def test_pdf_errors_drop_the_library_text():
    from app.services import pdf

    with pytest.raises(DocumentProblem) as caught:
        pdf.page_count(b"%PDF-1.4 not really a pdf")
    assert "PDF" in str(caught.value)
    assert caught.value.__cause__ is not None
    assert str(caught.value.__cause__) not in str(caught.value) or not str(caught.value.__cause__)
    assert isinstance(caught.value, ValueError)
