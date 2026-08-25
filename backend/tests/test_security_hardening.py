"""Regression tests for the security review fixes.

Each test states the attack it blocks. They are grouped here rather than spread
across the feature files because the thing under test is the boundary, not the
feature — a future refactor of past papers or invites should have to keep these
green even if every other assertion about them changes.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db import async_session
from app.models import Invite, Submission, SubmissionFile, User
from app.services.invites import consume
from app.services.rate_limit import LOGIN_FAILURE_LIMIT, FixedWindowLimiter
from app.workers.jobs import process_one_job
from tests.test_homework import PDF_BYTES, PNG_BYTES, group, student, subject  # noqa: F401
from tests.test_past_papers import (  # noqa: F401
    _extraction_double,
    _log_attempt,
    _marking_double,
    past_paper,
)


@pytest.fixture
async def other_tutor(client):
    """A second tutor, and therefore a second Organization."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": "rival@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


# --- Session revocation ----------------------------------------------------


async def test_password_reset_revokes_existing_tokens(client, tutor, group):  # noqa: F811
    """A tutor resetting a password is evicting whoever else is using the
    account. Tokens minted before the reset must stop working — including the
    refresh token, which otherwise keeps issuing access tokens for 30 days."""
    created = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Yusuf", "username": "yusuf", "password": "original-pw"},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "yusuf", "password": "original-pw"}
    )
    stolen = login.json()["tokens"]
    stolen_headers = {"Authorization": f"Bearer {stolen['access_token']}"}
    # Not in the JSON body (SEC-2) — only ever available from the cookie.
    stolen_refresh_token = login.cookies.get("igcse_refresh")

    assert (await client.get("/api/v1/auth/me", headers=stolen_headers)).status_code == 200

    reset = await client.post(
        f"/api/v1/groups/{group['id']}/students/{created.json()['id']}/reset-password",
        json={"password": "brand-new-password"},
        headers=tutor["headers"],
    )
    assert reset.status_code == 204, reset.text

    assert (await client.get("/api/v1/auth/me", headers=stolen_headers)).status_code == 401
    replayed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": stolen_refresh_token}
    )
    assert replayed.status_code == 401


# --- Tenancy ---------------------------------------------------------------


async def test_students_cannot_see_another_organizations_past_papers(
    client,
    tutor,
    subject,
    student,
    other_tutor,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Subjects are global, so matching a past paper on subject alone would show
    every student every tutor's uploads. Scope is (organization, subject)."""
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    rival = await client.post(
        "/api/v1/past-papers",
        data={
            "subject_id": str(subject["id"]),
            "session_label": "Rival Mock 2027",
            "paper_number": "Paper 9",
        },
        files=[
            ("booklet", ("rival.pdf", PDF_BYTES, "application/pdf")),
            ("mark_scheme", ("rival-ms.pdf", PDF_BYTES, "application/pdf")),
        ],
        headers=other_tutor["headers"],
    )
    assert rival.status_code == 201, rival.text
    rival_id = rival.json()["id"]
    await process_one_job()

    listing = await client.get("/api/v1/past-papers", headers=student["headers"])
    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()] == []

    for path in (f"/{rival_id}", f"/{rival_id}/booklet", f"/{rival_id}/mark-scheme"):
        resp = await client.get(f"/api/v1/past-papers{path}", headers=student["headers"])
        assert resp.status_code in (403, 404), f"{path} -> {resp.status_code}"


async def test_students_still_see_their_own_tutors_past_papers(
    client,
    tutor,
    student,
    past_paper,  # noqa: F811
):
    """The tenancy fix must not cut students off from the papers they're set."""
    listing = await client.get("/api/v1/past-papers", headers=student["headers"])
    assert [p["id"] for p in listing.json()] == [past_paper["id"]]

    booklet = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/booklet", headers=student["headers"]
    )
    assert booklet.status_code == 200
    # The answers stay tutor-only.
    scheme = await client.get(
        f"/api/v1/past-papers/{past_paper['id']}/mark-scheme", headers=student["headers"]
    )
    assert scheme.status_code == 403


