"""Changing your own password, and a tutor renaming their student (GH-3)."""

from sqlalchemy import select

from app.db import async_session
from app.models import Organization, User
from app.models.users import UserRole
from app.security import hash_password
from app.services.rate_limit import LOGIN_FAILURE_LIMIT, login_limiter
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def _pw(client, headers, current, new):
    return await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": current, "new_password": new},
    )


async def _hash_of(user_id):
    async with async_session() as session:
        return (await session.get(User, user_id)).password_hash


async def test_wrong_current_password_is_refused_and_hash_unchanged(client, tutor):
    before = await _hash_of(tutor["user"]["id"])
    resp = await _pw(client, tutor["headers"], "not-it-at-all", "brand-new-pass")
    assert resp.status_code == 400
    assert await _hash_of(tutor["user"]["id"]) == before
    assert (await client.get("/api/v1/auth/me", headers=tutor["headers"])).status_code == 200


async def test_wrong_current_password_spends_the_signin_throttle(client, tutor):
    for _ in range(11):
        r = await _pw(client, tutor["headers"], "nope-nope", "brand-new-pass")
        if r.status_code == 429:
            break
    assert r.status_code == 429
    # The shared per-identifier counter login uses (a browser with a device
    # cookie counts on its own key, so assert on the counter, not a login).
    assert await login_limiter.is_limited(f"user:{tutor['user']['id']}\x00chpw")


async def test_new_password_keeps_registration_rules(client, tutor):
    assert (await _pw(client, tutor["headers"], "password123", "short")).status_code == 422
    assert (await _pw(client, tutor["headers"], "password123", "x" * 73)).status_code == 422


async def test_password_change_requires_auth(client):
    assert (await _pw(client, {}, "a", "bbbbbbbb")).status_code == 401


async def test_password_change_kills_old_tokens_and_keeps_this_session(client, tutor):
    old_refresh = tutor["refresh_token"]
    resp = await _pw(client, tutor["headers"], "password123", "brand-new-pass")
    assert resp.status_code == 200
    new_access = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    new_refresh = resp.cookies.get("igcse_refresh")
    assert new_refresh and new_refresh != old_refresh

    assert (await client.get("/api/v1/auth/me", headers=tutor["headers"])).status_code == 401
    old = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert old.status_code == 401

    assert (await client.get("/api/v1/auth/me", headers=new_access)).status_code == 200
    ok = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert ok.status_code == 200

    stale = await client.post(
        "/api/v1/auth/login", json={"identifier": "tutor@example.com", "password": "password123"}
    )
    assert stale.status_code == 401
    fresh = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "brand-new-pass"},
    )
    assert fresh.status_code == 200


async def test_username_only_student_can_change_password(client, tutor, world):  # noqa: F811
    made = await client.post(
        f"/api/v1/groups/{world['group']['id']}/students",
        json={"name": "Kid", "username": "kid.one", "password": "password123"},
        headers=tutor["headers"],
    )
    assert made.status_code == 201, made.text
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "kid.one", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    assert (await _pw(client, headers, "password123", "kid-new-pass1")).status_code == 200
    again = await client.post(
        "/api/v1/auth/login", json={"identifier": "kid.one", "password": "kid-new-pass1"}
    )
    assert again.status_code == 200


async def test_a_successful_change_resets_the_counter(client, tutor):
    for _ in range(3):
        await _pw(client, tutor["headers"], "nope-nope", "brand-new-pass")
    ok = await _pw(client, tutor["headers"], "password123", "brand-new-pass")
    assert ok.status_code == 200
    # Ten more wrong guesses are needed again before it locks.
    new = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        r = await _pw(client, new, "nope-nope", "another-new-pass")
    assert r.status_code == 400


async def test_wrong_guesses_do_not_lock_the_owner_out_of_login(client, tutor):
    for _ in range(LOGIN_FAILURE_LIMIT + 1):
        r = await _pw(client, tutor["headers"], "nope-nope", "brand-new-pass")
    assert r.status_code == 429
    # No device cookie, so login counts on the shared per-identifier key.
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert login.status_code == 200


async def _make_user(role, email):
    async with async_session() as session:
        org = await session.scalar(select(Organization))
        user = User(
            email=email,
            password_hash=hash_password("password123"),
            role=role,
            name="Someone",
            organization_id=org.id,
        )
        session.add(user)
        await session.commit()
        return user.id


async def _login(client, email):
    r = await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}


async def test_parent_and_admin_can_change_their_own_password(client, tutor):
    for role, email in ((UserRole.parent, "p@example.com"), (UserRole.admin, "a@example.com")):
        await _make_user(role, email)
        headers = await _login(client, email)
        assert (await _pw(client, headers, "password123", "brand-new-pass")).status_code == 200
        again = await client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": "brand-new-pass"}
        )
        assert again.status_code == 200


# --- renaming a student -------------------------------------------------------


def _url(world):
    return f"/api/v1/students/{world['student_id']}"


async def test_tutor_renames_student(client, tutor, world):  # noqa: F811
    resp = await client.patch(_url(world), json={"name": "Sara Ahmed"}, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": world["student_id"], "name": "Sara Ahmed"}
    crm = await client.get(f"{_url(world)}/crm", headers=tutor["headers"])
    assert crm.json()["student_name"] == "Sara Ahmed"


async def test_rename_trims_and_collapses_whitespace(client, tutor, world):  # noqa: F811
    resp = await client.patch(
        _url(world), json={"name": "  Sara   Ahmed "}, headers=tutor["headers"]
    )
    assert resp.json()["name"] == "Sara Ahmed"


async def test_rename_refuses_bad_names(client, tutor, world):  # noqa: F811
    for bad in ("   ", "n" * 129, "Sara\nAhmed", "Sara\u200bAhmed", "Sara\u202eAhmed"):
        resp = await client.patch(_url(world), json={"name": bad}, headers=tutor["headers"])
        assert resp.status_code == 422, bad


async def test_rename_does_not_touch_the_profile(client, tutor, world):  # noqa: F811
    await client.put(
        f"{_url(world)}/profile", json={"school": "Greenwood"}, headers=tutor["headers"]
    )
    await client.patch(_url(world), json={"name": "Sara Ahmed"}, headers=tutor["headers"])
    crm = await client.get(f"{_url(world)}/crm", headers=tutor["headers"])
    assert crm.json()["profile"]["school"] == "Greenwood"


async def test_other_organizations_tutor_cannot_rename(client, tutor, world):  # noqa: F811
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-rename@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.patch(_url(world), json={"name": "Hijack"}, headers=headers)
    assert resp.status_code == 404
    async with async_session() as session:
        assert (await session.get(User, world["student_id"])).name != "Hijack"


async def test_student_cannot_rename(client, tutor, world):  # noqa: F811
    made = await client.post(
        f"/api/v1/groups/{world['group']['id']}/students",
        json={"name": "Kid", "username": "kid.two", "password": "password123"},
        headers=tutor["headers"],
    )
    assert made.status_code == 201, made.text
    headers = await _login(client, "kid.two")
    resp = await client.patch(_url(world), json={"name": "Me"}, headers=headers)
    assert resp.status_code == 403
