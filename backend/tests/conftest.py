import os

# Configure the app for tests BEFORE any app module is imported.
import tempfile

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-0123456789-abcdefghijklmnop"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="igcse-test-uploads-")
os.environ["REFRESH_COOKIE_SECURE"] = "false"

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import engine
from app.main import app
from app.models import Base
from app.services.ai import AiProvider, AiResponse


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


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    """The failed-login counter is a process-global, so without this a test that
    submits bad passwords would leak its count into every later test."""
    from app.services.rate_limit import login_limiter

    login_limiter._hits.clear()
    yield
    login_limiter._hits.clear()


@pytest.fixture(autouse=True)
async def _db_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def hidden_client():
    """The app as it would be with AV-58 un-hidden: every production router,
    plus `classroom` and `knowledge`, which `main.create_app` deliberately does
    not mount.

    Hiding those two removed their HTTP surface, not their code — services,
    models and tables all stay. Their test suites therefore keep running,
    against this app rather than the real one. Deleting them instead would
    leave the hidden code unverified, and the first person to un-hide it would
    be the one to discover it had rotted. That is the same reasoning that keeps
    both modules *imported* in main.py behind a noqa.

    `test_a_hidden_route_is_absent_from_the_real_app` in test_authorization.py
    is the other half of this: it asserts the *production* app still 404s them.

    Note this app is rebuilt per test rather than shared. That is cheap and
    keeps no state of its own, but it isolates nothing either: the login rate
    limiter and the job-handler registry are module-level and shared by every
    app in the process. Isolation here rides on the autouse fixtures above, not
    on this fixture — worth knowing before copying the pattern.
    """
    from app.api import classroom, knowledge
    from app.main import create_app

    unhidden = create_app()
    for router in (classroom.router, knowledge.router):
        unhidden.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=unhidden)
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
