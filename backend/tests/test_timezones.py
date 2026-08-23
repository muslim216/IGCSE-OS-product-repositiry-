"""The organization's timezone, and the "today" that depends on it.

The bug this closes: every "today" was datetime.now(timezone.utc).weekday(),
so a tutor east of UTC saw yesterday's lessons for the first hours of their
local day.
"""

from datetime import datetime, time, timezone
from unittest.mock import patch

import pytest

from app.db import async_session
from app.models import Organization, ScheduleSlot, Subject, User
from app.services.timezones import (
    is_valid_timezone,
    normalize_timezone,
    now_in,
    today_weekday,
)

# ---- Validation: the value comes from a browser ----


def test_real_zone_is_accepted():
    assert is_valid_timezone("Africa/Cairo")
    assert normalize_timezone("Africa/Cairo") == "Africa/Cairo"


def test_unknown_zone_is_rejected():
    assert not is_valid_timezone("Not/AZone")
    with pytest.raises(ValueError):
        normalize_timezone("Not/AZone")


def test_junk_is_rejected_rather_than_stored():
    # Shape alone cannot tell a real zone from a fabricated one, so the check
    # is membership in the system's tz database.
    for junk in ("../../etc/passwd", "<script>", "UTC; DROP TABLE", "Europe/Nowhere"):
        with pytest.raises(ValueError):
            normalize_timezone(junk)


def test_blank_and_none_clear_rather_than_raise():
    assert normalize_timezone(None) is None
    assert normalize_timezone("") is None
    assert normalize_timezone("   ") is None


def test_unset_timezone_falls_back_to_utc():
    # Compared as a wall clock: now_in(None) must agree with UTC, not merely
    # be an aware datetime.
    assert now_in(None).utcoffset() == timezone.utc.utcoffset(None)


def test_weekday_differs_across_the_local_midnight():
    # 22:00 UTC Monday is already Tuesday 01:00 in Cairo. This is the whole
    # reason the column exists.
    monday_late = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
    assert monday_late.weekday() == 0  # Monday in UTC
    with patch("app.services.timezones.datetime") as fake:
        fake.now.side_effect = lambda tz=None: monday_late.astimezone(tz) if tz else monday_late
        assert today_weekday("Africa/Cairo") == 1  # Tuesday where the tutor is
        assert today_weekday(None) == 0  # still Monday on the UTC fallback


def test_stored_but_unloadable_zone_degrades_to_utc():
    # tzdata can be trimmed or a zone retired between the write and the read;
    # a tutor's lesson list is not worth a 500.
    with patch("app.services.timezones.ZoneInfo", side_effect=Exception("no tzdata")):
        assert now_in("Africa/Cairo").utcoffset() == timezone.utc.utcoffset(None)


# ---- The endpoints ----


async def test_signup_captures_timezone(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={
            "name": "Cairo Tutor",
            "email": "cairo@example.com",
            "password": "password123",
            "timezone": "Africa/Cairo",
        },
    )
    assert resp.status_code == 201, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    org = await client.get("/api/v1/me/organization", headers=headers)
    assert org.json()["timezone"] == "Africa/Cairo"


async def test_signup_without_timezone_leaves_it_unset(client):
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "No Zone", "email": "nozone@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    assert (await client.get("/api/v1/me/organization", headers=headers)).json()["timezone"] is None


async def test_signup_with_a_junk_timezone_still_creates_the_account(client):
    # A convenience field must not be able to block a signup; the bad value is
    # dropped and Settings can correct it.
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={
            "name": "Junk Zone",
            "email": "junk@example.com",
            "password": "password123",
            "timezone": "Not/AZone",
        },
    )
    assert resp.status_code == 201
    headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    assert (await client.get("/api/v1/me/organization", headers=headers)).json()["timezone"] is None


