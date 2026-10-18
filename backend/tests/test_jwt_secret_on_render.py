"""On the server, a weak sign-in secret stops startup (`SA-04`).

With the public placeholder anyone can sign a token for any account. The
health check reported it first (#163) and read true in production; this makes
a deploy carrying the placeholder fail, leaving the previous one serving.
"""

import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_JWT_SECRET, Settings

STRONG = "s" * 32


@pytest.mark.parametrize("secret", [PLACEHOLDER_JWT_SECRET, "short", "x" * 31])
def test_a_weak_secret_on_render_refuses_to_start(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET is the public placeholder"):
        Settings(render=True, jwt_secret=secret)


def test_the_error_does_not_carry_the_secret():
    with pytest.raises(ValidationError) as raised:
        Settings(render=True, jwt_secret="short-but-private")
    assert "short-but-private" not in str(raised.value)


def test_a_real_secret_on_render_starts():
    assert Settings(render=True, jwt_secret=STRONG).jwt_secret == STRONG


def test_local_development_still_starts_on_the_placeholder():
    """`.env.example` ships it; /health/ready says 503 there instead."""
    assert Settings(render=False, jwt_secret=PLACEHOLDER_JWT_SECRET).jwt_secret_is_weak


def test_render_is_read_from_the_variable_render_sets(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("JWT_SECRET", PLACEHOLDER_JWT_SECRET)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings()
