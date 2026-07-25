"""A fixed-window counter for throttling failed logins.

Deliberately in-process: the API runs as a single instance (it mounts a
persistent disk for uploads — see render.yaml), so a shared store would be
machinery without a second consumer. If the service is ever scaled out, this
becomes per-instance and the effective limit multiplies by the instance count;
that is the moment to move the counter into Postgres or Redis, and it is the
same moment `services/storage.py` has to move to S3.

The window is fixed rather than sliding: a burst that straddles a boundary can
briefly exceed the limit. That is an acceptable trade for keeping this a plain
dict — the goal is to make credential stuffing impractical, not to enforce an
exact quota.
"""

import time
from dataclasses import dataclass, field


@dataclass
class FixedWindowLimiter:
    """Counts hits per key and reports when a key is over its allowance.

    Pure and clock-injectable so the policy is unit-testable without sleeping.
    """

    limit: int
    window_seconds: float
    _hits: dict[str, tuple[float, int]] = field(default_factory=dict)

    def _window_start(self, now: float) -> float:
        return now - (now % self.window_seconds)

    def is_limited(self, key: str, *, now: float | None = None) -> bool:
        """Whether `key` has already used up its allowance in this window."""
        now = time.monotonic() if now is None else now
        start, count = self._hits.get(key, (self._window_start(now), 0))
        if start != self._window_start(now):
            return False
        return count >= self.limit

    def record(self, key: str, *, now: float | None = None) -> None:
        """Count one failure against `key`."""
        now = time.monotonic() if now is None else now
        window = self._window_start(now)
        start, count = self._hits.get(key, (window, 0))
        self._hits[key] = (window, count + 1) if start == window else (window, 1)
        self._evict(window)

    def reset(self, key: str) -> None:
        """Forget a key's failures — called on a successful login so a user who
        finally remembers their password is not still locked out."""
        self._hits.pop(key, None)

    def _evict(self, current_window: float) -> None:
        """Drop keys from earlier windows so a long-running process does not
        accumulate an entry per attempted username forever."""
        if len(self._hits) < 10_000:
            return
        stale = [k for k, (start, _) in self._hits.items() if start != current_window]
        for key in stale:
            del self._hits[key]


#: Failed logins allowed per identifier, per window.
#: Generous enough that a student fumbling their password never notices, small
#: enough that guessing an 8-character password is not viable online.
LOGIN_FAILURE_LIMIT = 10
LOGIN_WINDOW_SECONDS = 15 * 60

login_limiter = FixedWindowLimiter(
    limit=LOGIN_FAILURE_LIMIT, window_seconds=LOGIN_WINDOW_SECONDS
)