async def test_tutor_can_open_a_past_paper_submission_page(
    client,
    tutor,
    student,
    past_paper,
    other_tutor,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Submission is polymorphic: a past-paper attempt has no assignment_id, and
    reading it unconditionally used to raise AttributeError (a 500) on the one
    endpoint the tutor needs to actually review the attempt."""
    monkeypatch.setattr("app.services.marking.structured_complete", _marking_double(fake_ai))
    assert (await _log_attempt(client, student, past_paper["id"])).status_code == 201
    await process_one_job()

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        file = await session.scalar(
            select(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
        )
        path = f"/api/v1/submissions/{submission.id}/files/{file.id}"

    assert (await client.get(path, headers=student["headers"])).status_code == 200
    assert (await client.get(path, headers=tutor["headers"])).status_code == 200
    # ...and still nobody else's tutor.
    assert (await client.get(path, headers=other_tutor["headers"])).status_code == 404


# --- Invite codes ----------------------------------------------------------


async def test_group_invites_expire(client, tutor, group):  # noqa: F811
    """A join code gets pasted into a group chat and lives there forever. It is
    multi-use on purpose, so the expiry is the only thing bounding it."""
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    code = invite.json()["code"]
    assert invite.json()["expires_at"] is not None

    async with async_session() as session:
        row = await session.scalar(select(Invite).where(Invite.code == code))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": code,
            "name": "Late",
            "email": "late@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 410
    # An expired code stops disclosing the tutor and group to anyone holding it.
    assert (await client.get(f"/api/v1/auth/invites/{code}")).status_code == 410


async def test_parent_link_codes_are_single_use(client, tutor, group, student):  # noqa: F811
    """This code hands over one child's entire academic record. The second
    redemption is someone the tutor never invited."""
    code_resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    assert code_resp.status_code == 201, code_resp.text
    code = code_resp.json()["code"]

    first = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Parent One",
            "email": "p1@example.com",
            "password": "password123",
        },
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Parent Two",
            "email": "p2@example.com",
            "password": "password123",
        },
    )
    assert second.status_code == 410

    async with async_session() as session:
        assert await session.scalar(select(User).where(User.email == "p2@example.com")) is None


async def test_claiming_a_parent_code_twice_loses_the_race(client, tutor, student):  # noqa: F811
    """The single-use check above passes even if `used_at` is only set in
    Python, because the two redemptions are sequential. Two parents redeeming
    at once are not: both read `used_at IS NULL` before either writes. Claim
    the same code twice without a commit in between — the state the loser of
    that race sees — and the second must be refused by the UPDATE itself."""
    code_resp = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    code = code_resp.json()["code"]

    async with async_session() as session:
        invite = await session.scalar(select(Invite).where(Invite.code == code))
        await consume(session, invite)
        with pytest.raises(HTTPException) as exc:
            await consume(session, invite)
        assert exc.value.status_code == 410


# --- Login throttling ------------------------------------------------------


async def test_repeated_failed_logins_are_throttled(client, tutor):
    """Unlimited guesses against a known username is how a tutor-set 8-character
    student password falls."""
    for _ in range(LOGIN_FAILURE_LIMIT):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "tutor@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    blocked = await client.post(
        "/api/v1/auth/login", json={"identifier": "tutor@example.com", "password": "wrong"}
    )
    assert blocked.status_code == 429
    # The throttle holds even once the attacker guesses right.
    correct = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert correct.status_code == 429


async def test_a_successful_login_clears_the_counter(client, tutor):
    """Someone who fumbles their password twice and then gets it right must not
    be carrying those failures around."""
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        await client.post(
            "/api/v1/auth/login",
            json={"identifier": "tutor@example.com", "password": "wrong"},
        )
    ok = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tutor@example.com", "password": "password123"},
    )
    assert ok.status_code == 200
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        again = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "tutor@example.com", "password": "wrong"},
        )
        assert again.status_code == 401


def test_fixed_window_limiter_counts_and_rolls_over():
    limiter = FixedWindowLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        assert limiter.is_limited("bob", now=100.0) is False
        limiter.record("bob", now=100.0)
    assert limiter.is_limited("bob", now=100.0) is True
    assert limiter.is_limited("alice", now=100.0) is False  # keys are independent
    assert limiter.is_limited("bob", now=200.0) is False  # next window
    limiter.record("bob", now=100.0)
    limiter.reset("bob")
    assert limiter.is_limited("bob", now=100.0) is False


# --- Uploads ---------------------------------------------------------------


async def test_upload_rejects_contents_that_belie_the_declared_type(
    client,
    tutor,
    subject,  # noqa: F811
):
    """Content-Type is the client's word. A file is what its bytes say it is."""
    resp = await client.post(
        "/api/v1/classifieds",
        data={"title": "Not really a pdf", "subject_id": str(subject["id"])},
        files={"file": ("payload.pdf", b"<html><script>alert(1)</script>", "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 415


async def test_upload_still_accepts_a_real_pdf(client, tutor, subject):  # noqa: F811
    resp = await client.post(
        "/api/v1/classifieds",
        data={"title": "A real pdf", "subject_id": str(subject["id"])},
        files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text


# --- OAuth -------------------------------------------------------------
#
# test_classroom_connect_rejects_a_state_it_did_not_issue moved to
# test_classroom.py in 0.5 (AV-58): classroom.router is unmounted from the
# production `app` this file's `client` fixture serves, and that test needs
# the router actually reachable to exercise it.

# --- Response headers ------------------------------------------------------


async def test_api_responses_carry_security_headers(client):
    resp = await client.get("/api/v1/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["referrer-policy"] == "no-referrer"
