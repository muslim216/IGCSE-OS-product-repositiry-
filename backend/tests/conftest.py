import os

# Configure the app for tests BEFORE any app module is imported.
import tempfile

# SQLite in memory is the default and stays the default: the suite is fast,
# needs no service, and QA-11 covers migrations separately. TEST_DATABASE_URL
# overrides it for the tests that are meaningless on SQLite — the multi-worker
# claim tests need real `FOR UPDATE SKIP LOCKED`, which SQLite silently drops
# (task 1.3, AV-82).
#
# Be clear about the blast radius: this sets DATABASE_URL process-wide, so
# TEST_DATABASE_URL points the WHOLE run at that database, not just the
# Postgres-only tests. What keeps everything else on SQLite is selecting only
# those tests — which is what CI does (`pytest tests/test_worker_concurrency.py`
# in the migrations job). Setting it for a full run is supported but means
# every test runs against that database, so point it at a throwaway one.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["JWT_SECRET"] = "test-secret-key-0123456789-abcdefghijklmnop"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="igcse-test-uploads-")
os.environ["REFRESH_COOKIE_SECURE"] = "false"

import contextlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import engine
from app.main import app
from app.models import Base
from app.services import storage
from app.services.ai import AiProvider, AiResponse

#: Whether this run is against the disposable in-memory SQLite. Guards the
#: destructive schema teardown in `_db_schema`, which must never drop tables in
#: a real database. Read at fixture time, so it sits below the imports rather
#: than in the env block above.
_USING_THROWAWAY_SQLITE = "TEST_DATABASE_URL" not in os.environ


def _fake_structured_complete(parsed, *, model: str = "test-model", tokens: int = 10):
    async def _call(**kwargs) -> AiResponse:
        return AiResponse(
            provider=AiProvider.anthropic,
            model=model,
            prompt_version="test",
            input_tokens=tokens,
            output_tokens=tokens,
            parsed=parsed,
        )

    return _call


@pytest.fixture
def fake_ai():
    """Factory for a services.ai.structured_complete stand-in that skips the
    network and hands back `parsed` in the normalized AiResponse shape.
    Monkeypatch it over the *calling* module's name:

        monkeypatch.setattr(
            "app.services.marking.structured_complete", fake_ai(result)
        )
    """
    return _fake_structured_complete


class FakeSigningBackend(storage.LocalBackend):
    """A local backend that also mints signed URLs, standing in for S3 so the
    F3 serving split (proxy vs. signed redirect) can be tested without a real
    object store. Shared here rather than living in one test module, since
    both test_storage.py and test_homework.py need to swap it in — the same
    reason `fake_ai` above lives in conftest rather than one caller's file."""

    def get_signed_url(self, key, *, mime, filename, expires_in):
        return f"https://objects.example/{key}?sig=deadbeef&expires={expires_in}"


@pytest.fixture
def signing_storage(monkeypatch):
    backend = FakeSigningBackend()
    monkeypatch.setattr(storage, "get_storage", lambda: backend)
    return backend


@pytest.fixture(autouse=True)
async def _reset_login_limiter():
    """The failed-login counters are process-globals, so without this a test that
    submits bad passwords would leak its count into every later test.

    Resets *whichever store is active* (task 1.4, AV-83), not just the in-process
    dict. A test running against a real Redis would otherwise carry its counts
    into the next test through a store this fixture never touched, and a test
    that tripped the breaker would leave every later limiter call degraded —
    both of which fail somewhere other than where they were caused.

    Async, so the Redis flush runs on the test's own loop rather than a loop this
    fixture invented; the same reasoning as `_db_schema` below.
    """
    await _clear_limiters()
    yield
    await _clear_limiters()


async def _clear_limiters():
    from app.services.rate_limit import ALL_LIMITERS, RedisWindowStore, _Degradation

    for limiter in ALL_LIMITERS:
        limiter.local._hits.clear()
        limiter.degradation = _Degradation()
        url = (get_settings().redis_url or "").strip()
        if not url:
            continue
        # A store built and closed inside this call, NOT `limiter._redis()`.
        # That one caches its pool on a module-global limiter, so the pool would
        # be created on the first test's event loop and reused by every later
        # test on its own — `asyncio_default_fixture_loop_scope = "function"`
        # tears each of those down, and the next checkout fails with
        # "Event loop is closed" from inside this fixture, which is the worst
        # possible place to read a traceback from.
        store = RedisWindowStore(
            url, limit=limiter.limit, window_seconds=limiter.window_seconds, timeout=1.0
        )
        try:
            client = store.client()
            # By namespace prefix, because the keys are hashed and there is no
            # identifier list to delete by name. Scoped to this limiter's own
            # prefix, never FLUSHDB: a developer pointing REDIS_URL at a Redis
            # that holds anything else must not lose it.
            async for key in client.scan_iter(match=f"avora:rl:{limiter.purpose}:*", count=500):
                await client.delete(key)
        except Exception:  # noqa: BLE001
            # A stopped local Redis must not turn the whole suite red. The local
            # counter and the breaker were already reset above, which is what
            # isolates the tests that do not need Redis — mirroring the
            # production limiter, which falls back rather than raising (F4).
            pass
        finally:
            with contextlib.suppress(Exception):
                await store.close()


@pytest.fixture(autouse=True)
async def _db_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Only ever drop the throwaway in-memory SQLite schema. Against a real
    # database (TEST_DATABASE_URL) this teardown would drop every table after
    # every test — in CI's migrations job that means deleting the schema
    # Alembic just built and verified, and against any other Postgres someone
    # points this at, it is straightforward data loss. Postgres-only tests
    # clean up the rows they create instead; see tests/test_worker_concurrency.py.
    if _USING_THROWAWAY_SQLITE:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def tutor(client):
    """A registered tutor with auth headers ready to use."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Test Tutor", "email": "tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
        "tokens": data["tokens"],
        # Not in the JSON body (SEC-2) — only ever available from the cookie.
        "refresh_token": resp.cookies.get("igcse_refresh"),
    }
