"""Which request or job a log line belongs to, and the process's log setup.

Until this, nothing configured logging in the API: every `log.info` was
dropped, and the warnings and errors that did reach Render's log carried no
time, no level, no logger name and nothing tying them to the request or job
they came from, so a tutor's report could not be matched to a line (audit
finding OPS-06).

Kept free of app imports so the worker layer and the API can both use it
(`BE-1`).
"""

import contextvars
import logging
import re
import uuid

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(context)s] %(message)s"

_context: contextvars.ContextVar[str] = contextvars.ContextVar("log_context", default="-")

#: A caller-supplied request id is kept only if it is short and plain, so a
#: header cannot inject text, or a newline, into the log.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def bind(value: str) -> contextvars.Token[str]:
    """Mark everything logged from here on, in this task and the tasks it
    starts, as belonging to `value`. Undo with `reset`."""
    return _context.set(value)


def reset(token: contextvars.Token[str]) -> None:
    _context.reset(token)


def request_id(header: str | None) -> str:
    """The id for one request: the caller's `X-Request-ID` if it is safe to
    log, otherwise a new one."""
    if header and _SAFE_ID.match(header):
        return header
    return uuid.uuid4().hex


class ContextFilter(logging.Filter):
    """Stamps every record with the current request or job id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.context = _context.get()
        return True


def configure_logging() -> None:
    """INFO and up, to stderr, with time, level, logger and context. Called once
    when a process starts serving (the API's lifespan, the standalone worker),
    never at import, so the test suite's own log capture is left alone.
    Repeat calls change nothing."""
    root = logging.getLogger()
    if any(isinstance(f, ContextFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
