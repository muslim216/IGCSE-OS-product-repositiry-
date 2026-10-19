"""A stranger cannot lock an owner out of their account (`SA-06`), and a refresh
token works once — a replayed copy ends that sign-in (`SA-11`)."""

import logging
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.main import app
from app.models import RefreshSession, User
from app.security import (
    create_access_token,
    create_device_token,
    create_refresh_token,
    decode_refresh_token,
    known_device,
)
from app.services import refresh_sessions
from app.services.rate_limit import LOGIN_FAILURE_LIMIT, login_limiter

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
GOOD = {"identifier": "tutor@example.com", "password": "password123"}
BAD = {"identifier": "tutor@example.com", "password": "not-the-password"}


@pytest.fixture(autouse=True)
def _window_that_cannot_roll_over(monkeypatch):
    """The login window is fixed to the clock, so a test that straddles a
    15-minute boundary would see the stranger's allowance refilled mid-test."""
    monkeypatch.setattr(login_limiter.local, "window_seconds", 10.0**12)


def _browser() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def stranger():
    """Another browser: no cookies from the owner's sign-in."""
    async with _browser() as c:
        yield c


async def _spend_the_shared_allowance(stranger):
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await stranger.post(LOGIN, json=BAD)).status_code == 401
    assert (await stranger.post(LOGIN, json=GOOD)).status_code == 429


def _sign(payload: dict, secret: str | None = None) -> str:
    settings = get_settings()
    return jwt.encode(payload, secret or settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _session_rows(user_id: int) -> list[RefreshSession]:
    async with async_session() as db:
        return list(
            (
                await db.scalars(select(RefreshSession).where(RefreshSession.user_id == user_id))
            ).all()
        )


async def _token_version(user_id: int) -> int:
    async with async_session() as db:
        user = await db.get(User, user_id)
        assert user is not None
        return user.token_version


# --- SA-06 -------------------------------------------------------------------


async def test_a_stranger_cannot_lock_the_owner_out_of_their_own_browser(client, tutor, stranger):
    # `client` registered the tutor, so it is the owner's known browser.
    await _spend_the_shared_allowance(stranger)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200


async def test_the_owner_signing_in_does_not_refill_the_strangers_allowance(
    client, tutor, stranger
):
    await _spend_the_shared_allowance(stranger)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200
    assert (await stranger.post(LOGIN, json=GOOD)).status_code == 429


async def test_the_owners_typos_do_not_spend_the_shared_allowance(client, tutor, stranger):
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        assert (await client.post(LOGIN, json=BAD)).status_code == 401
    # The stranger still has every one of their own tries.
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await stranger.post(LOGIN, json=BAD)).status_code == 401
    assert (await stranger.post(LOGIN, json=BAD)).status_code == 429


async def test_a_known_browser_is_throttled_too(client, tutor):
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await client.post(LOGIN, json=BAD)).status_code == 401
    assert (await client.post(LOGIN, json=GOOD)).status_code == 429


@pytest.mark.parametrize(
    "cookie",
    [
        pytest.param(lambda tutor_id: create_device_token(tutor_id + 1000), id="another-account"),
        pytest.param(lambda tutor_id: "not-a-token", id="garbage"),
        pytest.param(
            lambda tutor_id: _sign({"type": "device", "uid": tutor_id, "nonce": "x", "exp": 1}),
            id="expired",
        ),
        pytest.param(
            lambda tutor_id: _sign(
                {"type": "device", "uid": tutor_id, "nonce": "x"}, secret="x" * 64
            ),
            id="wrong-secret",
        ),
        pytest.param(
            lambda tutor_id: create_refresh_token(
                tutor_id, 0, 1, 0, datetime.now(timezone.utc) + timedelta(days=1)
            ),
            id="a-refresh-token",
        ),
        pytest.param(lambda tutor_id: create_access_token(tutor_id, 0), id="an-access-token"),
    ],
)
async def test_only_a_real_device_cookie_for_this_account_is_a_pass(tutor, stranger, cookie):
    """Negative case: the shared allowance is spent, so any browser the server
    wrongly took as known would get a fresh allowance and sign in."""
    await _spend_the_shared_allowance(stranger)
    async with _browser() as other:
        other.cookies.set("avora_device", cookie(tutor["user"]["id"]))
        assert (await other.post(LOGIN, json=GOOD)).status_code == 429


