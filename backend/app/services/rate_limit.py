"""Fixed-window throttling for failed logins, shared across API instances.

Counters live in Redis when `REDIS_URL` is set, so N instances enforce **one**
limit rather than N copies of it — the third and last link of `RISK-1`'s
single-instance pinning (task 1.4, AV-83). **Redis holds rate-limit counters and
nothing else** (`E18`): Postgres remains the source of truth for all application
state, and a second use of Redis is a separate decision, not an extension of
this one.

Unset `REDIS_URL` keeps the counters in process memory, which is exactly the
behaviour that shipped before this module grew a second store — correct at one
instance, and the documented mode for local development and tests. That mirrors
`AI-20`/`INF-9`: a missing dependency degrades its own surface with a clear
message and never blocks startup.

**Redis must not become an authentication dependency in either direction**
(threat review F4, AV-97). A store that is configured but unreachable falls back
to the in-process counter and raises an alarm. Blocking every login when Redis
is sick would be an outage an attacker can trigger by degrading Redis; letting
failures go uncounted would be a free credential-stuffing window. Degrading from
one global limit to one per instance is the middle, and it is precisely today's
behaviour. The fallback is loud — `rate_limit_health()` feeds `/health/ready`
and the first failure logs at ERROR — because a silent fallback is the same as
no fallback.

Throttling is per identifier, never per IP (`SEC-14`): the API sits behind a
proxy where one shared address would mean a global lockout instead of one
blocked attacker.

The window is fixed rather than sliding: a burst that straddles a boundary can
briefly exceed the limit. That is an acceptable trade for a counter that is one
`INCR` — the goal is to make credential stuffing impractical, not to enforce an
exact quota.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

log = logging.getLogger("rate_limit")


@dataclass
class FixedWindowLimiter:
    """Counts hits per key in process memory and reports when a key is over its
    allowance.

    Pure and clock-injectable so the policy is unit-testable without sleeping.
    This is the fallback store, and the only store when `REDIS_URL` is unset.
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