async def test_settings_can_set_and_clear_the_timezone(client, tutor):
    set_resp = await client.put(
        "/api/v1/me/organization/timezone",
        json={"timezone": "Africa/Cairo"},
        headers=tutor["headers"],
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["timezone"] == "Africa/Cairo"

    cleared = await client.put(
        "/api/v1/me/organization/timezone", json={"timezone": None}, headers=tutor["headers"]
    )
    assert cleared.json()["timezone"] is None


async def test_settings_rejects_an_unknown_timezone(client, tutor):
    # Unlike signup, an explicit settings write reports the problem.
    resp = await client.put(
        "/api/v1/me/organization/timezone",
        json={"timezone": "Not/AZone"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_a_student_cannot_change_the_organization_timezone(client, tutor):
    """QA-12: the negative case. This setting moves a whole roster's "today"."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4MA1",
            name="Maths",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set A", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Sara", "username": "sara01", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara01", "password": "password123"}
    )
    student_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    resp = await client.put(
        "/api/v1/me/organization/timezone",
        json={"timezone": "Africa/Cairo"},
        headers=student_headers,
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/me/organization", headers=student_headers)).status_code == 403


async def test_today_lessons_uses_org_timezone(client, tutor, monkeypatch):
    """A slot on Tuesday is returned at 01:00 Tuesday in Cairo, and is not
    returned at 23:00 the previous day — the same instant, either side of the
    local midnight UTC gets wrong."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()

    async with async_session() as session:
        # Tuesday (weekday 1)
        session.add(
            ScheduleSlot(group_id=group["id"], weekday=1, start_time=time(16, 0), duration_min=60)
        )
        user = await session.get(User, tutor["user"]["id"])
        org = await session.get(Organization, user.organization_id)
        org.timezone = "Africa/Cairo"
        await session.commit()

    # 22:00 UTC Monday == 01:00 Tuesday in Cairo: the lesson is today.
    monday_late = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
    with patch("app.services.timezones.datetime") as fake:
        fake.now.side_effect = lambda tz=None: monday_late.astimezone(tz) if tz else monday_late
        resp = await client.get("/api/v1/me/today-lessons", headers=tutor["headers"])
    assert [s["group_id"] for s in resp.json()] == [group["id"]]

    # 20:00 UTC Monday == 23:00 Monday in Cairo: not yet.
    monday_evening = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    with patch("app.services.timezones.datetime") as fake:
        fake.now.side_effect = lambda tz=None: (
            monday_evening.astimezone(tz) if tz else monday_evening
        )
        resp = await client.get("/api/v1/me/today-lessons", headers=tutor["headers"])
    assert resp.json() == []


# ---- The per-user override (AV-67) ----


async def test_a_user_can_set_and_clear_their_own_timezone(client, tutor):
    set_resp = await client.put(
        "/api/v1/me/timezone", json={"timezone": "Asia/Dubai"}, headers=tutor["headers"]
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["time_zone"] == "Asia/Dubai"
    # Readable both on the dedicated endpoint and the identity the app already has.
    assert (
        await client.get("/api/v1/me/timezone", headers=tutor["headers"])
    ).json()["time_zone"] == "Asia/Dubai"
    me = await client.get("/api/v1/auth/me", headers=tutor["headers"])
    assert me.json()["time_zone"] == "Asia/Dubai"

    cleared = await client.put("/api/v1/me/timezone", json={"timezone": None}, headers=tutor["headers"])
    assert cleared.status_code == 200
    assert cleared.json()["time_zone"] is None


async def test_a_student_can_set_their_own_timezone_but_not_the_organizations(client, tutor):
    """AV-67's whole point: the override is deliberately NOT tutor-gated."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4MA2",
            name="Maths B",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set B", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Omar", "username": "omar01", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "omar01", "password": "password123"}
    )
    student_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    own = await client.put(
        "/api/v1/me/timezone", json={"timezone": "Europe/London"}, headers=student_headers
    )
    assert own.status_code == 200
    assert own.json()["time_zone"] == "Europe/London"

    # The organization setting stays tutor-only (BE-17).
    org = await client.put(
        "/api/v1/me/organization/timezone",
        json={"timezone": "Africa/Cairo"},
        headers=student_headers,
    )
    assert org.status_code == 403


async def test_own_timezone_rejects_an_unknown_zone(client, tutor):
    resp = await client.put(
        "/api/v1/me/timezone", json={"timezone": "Not/AZone"}, headers=tutor["headers"]
    )
    assert resp.status_code == 422


async def test_own_timezone_requires_authentication(client):
    """QA-12: the negative case. A caller may only ever change their own row,
    and only when the row is behind a token at all."""
    resp = await client.put("/api/v1/me/timezone", json={"timezone": "Africa/Cairo"})
    assert resp.status_code == 401
