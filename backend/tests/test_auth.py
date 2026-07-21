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
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tutor["tokens"]["refresh_token"]}
    )
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
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
        "/api/v1/auth/refresh", json={"refresh_token": tutor["tokens"]["refresh_token"]}
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