class RedisWindowStore:
    """The same fixed window, counted in Redis so instances share it.

    The window start is baked into the key and every key carries a TTL, so
    rollover and cleanup are Redis's job rather than an eviction pass — the
    `_evict` this class does not need.

    Unlike `FixedWindowLimiter`, the clock here is `time.time()`, not
    `time.monotonic()`. Monotonic clocks have a per-process epoch, so two
    instances would bucket the same instant into different windows and each
    enforce its own — the exact defect this store exists to remove. The cost is
    that the window boundary moves with wall-clock skew between instances, which
    at worst shifts a boundary by the skew.
    """

    def __init__(self, url: str, *, limit: int, window_seconds: float, timeout: float) -> None:
        self.url = url
        self.limit = limit
        self.window_seconds = window_seconds
        self.timeout = timeout
        self._client: Any | None = None

    def client(self) -> Any:
        """The shared connection pool for this store.

        Built on first use and kept: redis-py's client is a pool, so
        constructing it per call would open a connection per login. Importing
        `redis` lazily keeps a deployment with no `REDIS_URL` from loading it at
        all, the same way `S3Backend` defers `boto3`.
        """
        if self._client is None:
            from redis.asyncio import Redis  # noqa: PLC0415 — deferred on purpose, see above

            self._client = Redis.from_url(
                self.url,
                # Bounded at the socket as well as at the await below, so a
                # half-open connection cannot outlive the request that opened
                # it. decode_responses because the only values here are small
                # integers and reading them as bytes buys nothing.
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout,
                decode_responses=True,
            )
        return self._client

    def _window_key(self, key: str) -> str:
        start = int(time.time() // self.window_seconds) * int(self.window_seconds)
        return f"{key}:{start}"

    @property
    def _ttl_seconds(self) -> int:
        # A minute past the window so a counter written at the last instant of a
        # window is still readable for the whole of it, and is gone well before
        # the same bucket comes round again.
        return int(self.window_seconds) + 60

    async def is_limited(self, key: str) -> bool:
        raw = await asyncio.wait_for(self.client().get(self._window_key(key)), self.timeout)
        return int(raw or 0) >= self.limit

    async def record(self, key: str) -> None:
        window_key = self._window_key(key)
        # One round trip, and MULTI/EXEC so the counter can never be left
        # without its TTL — a key that outlives its window would throttle an
        # identifier forever. EXPIRE unconditionally rather than only on the
        # first hit: re-setting the same TTL is idempotent and costs nothing,
        # where a first-hit-only EXPIRE that loses its race leaks the key.
        pipe = self.client().pipeline(transaction=True)
        pipe.incr(window_key)
        pipe.expire(window_key, self._ttl_seconds)
        await asyncio.wait_for(pipe.execute(), self.timeout)

    async def reset(self, key: str) -> None:
        await asyncio.wait_for(self.client().delete(self._window_key(key)), self.timeout)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


@dataclass
class _Degradation:
    """What `/health/ready` and the logs know about a sick Redis.

    Also the circuit breaker. Without one, every login during a Redis outage
    pays the socket timeout twice (the check and the record) before falling
    back, which turns a degraded dependency into a slow authentication endpoint
    for as long as the outage lasts — a smaller version of the outage F4 says
    must not happen.
    """

    #: Failures before the breaker opens. One is a blip; three in a row is a
    #: dependency that is down and will still be down on the next request.
    FAILURE_THRESHOLD = 3
    #: How long to skip Redis entirely once the breaker is open. Short enough
    #: that a recovered Redis is picked up within a window, long enough that a
    #: sustained outage costs one timeout per cooldown rather than per login.
    COOLDOWN_SECONDS = 30.0
    #: Log at most one ERROR per this interval. A login-rate log storm buries
    #: the alarm it is trying to raise.
    LOG_INTERVAL_SECONDS = 60.0

    consecutive_failures: int = 0
    open_until: float = 0.0
    since: float | None = None
    last_error: str | None = None
    _last_logged_at: float = 0.0

    @property
    def degraded(self) -> bool:
        return self.since is not None

    def is_open(self, now: float) -> bool:
        return now < self.open_until

    def record_failure(self, exc: BaseException, *, purpose: str, now: float) -> None:
        self.consecutive_failures += 1
        self.last_error = exc.__class__.__name__
        if self.since is None:
            self.since = now
        if self.consecutive_failures >= self.FAILURE_THRESHOLD:
            self.open_until = now + self.COOLDOWN_SECONDS
        if now - self._last_logged_at >= self.LOG_INTERVAL_SECONDS:
            self._last_logged_at = now
            # ERROR, not WARNING: throttling has silently dropped from global to
            # per-instance, which multiplies the effective limit by the instance
            # count. That is a security posture change and wants a human.
            log.error(
                "rate limit redis unavailable; falling back to the in-process counter "
                "(purpose=%s error=%s consecutive_failures=%d)",
                purpose,
                self.last_error,
                self.consecutive_failures,
                exc_info=exc,
            )

    def record_success(self) -> None:
        if self.since is not None:
            log.info("rate limit redis recovered; counters are shared again")
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.since = None
        self.last_error = None


class RateLimiter:
    """A named limit, counted in Redis when it is available and in process
    memory when it is not.

    Async because the Redis round trip is; `BE-13`/`PERF-1` forbid a blocking
    call anywhere in a request path, and the worker shares the API's event loop.
    """

    def __init__(self, *, purpose: str, limit: int, window_seconds: float) -> None:
        self.purpose = purpose
        self.limit = limit
        self.window_seconds = window_seconds
        self.local = FixedWindowLimiter(limit=limit, window_seconds=window_seconds)
        self.degradation = _Degradation()
        self._store: RedisWindowStore | None = None
        self._store_url: str | None = None

    # -- keys ------------------------------------------------------------- #

    def key(self, identifier: str, *, tenant: str | int | None = None) -> str:
        """The namespaced counter key for `identifier`.

        Namespaced by purpose and tenant so one caller cannot consume or collide
        with another's allowance (F4). Login is deliberately `global`: the
        lookup in `api/auth.py` matches an email or username across every
        organization, so there is no tenant to scope to until *after* the
        credential is accepted, and pretending otherwise would let an attacker
        pick a fresh allowance by guessing a tenant.

        The identifier is hashed, not embedded. The counters are keyed by email
        address, and a Redis keyspace is readable by anything with the
        connection string, `KEYS`/`SCAN` included — a store that is explicitly
        not the source of truth should not become a roster of who has an
        account. Debugging costs a hash of the address to match against.
        """
        digest = hashlib.sha256(identifier.encode()).hexdigest()[:32]
        return f"avora:rl:{self.purpose}:{tenant if tenant is not None else 'global'}:{digest}"

    # -- store resolution -------------------------------------------------- #

    def _redis(self) -> RedisWindowStore | None:
        """The configured store, or None when Redis is not configured.

        Re-reads `REDIS_URL` through `get_settings()` (`BE-15`) and rebuilds when
        it changes, so a test that swaps the setting is not answered by a client
        pinned to the previous value.
        """
        url = (get_settings().redis_url or "").strip()
        if not url:
            self._store = None
            self._store_url = None
            return None
        if self._store is None or self._store_url != url:
            self._store = RedisWindowStore(
                url,
                limit=self.limit,
                window_seconds=self.window_seconds,
                timeout=get_settings().redis_timeout_seconds,
            )
            self._store_url = url
        return self._store

    def _available(self, now: float) -> RedisWindowStore | None:
        store = self._redis()
        if store is None or self.degradation.is_open(now):
            return None
        return store

    # -- the limit --------------------------------------------------------- #

    async def is_limited(self, identifier: str, *, tenant: str | int | None = None) -> bool:
        """Whether `identifier` has already used up its allowance."""
        key = self.key(identifier, tenant=tenant)
        now = time.time()
        store = self._available(now)
        if store is not None:
            try:
                limited = await store.is_limited(key)
            except Exception as exc:  # noqa: BLE001 — every failure means "fall back"
                self.degradation.record_failure(exc, purpose=self.purpose, now=now)
            else:
                self.degradation.record_success()
                return limited
        return self.local.is_limited(key)

    async def record(self, identifier: str, *, tenant: str | int | None = None) -> None:
        """Count one failure against `identifier`.

        The in-process counter is written **as well as** Redis, not instead of
        it. A failure that lands just before an outage must still be visible to
        the store that takes over, and the local copy is per-process and
        short-lived anyway — double-counting an identifier that is already
        failing to authenticate costs it nothing it did not ask for.
        """
        key = self.key(identifier, tenant=tenant)
        now = time.time()
        store = self._available(now)
        if store is not None:
            try:
                await store.record(key)
            except Exception as exc:  # noqa: BLE001 — every failure means "fall back"
                self.degradation.record_failure(exc, purpose=self.purpose, now=now)
            else:
                self.degradation.record_success()
        self.local.record(key)

    async def reset(self, identifier: str, *, tenant: str | int | None = None) -> None:
        """Forget an identifier's failures, on both stores.

        Clearing only Redis would leave a user locked out by whichever instance
        counted their fumbled attempts during an outage.
        """
        key = self.key(identifier, tenant=tenant)
        now = time.time()
        store = self._available(now)
        if store is not None:
            try:
                await store.reset(key)
            except Exception as exc:  # noqa: BLE001 — every failure means "fall back"
                self.degradation.record_failure(exc, purpose=self.purpose, now=now)
            else:
                self.degradation.record_success()
        self.local.reset(key)

    # -- introspection ------------------------------------------------------ #

    def health(self) -> dict:
        """What `/health/ready` reports for this limiter.

        `configured` and `degraded` are separate answers on purpose. No Redis at
        all is the documented single-instance mode and is not a fault; Redis
        configured and unreachable is one, and is the case that needs a human
        before the next credential-stuffing run finds N times the allowance.

        `degraded` clears on the next *successful* call, not on a timer. An idle
        instance therefore keeps reporting a degradation nothing has retried,
        which is the safe direction to be wrong in: a stale alarm gets checked,
        where a self-clearing one gets missed.
        """
        configured = bool((get_settings().redis_url or "").strip())
        degraded = configured and self.degradation.degraded
        return {
            "purpose": self.purpose,
            "backend": "in_process" if (not configured or degraded) else "redis",
            "configured": configured,
            "degraded": degraded,
            "error": self.degradation.last_error if degraded else None,
            "degraded_for_seconds": (
                round(time.time() - self.degradation.since)
                if degraded and self.degradation.since is not None
                else None
            ),
        }


#: Failed logins allowed per identifier, per window.
#: Generous enough that a student fumbling their password never notices, small
#: enough that guessing an 8-character password is not viable online.
LOGIN_FAILURE_LIMIT = 10
LOGIN_WINDOW_SECONDS = 15 * 60

login_limiter = RateLimiter(
    purpose="login",
    limit=LOGIN_FAILURE_LIMIT,
    window_seconds=LOGIN_WINDOW_SECONDS,
)

#: Every limiter the app defines. A list rather than one global because the next
#: limiter (`RISK-12` wants one on the AI-triggering endpoints) must be able to
#: join the health report without changing its shape.
ALL_LIMITERS: list[RateLimiter] = [login_limiter]


def rate_limit_health() -> dict:
    """Every limiter's state, for `/health/ready`."""
    reports = [limiter.health() for limiter in ALL_LIMITERS]
    return {"ok": not any(r["degraded"] for r in reports), "limiters": reports}
