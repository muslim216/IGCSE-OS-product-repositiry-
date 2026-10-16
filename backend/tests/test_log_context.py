"""Every log line says which request or job it came from, and the process logs
INFO at all.

Until this nothing configured logging in the API: every `log.info` was
dropped, and what did reach the log could not be tied to a request or a job
(audit finding OPS-06)."""

import logging

import pytest
from sqlalchemy import select

from app import log_context
from app.db import async_session
from app.models import Job
from app.workers import jobs
from app.workers.jobs import enqueue, process_one_job


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.addFilter(log_context.ContextFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def collected():
    """Records from the root logger, stamped the way the real handler stamps
    them, for one test."""
    handler = _Collect()
    root = logging.getLogger()
    root.addHandler(handler)
    yield handler.records
    root.removeHandler(handler)


def test_a_plain_caller_id_is_kept():
    assert log_context.request_id("abc-123_X.y") == "abc-123_X.y"


@pytest.mark.parametrize(
    "header", [None, "", "has space", "line\nbreak", "x" * 65, 'quote"', "évil"]
)
def test_anything_else_gets_a_fresh_id(header):
    rid = log_context.request_id(header)
    assert rid != header
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)


def test_outside_any_request_or_job_the_context_is_a_dash():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    log_context.ContextFilter().filter(record)
    assert record.context == "-"


async def test_every_response_carries_its_request_id(client):
    fresh = await client.get("/api/v1/health")
    assert len(fresh.headers["x-request-id"]) == 32

    echoed = await client.get("/api/v1/health", headers={"X-Request-ID": "tutor-report-17"})
    assert echoed.headers["x-request-id"] == "tutor-report-17"


async def test_lines_logged_during_a_request_carry_its_id(client, monkeypatch, collected):
    def _refused():
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.async_session", _refused)

    await client.get("/api/v1/health/ready", headers={"X-Request-ID": "find-me"})

    lines = [r for r in collected if "could not reach the database" in r.getMessage()]
    assert lines
    assert all(r.context == "req-find-me" for r in lines)


async def test_lines_logged_during_a_job_carry_its_id(client, monkeypatch, collected, caplog):
    caplog.set_level(logging.INFO)  # what `configure_logging` does in a real process

    async def _logs(session, payload):
        logging.getLogger("probe").info("inside the handler")

    monkeypatch.setitem(jobs._handlers, "log_probe", _logs)
    async with async_session() as session:
        await enqueue(session, "log_probe", {})
        await session.commit()
        job_id = (await session.scalars(select(Job.id).where(Job.type == "log_probe"))).one()

    assert await process_one_job() is True

    [line] = [r for r in collected if r.getMessage() == "inside the handler"]
    assert line.context == f"job-{job_id}"
    assert log_context._context.get() == "-", "the job's id does not leak past it"


def test_configuring_twice_adds_one_handler_and_logs_info():
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    try:
        log_context.configure_logging()
        log_context.configure_logging()
        ours = [
            h
            for h in root.handlers
            if any(isinstance(f, log_context.ContextFilter) for f in h.filters)
            and h not in before_handlers
        ]
        assert len(ours) == 1
        assert root.level == logging.INFO
        assert "%(context)s" in ours[0].formatter._fmt
    finally:
        for h in list(root.handlers):
            if h not in before_handlers:
                root.removeHandler(h)
        root.setLevel(before_level)
