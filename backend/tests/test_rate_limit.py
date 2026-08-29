"""Task 1.4 (AV-83): failed-login throttling shared across API instances.

Two halves, tested separately because they fail for different reasons.

The **fallback** half needs no Redis and always runs: a configured Redis that
has stopped answering must degrade to the in-process counter, stay loud about
it, and stop hammering the dead dependency. Threat review F4 says the fallback
needs its own test and its own alert, on the grounds that a silent fallback is
the same as no fallback — so these assert the log line and the `/health/ready`
answer, not only that logins kept working.

The **Redis** half is skipped without `TEST_REDIS_URL` and is the only thing
that proves counters are actually shared. It follows the lesson from task 1.3:
a fake that never runs the real client would pass while exercising nothing, and
the green tick then gets cited as evidence. CI sets `TEST_REDIS_URL` against a
real `redis:7-alpine` service and fails if these skip.
"""

import logging
import os
import time

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.services.rate_limit import (
    LOGIN_FAILURE_LIMIT,
    RateLimiter,
    RedisWindowStore,
    login_limiter,
)

REDIS_URL = os.environ.get("TEST_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set")


class BrokenRedis:
    """A client that fails the way a dead Redis does: every call raises.

    Counts its calls so a test can assert the breaker actually stopped calling
    it, which is the difference between "we fall back" and "we fall back after
    paying the timeout on every single login".
    """

    def __init__(self) -> None:
        self.calls = 0

    async def ping(self):
        self.calls += 1
        raise ConnectionError("redis is down")

    async def get(self, key):
        self.calls += 1
        raise ConnectionError("redis is down")

    async def delete(self, key):
        self.calls += 1
        raise ConnectionError("redis is down")

    def pipeline(self, transaction=True):
        return self

    def incr(self, key):
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        self.calls += 1
        raise ConnectionError("redis is down")