async def test_the_pass_holds_however_the_owner_types_their_name(client, tutor, stranger):
    await _spend_the_shared_allowance(stranger)
    shouty = {"identifier": "  TUTOR@Example.com ", "password": "password123"}
    assert (await client.post(LOGIN, json=shouty)).status_code == 200


async def test_joining_through_an_invite_marks_the_browser_known(client, tutor, group):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    async with _browser() as fresh:
        resp = await fresh.post(
            "/api/v1/auth/register/student",
            json={
                "invite_code": invite.json()["code"],
                "name": "Sara",
                "email": "sara@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 201, resp.text
        user_id = resp.json()["user"]["id"]
        assert known_device(fresh.cookies.get("avora_device"), user_id) is not None
        assert fresh.cookies.get("igcse_refresh")
    assert len(await _session_rows(user_id)) == 1


async def test_a_browser_is_known_to_the_last_account_signed_in_on_it(client, tutor, stranger):
    """Pinned limit: one device cookie per browser. On a laptop two people share,
    the one who signed in last is the one the browser vouches for."""
    await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Second", "email": "second@example.com", "password": "password123"},
    )
    await _spend_the_shared_allowance(stranger)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 429


@pytest.mark.parametrize("path", ["/api/v1/auth/register/tutor", LOGIN])
async def test_the_cookies_are_not_readable_by_script(client, path):
    signup = {"name": "Dev", "email": "dev@example.com", "password": "password123"}
    if path == LOGIN:
        await client.post("/api/v1/auth/register/tutor", json=signup)
        resp = await client.post(LOGIN, json={"identifier": "dev@example.com", **signup})
    else:
        resp = await client.post(path, json=signup)
    assert resp.status_code in (200, 201), resp.text
    cookies = resp.headers.get_list("set-cookie")
    for name in ("avora_device=", "igcse_refresh="):
        cookie = next(h for h in cookies if h.startswith(name)).lower()
        assert "httponly" in cookie
        assert "path=/api/v1/auth" in cookie
        assert "samesite=lax" in cookie
        assert "dev@example.com" not in cookie
    refresh_cookie = next(h for h in cookies if h.startswith("igcse_refresh="))
    assert f"Max-Age={get_settings().refresh_session_max_days * 86400}" in refresh_cookie


# --- SA-11 -------------------------------------------------------------------


async def test_a_refresh_token_works_once_and_a_replay_ends_that_sign_in(
    client, tutor, stranger, monkeypatch, caplog
):
    assert get_settings() is get_settings()  # the patch below reaches the app
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    # The same account signed in on a second browser too.
    other = await stranger.post(LOGIN, json=GOOD)
    assert other.status_code == 200
    other_refresh = other.cookies.get("igcse_refresh")
    version = await _token_version(tutor["user"]["id"])

    first = tutor["refresh_token"]
    rotated = await client.post(REFRESH, json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.cookies.get("igcse_refresh")
    assert second and second != first

    # The thief replays the copy they took.
    with caplog.at_level(logging.WARNING, logger="auth"):
        assert (await client.post(REFRESH, json={"refresh_token": first})).status_code == 401
    assert "refresh token replayed" in caplog.text
    # The chain is gone for the owner too: neither party keeps it.
    assert (await client.post(REFRESH, json={"refresh_token": second})).status_code == 401
    # Only that chain. The other browser carries on, and nothing else was revoked.
    assert (await stranger.post(REFRESH, json={"refresh_token": other_refresh})).status_code == 200
    assert await _token_version(tutor["user"]["id"]) == version
    # Whoever knows the password signs straight back in.
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200


async def test_one_browser_refreshing_from_several_requests_at_once_is_not_a_replay(client, tutor):
    first = tutor["refresh_token"]
    a = await client.post(REFRESH, json={"refresh_token": first})
    b = await client.post(REFRESH, json={"refresh_token": first})
    assert a.status_code == 200
    assert b.status_code == 200
    # Both answers carry the same current token, so the chain carries on.
    assert a.cookies.get("igcse_refresh") == b.cookies.get("igcse_refresh")
    current = b.cookies.get("igcse_refresh")
    assert (await client.post(REFRESH, json={"refresh_token": current})).status_code == 200


async def test_the_grace_covers_only_the_token_just_replaced(client, tutor):
    """Negative case: a token two generations old is a replay even inside the
    grace window."""
    first = tutor["refresh_token"]
    second = (await client.post(REFRESH, json={"refresh_token": first})).cookies["igcse_refresh"]
    third = (await client.post(REFRESH, json={"refresh_token": second})).cookies["igcse_refresh"]
    assert (await client.post(REFRESH, json={"refresh_token": first})).status_code == 401
    assert (await client.post(REFRESH, json={"refresh_token": third})).status_code == 401


async def test_the_token_just_replaced_is_refused_once_the_grace_has_passed(client, tutor):
    first = tutor["refresh_token"]
    assert (await client.post(REFRESH, json={"refresh_token": first})).status_code == 200
    [row] = await _session_rows(tutor["user"]["id"])
    grace = get_settings().refresh_reuse_grace_seconds
    async with async_session() as db:
        session = await db.get(RefreshSession, row.id)
        assert session is not None
        session.rotated_at = datetime.now(timezone.utc) - timedelta(seconds=grace + 1)
        await db.commit()
    assert (await client.post(REFRESH, json={"refresh_token": first})).status_code == 401
    assert await _session_rows(tutor["user"]["id"]) == []


async def test_a_token_from_before_sessions_is_refused(client, tutor):
    now = datetime.now(timezone.utc)
    legacy = _sign(
        {
            "sub": str(tutor["user"]["id"]),
            "tv": 0,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=30),
        }
    )
    assert (await client.post(REFRESH, json={"refresh_token": legacy})).status_code == 401


async def test_an_expired_refresh_token_is_refused(client, tutor):
    [row] = await _session_rows(tutor["user"]["id"])
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = create_refresh_token(tutor["user"]["id"], 0, row.id, row.generation, past)
    assert (await client.post(REFRESH, json={"refresh_token": expired})).status_code == 401


async def test_a_device_token_is_not_a_refresh_or_access_token(client, tutor):
    device = client.cookies.get("avora_device")
    assert device
    assert (await client.post(REFRESH, json={"refresh_token": device})).status_code == 401
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {device}"})
    assert me.status_code == 401


async def test_a_token_naming_another_users_session_is_refused(client, tutor, stranger):
    other = await stranger.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other_token = other.cookies.get("igcse_refresh")
    decoded = decode_refresh_token(other_token)
    assert decoded is not None
    _, _, other_session, other_gen = decoded
    forged = create_refresh_token(
        tutor["user"]["id"],
        0,
        other_session,
        other_gen,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert (await client.post(REFRESH, json={"refresh_token": forged})).status_code == 401
    # Refusing it did not end the other user's session.
    assert (await stranger.post(REFRESH, json={"refresh_token": other_token})).status_code == 200


async def test_a_refresh_never_carries_a_sign_in_past_its_hard_limit(client, tutor):
    max_days = get_settings().refresh_session_max_days
    [row] = await _session_rows(tutor["user"]["id"])
    signed_in = datetime.now(timezone.utc) - timedelta(days=max_days - 1)
    async with async_session() as db:
        session = await db.get(RefreshSession, row.id)
        assert session is not None
        session.created_at = signed_in
        await db.commit()
    resp = await client.post(REFRESH, json={"refresh_token": tutor["refresh_token"]})
    assert resp.status_code == 200
    payload = jwt.decode(
        resp.cookies["igcse_refresh"],
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    assert payload["exp"] <= (signed_in + timedelta(days=max_days)).timestamp() + 1


async def test_an_unused_sign_in_lapses_after_the_idle_limit():
    settings = get_settings()
    signed_in = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session = RefreshSession(created_at=signed_in)
    used = signed_in + timedelta(days=1)
    assert refresh_sessions.expires_at(session, used) == used + timedelta(
        days=settings.refresh_token_expire_days
    )


async def test_signing_in_clears_only_this_users_lapsed_sessions(client, tutor, stranger):
    other = await stranger.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other_id = other.json()["user"]["id"]
    old = datetime.now(timezone.utc) - timedelta(days=get_settings().refresh_session_max_days + 1)
    async with async_session() as db:
        for row in [*await _session_rows(tutor["user"]["id"]), *await _session_rows(other_id)]:
            session = await db.get(RefreshSession, row.id)
            assert session is not None
            session.created_at = old
        await db.commit()
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200
    assert len(await _session_rows(tutor["user"]["id"])) == 1  # just the new one
    assert len(await _session_rows(other_id)) == 1  # untouched


async def test_logout_clears_the_users_sessions(client, tutor):
    assert await _session_rows(tutor["user"]["id"])
    resp = await client.post("/api/v1/auth/logout", headers=tutor["headers"])
    assert resp.status_code == 204
    assert await _session_rows(tutor["user"]["id"]) == []
