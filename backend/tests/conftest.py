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
from app.models import AssignmentQuestion, Base, QuestionTopic, Topic
from app.services import storage
from app.services.ai import AiProvider, AiResponse
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults

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
        limiter._local_unsynced.clear()
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
        # The module-global's own pool has to go too, not just be bypassed. The
        # CI slice that sets REDIS_URL drives the login endpoint through
        # `login_limiter`, which caches a real pool on the first test's event
        # loop; `asyncio_default_fixture_loop_scope = "function"` closes that
        # loop, and the next test's checkout fails with "Event loop is closed".
        # Clearing the counters while leaving the pool cached would fix the
        # counts and keep the crash.
        with contextlib.suppress(Exception):
            await limiter.close()
        store = RedisWindowStore(
            url,
            limit=limiter.limit,
            window_seconds=limiter.window_seconds,
            # The configured timeout, not a hardcoded one: an environment that
            # raised it for a slow Redis would otherwise have cleanup time out
            # and leak counters into the next test.
            timeout=get_settings().redis_timeout_seconds,
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


# ---------------------------------------------------------------------------
# The homework pipeline's fixture chain.
#
# Shared here rather than in one test module, on the same reasoning as `fake_ai`
# above: three files now build a published assignment to submit against
# (test_homework.py, test_typed_answers.py, and the marking tests), and a copy
# per file is how they stop agreeing about what "a published assignment" is.
# ---------------------------------------------------------------------------

PDF_BYTES = b"%PDF-1.4 fake test pdf"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake test png"


@pytest.fixture
async def subject(client, tutor):
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        s = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
        )
        session.add(s)
        await session.flush()
        t1 = Topic(subject_id=s.id, code="1.3", title="Atomic structure")
        t2 = Topic(subject_id=s.id, code="1.6", title="Ionic bonding")
        session.add_all([t1, t2])
        await session.commit()
        return {"id": s.id, "topic1": t1.id, "topic2": t2.id}


@pytest.fixture
async def group(client, tutor, subject):
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    return resp.json()


@pytest.fixture
async def student(client, tutor, group):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


@pytest.fixture
async def classified(client, tutor, subject):
    resp = await client.post(
        "/api/v1/classifieds",
        data={"title": "Atomic structure classified", "subject_id": str(subject["id"])},
        files={
            "file": ("classified.pdf", PDF_BYTES, "application/pdf"),
            "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def fake_extraction(subject):
    async def _fake(session, assignment):
        q1 = AssignmentQuestion(
            assignment_id=assignment.id,
            position=0,
            number="1",
            text_summary="Define an isotope",
            max_marks=2,
            has_mark_scheme=True,
        )
        q2 = AssignmentQuestion(
            assignment_id=assignment.id,
            position=1,
            number="2",
            text_summary="Explain ionic bonding in NaCl",
            max_marks=4,
            has_mark_scheme=False,
        )
        session.add_all([q1, q2])
        await session.flush()
        session.add(QuestionTopic(question_id=q1.id, topic_id=subject["topic1"]))
        session.add(QuestionTopic(question_id=q2.id, topic_id=subject["topic2"]))

    return _fake


@pytest.fixture
async def published_assignment(client, tutor, group, classified, subject, monkeypatch):
    monkeypatch.setattr("app.services.extraction._run_extraction", fake_extraction(subject))
    resp = await client.post(
        "/api/v1/assignments",
        json={
            "group_id": group["id"],
            "classified_id": classified["id"],
            "title": "HW1 — Atomic structure",
            "question_range": "Q1-2",
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assignment = resp.json()
    assert assignment["status"] == "extracting"
    assert await process_one_job() is True

    # Successful extraction publishes automatically — students aren't blocked
    # on the tutor coming back for a second pass.
    detail = await client.get(f"/api/v1/assignments/{assignment['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "published"
    assert len(detail.json()["questions"]) == 2
    return detail.json()