class InMemoryRedis:
    """Just enough Redis to stand in for a healthy one in the recovery test.

    Deliberately NOT used for the sharing tests below — proving counters are
    shared against a dictionary would prove nothing about Redis.
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    def pipeline(self, transaction=True):
        return self

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        return [None, None]


@pytest.fixture
def broken_redis(monkeypatch):
    """A limiter configured for Redis, whose Redis is down."""
    monkeypatch.setattr(get_settings(), "redis_url", "redis://unreachable.invalid:6379/0")
    client = BrokenRedis()
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: client)
    return client


# --- Configuration ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "redis://localhost:6379/0",
        "redis://127.0.0.1:6379/0",
        "redis://redis:6379/0",  # a compose service name on a private network
        "rediss://:secret@shared-redis.example.com:6379/0",
        "",
    ],
)
def test_settings_accept_a_redis_url_that_cannot_leak_its_password(url):
    Settings(redis_url=url, jwt_secret="x")


@pytest.mark.parametrize(
    "url",
    [
        "redis://:secret@shared-redis.example.com:6379/0",
        "redis://10.0.0.5:6379/0",
    ],
)
def test_settings_reject_cleartext_redis_to_an_off_box_host(url):
    """CWE-319. A managed Redis URL carries its password inline, and `redis://`
    sends that AUTH in the clear. Startup is the only place to catch it —
    `Redis.from_url` will connect happily."""
    with pytest.raises(ValidationError, match="cleartext"):
        Settings(redis_url=url, jwt_secret="x")


@pytest.mark.parametrize("timeout", [0, -1, 30])
def test_settings_reject_an_unusable_redis_timeout(timeout):
    """Zero makes every call time out instantly, which is indistinguishable from
    a permanent outage — the limiter would degrade to per-instance counting on a
    config typo and say so only in /health/ready."""
    with pytest.raises(ValidationError, match="REDIS_TIMEOUT_SECONDS"):
        Settings(redis_timeout_seconds=timeout, jwt_secret="x")


# --- Keys ------------------------------------------------------------------


def test_keys_are_namespaced_by_purpose_and_tenant():
    """F4: one caller must not be able to consume or collide with another's
    allowance."""
    login = RateLimiter(purpose="login", limit=3, window_seconds=60)
    other = RateLimiter(purpose="ai_calls", limit=3, window_seconds=60)

    assert login.key("a@example.com") != other.key("a@example.com")
    assert login.key("a@example.com", tenant=1) != login.key("a@example.com", tenant=2)
    assert login.key("a@example.com") != login.key("b@example.com")
    assert login.key("a@example.com").startswith("avora:rl:login:global:")


def test_keys_do_not_carry_the_identifier_in_the_clear():
    """A Redis keyspace is readable by anything holding the connection string.
    The counters must not double as a roster of who has an account."""
    assert "a@example.com" not in login_limiter.key("a@example.com")


# --- Fallback (threat review F4) -------------------------------------------


async def test_a_dead_redis_still_throttles_through_the_in_process_counter(broken_redis):
    """Logins are never left uncounted: that would be a free credential-stuffing
    window for as long as Redis is unwell."""
    limiter = RateLimiter(purpose="login", limit=3, window_seconds=60)

    for _ in range(3):
        assert await limiter.is_limited("victim@example.com") is False
        await limiter.record("victim@example.com")

    assert await limiter.is_limited("victim@example.com") is True
    assert await limiter.is_limited("someone-else@example.com") is False


async def test_a_dead_redis_never_blocks_a_login(broken_redis):
    """The other direction of F4: a degraded Redis must not become an
    authentication outage an attacker can trigger by degrading Redis."""
    limiter = RateLimiter(purpose="login", limit=3, window_seconds=60)

    assert await limiter.is_limited("nobody@example.com") is False
    await limiter.reset("nobody@example.com")  # must not raise either


async def test_the_fallback_raises_an_alarm(broken_redis, caplog):
    """A silent fallback is the same as no fallback, so the alarm is part of the
    contract, not a nicety."""
    limiter = RateLimiter(purpose="login", limit=3, window_seconds=60)

    with caplog.at_level(logging.ERROR, logger="rate_limit"):
        await limiter.record("victim@example.com")

    assert any(
        "rate limit redis unavailable" in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    )
    health = await limiter.health()
    assert health["degraded"] is True
    assert health["backend"] == "in_process"
    assert health["error"] == "ConnectionError"


async def test_the_breaker_stops_calling_a_dead_redis(broken_redis):
    """Without this, every login during an outage pays the socket timeout twice
    before falling back — a slow authentication endpoint for the whole outage."""
    limiter = RateLimiter(purpose="login", limit=100, window_seconds=60)

    for _ in range(10):
        await limiter.record("victim@example.com")

    # Opens on the third consecutive failure and then skips Redis entirely.
    assert broken_redis.calls == limiter.degradation.FAILURE_THRESHOLD


async def test_a_recovered_redis_is_used_again(monkeypatch):
    """The breaker must be a pause, not a one-way door: a Redis that comes back
    has to resume counting globally without a restart."""
    limiter = RateLimiter(purpose="login", limit=100, window_seconds=60)
    monkeypatch.setattr(get_settings(), "redis_url", "redis://unreachable.invalid:6379/0")
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: BrokenRedis())

    # Enough failures to actually OPEN the breaker. One is not: below
    # FAILURE_THRESHOLD the store is still being called, so a regression where
    # an open breaker never reconnects would sail through.
    for _ in range(limiter.degradation.FAILURE_THRESHOLD):
        await limiter.record("victim@example.com")
    assert limiter.degradation.degraded is True
    assert limiter.degradation.is_open(time.time()) is True

    healthy = InMemoryRedis()
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: healthy)
    limiter.degradation.open_until = 0.0  # the cooldown elapsing, without sleeping

    await limiter.record("victim@example.com")
    assert limiter.degradation.degraded is False
    assert (await limiter.health())["backend"] == "redis"
    assert healthy.store, "the recovered store must actually have been written to"


async def test_a_recovered_redis_does_not_hand_back_a_fresh_allowance(monkeypatch):
    """Regression: failures counted during an outage are never backfilled into
    Redis, so reading only the Redis answer after recovery would restart the
    attacker at zero — the outage would *buy* a second full allowance."""
    limiter = RateLimiter(purpose="login", limit=3, window_seconds=60)
    monkeypatch.setattr(get_settings(), "redis_url", "redis://unreachable.invalid:6379/0")
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: BrokenRedis())

    for _ in range(3):
        await limiter.record("victim@example.com")
    assert await limiter.is_limited("victim@example.com") is True

    # Redis comes back, and knows nothing about those three failures.
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: InMemoryRedis())
    limiter.degradation.open_until = 0.0

    assert await limiter.is_limited("victim@example.com") is True
    assert limiter.degradation.degraded is False


async def test_a_reset_clears_both_stores(monkeypatch):
    """The other side of the OR: once both stores can say 'limited', a
    successful login has to clear both or the user stays locked out."""
    limiter = RateLimiter(purpose="login", limit=2, window_seconds=60)
    monkeypatch.setattr(get_settings(), "redis_url", "redis://unreachable.invalid:6379/0")
    monkeypatch.setattr(RedisWindowStore, "client", lambda self: InMemoryRedis())

    for _ in range(2):
        await limiter.record("forgetful@example.com")
    assert await limiter.is_limited("forgetful@example.com") is True

    await limiter.reset("forgetful@example.com")
    assert await limiter.is_limited("forgetful@example.com") is False


# --- /health/ready ---------------------------------------------------------


async def test_readiness_is_not_degraded_when_no_redis_is_configured(client, monkeypatch):
    """No Redis at all is the documented single-instance mode, not a fault. It
    must not turn every deployment's readiness check red.

    `redis_url` is cleared explicitly rather than relied on being empty: CI runs
    one slice of this suite with REDIS_URL set, and a test asserting the
    unconfigured behaviour must assert it, not inherit it."""
    monkeypatch.setattr(get_settings(), "redis_url", None)
    body = (await client.get("/api/v1/health/ready")).json()

    assert body["rate_limit"]["ok"] is True
    limiter = body["rate_limit"]["limiters"][0]
    assert limiter["configured"] is False
    assert limiter["degraded"] is False
    assert limiter["backend"] == "in_process"


async def test_readiness_reports_a_configured_redis_that_stopped_answering(
    client, broken_redis, tutor
):
    """This is the alert. Throttling has silently dropped from one global limit
    to one per instance, which multiplies the effective allowance by the
    instance count — a security posture change with no other symptom."""
    await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "wrong"},
    )

    resp = await client.get("/api/v1/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["rate_limit"]["ok"] is False
    assert body["rate_limit"]["limiters"][0]["degraded"] is True


async def test_readiness_probes_rather_than_remembering(client, broken_redis):
    """A fresh instance has observed nothing. Reporting only past observations
    would call a configured-but-refusing Redis healthy until the next login —
    hours, on a quiet night. Readiness PINGs instead."""
    assert broken_redis.calls == 0  # nothing has touched Redis yet

    resp = await client.get("/api/v1/health/ready")

    assert resp.status_code == 503
    limiter = resp.json()["rate_limit"]["limiters"][0]
    assert limiter["reachable"] is False
    assert limiter["degraded"] is True
    assert broken_redis.calls > 0, "readiness must actually probe"


# --- The endpoint still throttles ------------------------------------------


async def test_login_still_returns_429_over_the_limit_with_redis_down(client, broken_redis, tutor):
    """The negative case QA-12 asks for, on the degraded path specifically."""
    for _ in range(LOGIN_FAILURE_LIMIT):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "tutor@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "wrong"},
    )
    assert blocked.status_code == 429


# --- The Redis path itself -------------------------------------------------


@pytest.fixture
def redis_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", REDIS_URL)
    return REDIS_URL


@needs_redis
async def test_two_instances_share_one_limit(redis_settings):
    """The whole point of the task, and 1.5's second acceptance case in
    miniature: failed logins spread across two API processes trip ONE limit.

    Two `RateLimiter` objects stand in for two instances — separate in-process
    counters, one Redis. If the counting quietly fell back to the local store
    this would pass by accident, so the local counters are asserted to be the
    thing that could NOT have produced the answer.
    """
    api_one = RateLimiter(purpose="login_test_shared", limit=4, window_seconds=60)
    api_two = RateLimiter(purpose="login_test_shared", limit=4, window_seconds=60)
    identifier = "attacker-target@example.com"
    await api_one.reset(identifier)

    try:
        for _ in range(2):
            await api_one.record(identifier)
        for _ in range(2):
            await api_two.record(identifier)

        assert await api_one.is_limited(identifier) is True
        assert await api_two.is_limited(identifier) is True
        # Neither local counter reached 4 on its own.
        assert api_one.local.is_limited(api_one.key(identifier)) is False
        assert api_two.local.is_limited(api_two.key(identifier)) is False
        assert api_one.degradation.degraded is False
    finally:
        await api_one.reset(identifier)
        await api_one._redis().close()
        await api_two._redis().close()


@needs_redis
async def test_a_successful_login_clears_the_shared_counter(redis_settings):
    """A user who finally remembers their password must not still be locked out
    by the instance that did not serve their successful attempt."""
    api_one = RateLimiter(purpose="login_test_reset", limit=2, window_seconds=60)
    api_two = RateLimiter(purpose="login_test_reset", limit=2, window_seconds=60)
    identifier = "forgetful@example.com"

    try:
        await api_one.record(identifier)
        await api_one.record(identifier)
        assert await api_two.is_limited(identifier) is True

        await api_two.reset(identifier)
        assert await api_one.is_limited(identifier) is False
    finally:
        await api_one.reset(identifier)
        await api_one._redis().close()
        await api_two._redis().close()


@needs_redis
async def test_every_counter_carries_a_ttl(redis_settings):
    """A counter that outlives its window would throttle an identifier forever,
    and nothing else in this design ever deletes it."""
    limiter = RateLimiter(purpose="login_test_ttl", limit=5, window_seconds=60)
    identifier = "ttl@example.com"
    store = limiter._redis()

    try:
        await limiter.record(identifier)
        ttl = await store.client().ttl(store._window_key(limiter.key(identifier)))
        assert 0 < ttl <= 60 + 60
    finally:
        await limiter.reset(identifier)
        await store.close()
