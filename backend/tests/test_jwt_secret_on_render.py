"""On the server, a weak sign-in secret stops startup (`SA-04`).

With the public placeholder anyone can sign a token for any account. The
health check reported it first (#163) and read true in production; this makes
a deploy carrying the placeholder fail, leaving the previous one serving.
"""

import traceback

import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_JWT_SECRET, Settings

STRONG = "s" * 32


@pytest.mark.parametrize("secret", [PLACEHOLDER_JWT_SECRET, "short", "x" * 31])
def test_a_weak_secret_on_render_refuses_to_start(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET is the public placeholder"):
        Settings(_env_file=None, render=True, jwt_secret=secret)


def test_the_error_carries_no_secret_and_no_database_password():
    """The failed-deploy log keeps whatever this prints. Pydantic would put the
    whole input in it, truncated in the middle, so a secret's last characters
    and the database password showed."""
    secret, password = "short-tail-WXYZ", "db-pass-QRST"
    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            render=True,
            jwt_secret=secret,
            database_url=f"postgresql://u:{password}@db.example.com/avora",
        )
    # What a crashed startup writes to the log: the whole traceback.
    logged = "".join(traceback.format_exception(raised.value))
    assert "is the public placeholder" in logged
    assert "WXYZ" not in logged
    assert "QRST" not in logged


def test_a_real_secret_on_render_starts():
    assert Settings(_env_file=None, render=True, jwt_secret=STRONG).jwt_secret == STRONG


def test_local_development_still_starts_on_the_placeholder():
    """`.env.example` ships it; /health/ready says 503 there instead."""
    assert Settings(
        _env_file=None, render=False, jwt_secret=PLACEHOLDER_JWT_SECRET
    ).jwt_secret_is_weak


def test_render_is_read_from_the_variable_render_sets(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("JWT_SECRET", PLACEHOLDER_JWT_SECRET)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)
