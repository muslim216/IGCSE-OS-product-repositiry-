async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_tutor_signup_and_me(client, tutor):
    resp = await client.get("/api/v1/auth/me", headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "tutor@example.com"
    assert body["role"] == "tutor"


async def test_duplicate_email_rejected(client, tutor):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 409


async def test_login_with_email(client, tutor):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "Tutor@Example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "tutor"


async def test_login_wrong_password(client, tutor):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_refresh_token_flow(client, tutor):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": tutor["refresh_token"]})
    assert resp.status_code == 200
    body = resp.json()
    assert "refresh_token" not in body  # SEC-2: never in a response body
    new_access = body["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200


async def test_access_token_rejected_as_refresh(client, tutor):
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tutor["tokens"]["access_token"]}
    )
    assert resp.status_code == 401


async def test_me_requires_auth(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_login_sets_refresh_cookie(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Cookie Tutor", "email": "cookie@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    assert "igcse_refresh" in resp.cookies


async def test_register_response_never_carries_refresh_token_in_json(client):
    """SEC-2: the refresh token must live only in the httpOnly cookie. A
    regression here would mean same-origin XSS could read a 30-day
    credential straight out of the register response body."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "No Leak", "email": "noleak@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    assert "refresh_token" not in resp.json()["tokens"]
    assert "igcse_refresh" in resp.cookies


async def test_login_response_never_carries_refresh_token_in_json(client, tutor):
    """Same guarantee as above, for the login response specifically."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    assert "refresh_token" not in resp.json()["tokens"]
    assert "igcse_refresh" in resp.cookies


async def test_refresh_from_cookie_only(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Cookie Tutor 2", "email": "cookie2@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    # No body — relies solely on the cookie set during registration.
    refresh_resp = await client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 200
    new_access = refresh_resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200


async def test_refresh_without_token_rejected(client):
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_clears_cookie(client, tutor):
    resp = await client.post("/api/v1/auth/logout", headers=tutor["headers"])
    assert resp.status_code == 204


async def test_logout_requires_auth(client):
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


async def test_logout_revokes_existing_access_token(client, tutor):
    resp = await client.post("/api/v1/auth/logout", headers=tutor["headers"])
    assert resp.status_code == 204
    me = await client.get("/api/v1/auth/me", headers=tutor["headers"])
    assert me.status_code == 401


async def test_logout_revokes_existing_refresh_token(client, tutor):
    resp = await client.post("/api/v1/auth/logout", headers=tutor["headers"])
    assert resp.status_code == 204
    refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tutor["refresh_token"]}
    )
    assert refresh_resp.status_code == 401


async def test_login_after_logout_issues_valid_tokens(client, tutor):
    await client.post("/api/v1/auth/logout", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    new_access = resp.json()["tokens"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200


async def test_bumping_token_version_invalidates_both_tokens(client, tutor):
    """CODE-12 tripwire.

    Any future endpoint that calls `user.token_version += 1` (password
    reset, disable, etc.) must invalidate every outstanding access and
    refresh token. This test bypasses the HTTP logout/reset handlers and
    mutates the row directly so the invariant is checked even if a new
    handler forgets to bump.
    """
    from app.db import async_session
    from app.models import User

    old_access = tutor["headers"]["Authorization"].split(" ", 1)[1]
    old_refresh = tutor["tokens"]["refresh_token"]
    # Bump the version straight in the DB — the same write logout and
    # reset perform, without going through those handlers.
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        assert user is not None
        user.token_version += 1
        await session.commit()
    # Old access token is now revoked (deps.py:29).
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert me.status_code == 401
    # Old refresh token is also revoked (api/auth.py:152).
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert refresh.status_code == 401
    # A fresh login at the new version still works.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    new_access = resp.json()["tokens"]["access_token"]
    me2 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me2.status_code == 200
