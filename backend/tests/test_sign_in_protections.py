"""A stranger cannot lock an owner out of their account (`SA-06`), and a refresh
token works once — a replayed copy ends every session (`SA-11`)."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.security import create_device_token, create_refresh_token
from app.services import refresh_sessions
from app.services.rate_limit import LOGIN_FAILURE_LIMIT

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
GOOD = {"identifier": "tutor@example.com", "password": "password123"}
BAD = {"identifier": "tutor@example.com", "password": "not-the-password"}


@pytest.fixture
async def stranger():
    """Another browser: no cookies from the owner's sign-in."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _spend_the_shared_allowance(stranger):
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await stranger.post(LOGIN, json=BAD)).status_code == 401
    assert (await stranger.post(LOGIN, json=GOOD)).status_code == 429


# --- SA-06 -------------------------------------------------------------------


async def test_a_stranger_cannot_lock_the_owner_out_of_their_own_browser(client, tutor, stranger):
    # `client` registered the tutor, so it is the owner's known browser.
    await _spend_the_shared_allowance(stranger)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200


async def test_the_shared_allowance_still_stops_a_stranger_guessing(client, tutor, stranger):
    """Negative case: the owner signing in on their own browser does not hand the
    stranger a fresh allowance."""
    await _spend_the_shared_allowance(stranger)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200
    assert (await stranger.post(LOGIN, json=GOOD)).status_code == 429


async def test_a_known_browser_is_throttled_too(client, tutor):
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await client.post(LOGIN, json=BAD)).status_code == 401
    assert (await client.post(LOGIN, json=GOOD)).status_code == 429


async def test_a_device_cookie_for_another_account_is_no_pass(tutor, stranger):
    """An attacker's own account makes their browser known to that account
    only, not to the victim's."""
    stranger.cookies.set("avora_device", create_device_token("attacker@example.com"))
    await _spend_the_shared_allowance(stranger)


async def test_a_forged_device_cookie_is_ignored(tutor, stranger):
    stranger.cookies.set("avora_device", "not-a-token")
    await _spend_the_shared_allowance(stranger)


async def test_the_device_cookie_is_not_readable_by_script(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Dev", "email": "dev@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    cookie = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("avora_device="))
    assert "httponly" in cookie.lower()
    assert "dev@example.com" not in cookie


# --- SA-11 -------------------------------------------------------------------


async def test_a_refresh_token_works_once_and_a_replay_ends_every_session(
    client, tutor, monkeypatch
):
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    first = tutor["refresh_token"]
    rotated = await client.post(REFRESH, json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.cookies.get("igcse_refresh")
    assert second and second != first
    fresh_access = {"Authorization": f"Bearer {rotated.json()['access_token']}"}

    # The thief replays the copy they took.
    assert (await client.post(REFRESH, json={"refresh_token": first})).status_code == 401
    # The replay ended the owner's session as well: neither party keeps it.
    assert (await client.post(REFRESH, json={"refresh_token": second})).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=fresh_access)).status_code == 401
    # Whoever knows the password signs straight back in.
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200


async def test_one_browser_refreshing_from_several_requests_at_once_is_not_a_replay(
    client, tutor
):
    first = tutor["refresh_token"]
    a = await client.post(REFRESH, json={"refresh_token": first})
    b = await client.post(REFRESH, json={"refresh_token": first})
    assert a.status_code == b.status_code == 200
    # Both answers carry the same current token, so the chain carries on.
    assert a.cookies.get("igcse_refresh") == b.cookies.get("igcse_refresh")
    current = b.cookies.get("igcse_refresh")
    assert (await client.post(REFRESH, json={"refresh_token": current})).status_code == 200


async def test_a_token_from_before_sessions_is_refused(client, tutor):
    import jwt

    settings = get_settings()
    now = datetime.now(timezone.utc)
    legacy = jwt.encode(
        {
            "sub": str(tutor["user"]["id"]),
            "tv": 0,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=30),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert (await client.post(REFRESH, json={"refresh_token": legacy})).status_code == 401


async def test_a_token_naming_another_users_session_is_refused(client, tutor, stranger):
    other = await stranger.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    other_token = other.cookies.get("igcse_refresh")
    from app.security import decode_refresh_token

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


async def test_using_a_session_never_carries_it_past_its_hard_limit():
    settings = get_settings()
    signed_in = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session = refresh_sessions.RefreshSession(created_at=signed_in)
    late = signed_in + timedelta(days=settings.refresh_session_max_days - 1)
    assert refresh_sessions.expires_at(session, late) == signed_in + timedelta(
        days=settings.refresh_session_max_days
    )
    early = signed_in + timedelta(days=1)
    assert refresh_sessions.expires_at(session, early) == early + timedelta(
        days=settings.refresh_token_expire_days
    )
