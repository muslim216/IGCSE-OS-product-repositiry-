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


def test_request_ids_are_fresh_and_unguessable():
    ids = {log_context.new_request_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 32 and all(c in "0123456789abcdef" for c in i) for i in ids)


def test_outside_any_request_or_job_the_context_is_a_dash():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    log_context.ContextFilter().filter(record)
    assert record.context == "-"


async def test_every_response_carries_its_own_request_id(client):
    first = await client.get("/api/v1/health")
    second = await client.get("/api/v1/health", headers={"X-Request-ID": "chosen-by-caller"})

    assert len(first.headers["x-request-id"]) == 32
    # A caller cannot choose one: theirs could collide with someone else's
    # lines in a search of the log.
    assert second.headers["x-request-id"] != "chosen-by-caller"
    assert second.headers["x-request-id"] != first.headers["x-request-id"]


async def test_an_unhandled_error_is_logged_with_the_request_id_and_still_raises(client, collected):
    """The case someone reports, so the one whose log line most needs the id.
    The error still propagates, as it always has, for the server to answer."""
    from app.main import app

    async def _boom():
        raise RuntimeError("something broke")

    app.add_api_route("/api/v1/_test_boom", _boom)
    try:
        with pytest.raises(RuntimeError, match="something broke"):
            await client.get("/api/v1/_test_boom")
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", "") != "/api/v1/_test_boom"
        ]

    [line] = [r for r in collected if "unhandled error" in r.getMessage()]
    assert line.context.startswith("req-")
    assert len(line.context) == len("req-") + 32
    assert line.exc_info is not None


async def test_lines_logged_during_a_request_carry_its_id(client, monkeypatch, collected):
    def _refused():
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.async_session", _refused)

    resp = await client.get("/api/v1/health/ready")

    lines = [r for r in collected if "could not reach the database" in r.getMessage()]
    assert lines
    assert all(r.context == f"req-{resp.headers['x-request-id']}" for r in lines)


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
        # The HTTP client would log every request's full URL at INFO.
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    finally:
        for h in list(root.handlers):
            if h not in before_handlers:
                root.removeHandler(h)
        root.setLevel(before_level)
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.NOTSET)
