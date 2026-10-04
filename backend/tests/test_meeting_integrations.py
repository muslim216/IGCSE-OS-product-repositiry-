"""Zoom and Google Meet attendance (task 7.3, AV-118).

Nothing here reaches Zoom or Google (`QA-8`): the provider functions are
monkeypatched, and the HTTP layer is driven through `httpx.MockTransport`.
"""

import datetime as dt

import httpx
import jwt
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import (
    AttendanceSource,
    AttendanceState,
    Lesson,
    LessonAttendance,
    LessonMeetingImport,
    MeetingConnection,
    MeetingParticipant,
    MeetingProvider,
)
from app.security import create_state_token
from app.services import google_meet, zoom
from app.services.google_classroom import decrypt_token
from app.services.meeting_common import (
    AUTH_FAILED,
    LessonMoment,
    MeetingLinkError,
    MeetingProviderError,
    ParticipantRecord,
    ParticipantsResult,
    TokenGrant,
    lesson_moment,
    parse_meeting_link,
    pick_session,
)
from app.workers.jobs import process_one_job
from tests.test_attendance import _lesson, _other_tutor

ZOOM_LINK = "https://us02web.zoom.us/j/81234567890?pwd=SeCrEtPassCode"
MEET_LINK = "https://meet.google.com/abc-defg-hij"
MOMENT = lesson_moment(dt.date(2026, 7, 14), None, None)


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    settings = get_settings()
    for name in (
        "zoom_client_id",
        "zoom_client_secret",
        "google_meet_client_id",
        "google_meet_client_secret",
    ):
        monkeypatch.setattr(settings, name, f"test-{name}")


class FakeProviders:
    def __init__(self) -> None:
        self.participants: list[ParticipantRecord] = []
        self.warning: str | None = None
        self.error: MeetingProviderError | None = None
        self.refresh_error: MeetingProviderError | None = None
        self.rotated_to: str | None = None
        self.fetched: list[tuple[str, str, LessonMoment]] = []
        self.crash: Exception | None = None
        self.revoked: list[tuple[str, str]] = []
        self.revoke_error: Exception | None = None


@pytest.fixture
def fake(monkeypatch) -> FakeProviders:
    f = FakeProviders()

    def install(module, scopes: str):
        async def exchange_code(code: str) -> TokenGrant:
            return TokenGrant("access-1", f"refresh-for-{code}", scopes)

        async def refresh(refresh_token: str) -> TokenGrant:
            if f.refresh_error:
                raise f.refresh_error
            return TokenGrant("access-2", f.rotated_to, scopes)

        async def fetch_account_email(access_token: str) -> str:
            return "host@school.example"

        async def fetch_participants(access_token, ref, moment) -> ParticipantsResult:
            f.fetched.append((access_token, ref, moment))
            if f.crash:
                raise f.crash
            if f.error:
                raise f.error
            return ParticipantsResult(list(f.participants), f.warning)

        monkeypatch.setattr(module, "exchange_code", exchange_code)
        monkeypatch.setattr(module, "refresh", refresh)
        monkeypatch.setattr(module, "fetch_account_email", fetch_account_email)
        monkeypatch.setattr(module, "fetch_participants", fetch_participants)

        async def revoke(refresh_token: str) -> None:
            f.revoked.append((module.__name__, refresh_token))
            if f.revoke_error:
                raise f.revoke_error

        monkeypatch.setattr(module, "revoke", revoke)

    install(zoom, "meeting:read user:read")
    install(google_meet, f"{google_meet.MEET_SCOPE} {google_meet.DIRECTORY_SCOPE}")
    return f


async def _connect(client, headers, provider="zoom", code="the-code"):
    url = await client.get(f"/api/v1/integrations/{provider}/authorize-url", headers=headers)
    assert url.status_code == 200, url.text
    resp = await client.get(
        f"/api/v1/integrations/{provider}/callback",
        params={"code": code, "state": url.json()["state"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _online(client, tutor, group, link=ZOOM_LINK):
    return await _lesson(client, tutor, group, mode="online", meeting_link=link)


async def _add_student(client, tutor, group, name, email):
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": name,
            "email": email,
            "password": "password123",
        },
    )
    assert reg.status_code == 201, reg.text
    return reg.json()["user"]["id"]


async def _import(client, tutor, lesson):
    resp = await client.post(
        f"/api/v1/lessons/{lesson['id']}/attendance/import", headers=tutor["headers"]
    )
    assert resp.status_code == 202, resp.text
    assert await process_one_job() is True
    meeting = await client.get(f"/api/v1/lessons/{lesson['id']}/meeting", headers=tutor["headers"])
    return meeting.json()


async def _register(client, tutor, lesson):
    resp = await client.get(f"/api/v1/lessons/{lesson['id']}/attendance", headers=tutor["headers"])
    return {r["name"]: (r["state"], r["source"]) for r in resp.json()}


# --- Meeting links -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (ZOOM_LINK, (MeetingProvider.zoom, "81234567890")),
        ("https://zoom.us/j/123456789", (MeetingProvider.zoom, "123456789")),
        ("https://zoom.us/wc/join/123456789", (MeetingProvider.zoom, "123456789")),
        (MEET_LINK, (MeetingProvider.google_meet, "abc-defg-hij")),
        (
            "https://meet.google.com/ABC-DEFG-HIJ?authuser=1",
            (MeetingProvider.google_meet, "abc-defg-hij"),
        ),
    ],
)
def test_links_parse_into_provider_and_ref(link, expected):
    assert parse_meeting_link(link) == expected


@pytest.mark.parametrize(
    "link",
    [
        "",
        "not a link",
        "http://zoom.us/j/123456789",
        "https://evilzoom.us/j/123456789",
        "https://zoom.us.evil.example/j/123456789",
        "https://zoom.us/my/someroom",
        "https://meet.google.com/lookup/xyz",
        "https://meet.google.com/new",
        "https://teams.microsoft.com/l/meetup-join/abc",
        "https://example.com/abc-defg-hij",
    ],
)
def test_other_links_are_rejected(link):
    with pytest.raises(MeetingLinkError):
        parse_meeting_link(link)


async def test_lesson_link_round_trip_drops_the_passcode(client, tutor, group):
    lesson = await _online(client, tutor, group)
    assert lesson["meeting_provider"] == "zoom"
    assert lesson["meeting_link"] == "https://zoom.us/j/81234567890"
    async with async_session() as s:
        row = await s.get(Lesson, lesson["id"])
        assert (row.meeting_provider, row.meeting_ref) == (MeetingProvider.zoom, "81234567890")
    got = await client.get(f"/api/v1/lessons/{lesson['id']}", headers=tutor["headers"])
    assert got.json()["meeting_link"] == "https://zoom.us/j/81234567890"

    swapped = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"meeting_link": MEET_LINK},
        headers=tutor["headers"],
    )
    assert (swapped.json()["meeting_provider"], swapped.json()["meeting_link"]) == (
        "google_meet",
        MEET_LINK,
    )
    untouched = await client.patch(
        f"/api/v1/lessons/{lesson['id']}", json={"notes": "x"}, headers=tutor["headers"]
    )
    assert untouched.json()["meeting_link"] == MEET_LINK
    cleared = await client.patch(
        f"/api/v1/lessons/{lesson['id']}", json={"meeting_link": None}, headers=tutor["headers"]
    )
    assert (cleared.json()["meeting_provider"], cleared.json()["meeting_link"]) == (None, None)


async def test_a_bad_link_or_an_in_person_lesson_is_a_422(client, tutor, group):
    body = {"group_id": group["id"], "date": "2026-07-14"}
    bad = await client.post(
        "/api/v1/lessons",
        json={**body, "mode": "online", "meeting_link": "https://example.com/x"},
        headers=tutor["headers"],
    )
    assert bad.status_code == 422
    in_person = await client.post(
        "/api/v1/lessons", json={**body, "meeting_link": MEET_LINK}, headers=tutor["headers"]
    )
    assert in_person.status_code == 422
    lesson = await _lesson(client, tutor, group)
    patched = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"meeting_link": MEET_LINK},
        headers=tutor["headers"],
    )
    assert patched.status_code == 422
    async with async_session() as s:
        assert (await s.scalars(select(Lesson).where(Lesson.meeting_ref.is_not(None)))).all() == []


# --- Connecting --------------------------------------------------------------------


async def test_status_says_not_configured_and_never_errors(client, tutor, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "zoom_client_id", None)
    monkeypatch.setattr(settings, "google_meet_client_secret", None)
    resp = await client.get("/api/v1/integrations", headers=tutor["headers"])
    assert resp.status_code == 200
    by = {r["provider"]: r for r in resp.json()}
    assert by["zoom"]["configured"] is False and by["zoom"]["connected"] is False
    assert by["google_meet"]["configured"] is False
    assert "paid Google Workspace account" in by["google_meet"]["note"]
    assert "free Google account returns no attendance" in by["google_meet"]["note"]
    for provider in ("zoom", "google_meet"):
        url = await client.get(
            f"/api/v1/integrations/{provider}/authorize-url", headers=tutor["headers"]
        )
        assert url.status_code == 503
        assert "isn't set up" in url.json()["detail"]


async def test_connect_stores_an_encrypted_token_and_disconnect_removes_it(client, tutor, fake):
    status = await _connect(client, tutor["headers"], "zoom", code="abc")
    assert (status["connected"], status["account_email"]) == (True, "host@school.example")
    async with async_session() as s:
        conn = (await s.scalars(select(MeetingConnection))).one()
        assert conn.provider == MeetingProvider.zoom and conn.tutor_id == tutor["user"]["id"]
        assert "refresh-for-abc" not in conn.encrypted_refresh_token
        assert decrypt_token(conn.encrypted_refresh_token) == "refresh-for-abc"
    listed = await client.get("/api/v1/integrations", headers=tutor["headers"])
    assert {r["provider"]: r["connected"] for r in listed.json()} == {
        "zoom": True,
        "google_meet": False,
    }
    gone = await client.delete("/api/v1/integrations/zoom", headers=tutor["headers"])
    assert gone.status_code == 204
    again = await client.delete("/api/v1/integrations/zoom", headers=tutor["headers"])
    assert again.status_code == 404
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_reconnecting_replaces_rather_than_duplicates(client, tutor, fake):
    await _connect(client, tutor["headers"], "google_meet", code="one")
    await _connect(client, tutor["headers"], "google_meet", code="two")
    async with async_session() as s:
        conn = (await s.scalars(select(MeetingConnection))).one()
        assert decrypt_token(conn.encrypted_refresh_token) == "refresh-for-two"


async def test_callback_refuses_state_that_this_tutor_did_not_start(client, tutor, fake):
    other_headers, other_user = await _other_tutor(client, "other@example.com")
    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": str(tutor["user"]["id"]),
            "type": "oauth_state",
            "purpose": "meeting_zoom",
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    others = create_state_token(other_user["id"], "meeting_zoom")
    wrong_provider = create_state_token(tutor["user"]["id"], "meeting_google_meet")
    wrong_type = jwt.encode(
        {"sub": str(tutor["user"]["id"]), "type": "access", "purpose": "meeting_zoom"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    for state in ("forged", expired, others, wrong_provider, wrong_type):
        resp = await client.get(
            "/api/v1/integrations/zoom/callback",
            params={"code": "x", "state": state},
            headers=tutor["headers"],
        )
        assert resp.status_code == 400, state
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_callback_when_unconfigured_is_a_503_not_a_crash(client, tutor, fake, monkeypatch):
    state = create_state_token(tutor["user"]["id"], "meeting_zoom")
    # The real exchange, not the fake: it is what reads the (now absent) settings.
    monkeypatch.undo()
    settings = get_settings()
    monkeypatch.setattr(settings, "zoom_client_id", None)
    resp = await client.get(
        "/api/v1/integrations/zoom/callback",
        params={"code": "x", "state": state},
        headers=tutor["headers"],
    )
    assert resp.status_code == 503


async def test_google_connection_without_the_meet_permission_is_refused(
    client, tutor, fake, monkeypatch
):
    async def exchange_code(code):
        return TokenGrant("a", "r", "https://www.googleapis.com/auth/userinfo.email")

    monkeypatch.setattr(google_meet, "exchange_code", exchange_code)
    url = await client.get(
        "/api/v1/integrations/google_meet/authorize-url", headers=tutor["headers"]
    )
    resp = await client.get(
        "/api/v1/integrations/google_meet/callback",
        params={"code": "x", "state": url.json()["state"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 400
    assert "permission" in resp.json()["detail"]
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_google_connection_without_the_directory_permission_is_refused(
    client, tutor, fake, monkeypatch
):
    async def exchange_code(code):
        return TokenGrant("a", "r", google_meet.MEET_SCOPE)

    monkeypatch.setattr(google_meet, "exchange_code", exchange_code)
    url = await client.get(
        "/api/v1/integrations/google_meet/authorize-url", headers=tutor["headers"]
    )
    resp = await client.get(
        "/api/v1/integrations/google_meet/callback",
        params={"code": "x", "state": url.json()["state"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 400
    assert "directory permission" in resp.json()["detail"]
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_the_google_note_says_why_the_directory_is_read(client, tutor):
    listed = await client.get("/api/v1/integrations", headers=tutor["headers"])
    google = next(r for r in listed.json() if r["provider"] == "google_meet")
    assert "directory names and emails only to match meeting participants" in google["note"]


async def test_authorize_url_carries_the_state_and_client(client, tutor):
    resp = await client.get("/api/v1/integrations/zoom/authorize-url", headers=tutor["headers"])
    body = resp.json()
    assert body["url"].startswith("https://zoom.us/oauth/authorize?")
    assert "client_id=test-zoom_client_id" in body["url"]
    assert body["state"] in body["url"]


async def test_integration_routes_are_tutor_only(client, tutor, student):
    for method, path in (
        ("GET", "/api/v1/integrations"),
        ("GET", "/api/v1/integrations/zoom/authorize-url"),
        ("GET", "/api/v1/integrations/zoom/callback?code=x&state=y"),
        ("DELETE", "/api/v1/integrations/zoom"),
        ("GET", "/api/v1/lessons/1/meeting"),
        ("POST", "/api/v1/lessons/1/attendance/import"),
        ("POST", "/api/v1/lessons/1/participants/1/resolve"),
    ):
        as_student = await client.request(method, path, headers=student["headers"])
        assert as_student.status_code == 403, (method, path)
        anonymous = await client.request(method, path)
        assert anonymous.status_code == 401, (method, path)


async def test_one_tutors_connection_is_invisible_to_another(client, tutor, fake):
    await _connect(client, tutor["headers"], "zoom")
    other_headers, _ = await _other_tutor(client, "other@example.com")
    listed = await client.get("/api/v1/integrations", headers=other_headers)
    assert all(r["connected"] is False for r in listed.json())
    assert (
        await client.delete("/api/v1/integrations/zoom", headers=other_headers)
    ).status_code == 404
    async with async_session() as s:
        assert len((await s.scalars(select(MeetingConnection))).all()) == 1


# --- Importing ---------------------------------------------------------------------


async def test_import_needs_a_link_a_configured_provider_and_a_connection(
    client, tutor, group, fake, monkeypatch
):
    url = "/api/v1/lessons/{}/attendance/import"
    in_person = await _lesson(client, tutor, group)
    no_link = await client.post(url.format(in_person["id"]), headers=tutor["headers"])
    assert no_link.status_code == 409 and "link" in no_link.json()["detail"]

    lesson = await _online(client, tutor, group)
    not_connected = await client.post(url.format(lesson["id"]), headers=tutor["headers"])
    assert not_connected.status_code == 409
    assert "Connect Zoom" in not_connected.json()["detail"]

    monkeypatch.setattr(get_settings(), "zoom_client_id", None)
    unconfigured = await client.post(url.format(lesson["id"]), headers=tutor["headers"])
    assert unconfigured.status_code == 409
    assert "isn't set up" in unconfigured.json()["detail"]
    async with async_session() as s:
        assert (await s.scalars(select(LessonMeetingImport))).all() == []


async def test_matches_by_verified_email_and_withholds_absence_while_anyone_is_unidentified(
    client, tutor, group, student, fake
):
    sara = student["user"]["id"]  # sara@example.com
    await _add_student(client, tutor, group, "Omar", "omar@example.com")
    await _add_student(client, tutor, group, "Lina", "lina@example.com")
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [
        ParticipantRecord("Teacher", "host@school.example", 3000, verified=True),
        ParticipantRecord("sara (phone)", "  SARA@Example.com ", 2400, verified=True),
        # Same first name as Lina, no email: must NOT be matched to her.
        ParticipantRecord("Lina", None, 1800),
        ParticipantRecord("Mr Guest", "guest@elsewhere.example", 600, verified=True),
    ]
    meeting = await _import(client, tutor, lesson)

    message = meeting["last_import"]["message"]
    assert meeting["last_import"]["status"] == "succeeded"
    assert message.startswith("1 present.")
    assert "absent" not in message.replace("nobody was marked absent", "")
    assert (
        "2 participants couldn't be identified — match them or mark the register; "
        "nobody was marked absent." in message
    )
    by_name = {p["display_name"]: p for p in meeting["participants"]}
    assert "Teacher" not in by_name  # the host is neither matched nor asked about
    assert by_name["sara (phone)"]["matched_student_id"] == sara
    assert by_name["Lina"]["matched_student_id"] is None
    assert by_name["Mr Guest"]["matched_student_id"] is None
    assert by_name["Lina"]["email"] is None and by_name["Lina"]["resolved"] is False
    # Present for who was identified; nobody invented as absent (PROD-2).
    assert await _register(client, tutor, lesson) == {
        "Sara": ("present", "google_meet"),
        "Omar": (None, None),
        "Lina": (None, None),
    }
    async with async_session() as s:
        rows = (await s.scalars(select(LessonAttendance))).all()
        assert all(r.recorded_by_id is None for r in rows)
    _, ref, moment = fake.fetched[0]
    assert (ref, moment.local_date) == ("abc-defg-hij", dt.date(2026, 7, 14))


async def test_absence_is_marked_only_when_every_participant_was_identified(
    client, tutor, group, student, fake
):
    await _add_student(client, tutor, group, "Omar", "omar@example.com")
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [
        ParticipantRecord("Teacher", "host@school.example", 3000, verified=True),
        ParticipantRecord("Sara", "sara@example.com", 2400, verified=True),
    ]
    meeting = await _import(client, tutor, lesson)
    assert meeting["last_import"]["message"] == "1 present, 1 absent."
    assert await _register(client, tutor, lesson) == {
        "Sara": ("present", "google_meet"),
        "Omar": ("absent", "google_meet"),
    }


async def test_a_zoom_email_is_only_a_suggestion_the_tutor_confirms(
    client, tutor, group, student, fake
):
    """A Zoom guest types their own email, so anyone can claim a classmate's."""
    sara = student["user"]["id"]
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.participants = [ParticipantRecord("totally not sara", "sara@example.com", 900)]
    meeting = await _import(client, tutor, lesson)
    part = meeting["participants"][0]
    assert (part["matched_student_id"], part["suggested_student_id"]) == (None, sara)
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}
    assert "1 participant couldn't be identified" in meeting["last_import"]["message"]

    confirmed = await client.post(
        f"/api/v1/lessons/{lesson['id']}/participants/{part['id']}/resolve",
        json={"student_id": sara},
        headers=tutor["headers"],
    )
    assert confirmed.status_code == 200
    assert await _register(client, tutor, lesson) == {"Sara": ("present", "tutor")}


async def test_a_tutors_mark_is_never_overwritten_by_an_import(client, tutor, group, student, fake):
    sara = student["user"]["id"]
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    put = await client.put(
        f"/api/v1/lessons/{lesson['id']}/attendance",
        json={"entries": [{"student_id": sara, "state": "absent"}]},
        headers=tutor["headers"],
    )
    assert put.status_code == 200
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 3000, verified=True)]
    meeting = await _import(client, tutor, lesson)
    assert await _register(client, tutor, lesson) == {"Sara": ("absent", "tutor")}
    assert "1 kept as you marked them" in meeting["last_import"]["message"]


async def test_an_empty_answer_writes_nothing_and_says_so(client, tutor, group, student, fake):
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = []
    meeting = await _import(client, tutor, lesson)
    assert meeting["last_import"]["status"] == "failed"
    assert meeting["last_import"]["error_code"] == "no_data"
    assert "paid Google Workspace account" in meeting["last_import"]["message"]
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("forbidden", "wouldn't share"),
        ("not_found", "no finished meeting"),
        ("rate_limited", "later"),
    ],
)
async def test_provider_failures_are_recorded_for_the_tutor(
    client, tutor, group, student, fake, code, text
):
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.error = MeetingProviderError(code, f"Zoom: {text}")
    meeting = await _import(client, tutor, lesson)
    assert meeting["last_import"] == {
        "status": "failed",
        "error_code": code,
        "message": f"Zoom: {text}",
        "finished_at": meeting["last_import"]["finished_at"],
    }
    assert meeting["last_import"]["finished_at"] is not None
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}


async def test_a_refused_token_refresh_is_reported(client, tutor, group, student, fake):
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.refresh_error = MeetingProviderError(
        AUTH_FAILED, "Zoom no longer accepts this connection."
    )
    meeting = await _import(client, tutor, lesson)
    assert meeting["last_import"]["status"] == "failed"
    assert meeting["last_import"]["error_code"] == "auth_failed"
    assert fake.fetched == []


async def test_a_disconnect_before_the_job_runs_is_reported(client, tutor, group, student, fake):
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    queued = await client.post(
        f"/api/v1/lessons/{lesson['id']}/attendance/import", headers=tutor["headers"]
    )
    assert queued.json()["status"] == "queued"
    await client.delete("/api/v1/integrations/zoom", headers=tutor["headers"])
    await process_one_job()
    meeting = (
        await client.get(f"/api/v1/lessons/{lesson['id']}/meeting", headers=tutor["headers"])
    ).json()
    assert meeting["last_import"]["error_code"] == "not_connected"


async def test_zoom_refresh_token_rotation_is_persisted(client, tutor, group, student, fake):
    await _connect(client, tutor["headers"], "zoom", code="first")
    lesson = await _online(client, tutor, group)
    fake.rotated_to = "rotated-refresh"
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60)]
    await _import(client, tutor, lesson)
    async with async_session() as s:
        conn = (await s.scalars(select(MeetingConnection))).one()
        assert decrypt_token(conn.encrypted_refresh_token) == "rotated-refresh"


async def test_a_student_of_another_class_sharing_an_email_is_never_matched(
    client, tutor, group, student, subject, fake
):
    theirs = await client.post(
        "/api/v1/groups",
        json={"name": "Other class", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    assert theirs.status_code == 201, theirs.text
    invite = await client.post(
        f"/api/v1/groups/{theirs.json()['id']}/invites", headers=tutor["headers"]
    )
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Stranger",
            "email": "stranger@example.com",
            "password": "password123",
        },
    )
    assert reg.status_code == 201, reg.text
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.participants = [ParticipantRecord("Stranger", "stranger@example.com", 60)]
    meeting = await _import(client, tutor, lesson)
    assert meeting["participants"][0]["matched_student_id"] is None
    # Stranger could not be identified, so nobody is marked absent.
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}


# --- Resolving ---------------------------------------------------------------------


async def _imported_with_one_unmatched(client, tutor, group, fake):
    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.participants = [ParticipantRecord("S. A.", "other-address@example.com", 1200)]
    meeting = await _import(client, tutor, lesson)
    return lesson, meeting["participants"][0]["id"]


async def test_resolving_marks_present_as_the_tutor_and_survives_a_reimport(
    client, tutor, group, student, fake
):
    sara = student["user"]["id"]
    lesson, pid = await _imported_with_one_unmatched(client, tutor, group, fake)
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}

    resp = await client.post(
        f"/api/v1/lessons/{lesson['id']}/participants/{pid}/resolve",
        json={"student_id": sara},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["matched_student_id"], resp.json()["resolved"]) == (sara, True)
    assert await _register(client, tutor, lesson) == {"Sara": ("present", "tutor")}
    async with async_session() as s:
        att = (await s.scalars(select(LessonAttendance))).one()
        assert (att.state, att.source) == (AttendanceState.present, AttendanceSource.tutor)
        assert att.recorded_by_id == tutor["user"]["id"]

    again = await _import(client, tutor, lesson)
    assert [(p["id"], p["resolved"]) for p in again["participants"]] == [(pid, True)]
    assert await _register(client, tutor, lesson) == {"Sara": ("present", "tutor")}
    async with async_session() as s:
        assert len((await s.scalars(select(MeetingParticipant))).all()) == 1


async def test_a_resolved_student_is_not_marked_absent_after_the_tutor_clears_them(
    client, tutor, group, student, fake
):
    sara = student["user"]["id"]
    lesson, pid = await _imported_with_one_unmatched(client, tutor, group, fake)
    await client.post(
        f"/api/v1/lessons/{lesson['id']}/participants/{pid}/resolve",
        json={"student_id": sara},
        headers=tutor["headers"],
    )
    await client.put(
        f"/api/v1/lessons/{lesson['id']}/attendance",
        json={"entries": [{"student_id": sara, "state": None}]},
        headers=tutor["headers"],
    )
    await _import(client, tutor, lesson)
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}


async def test_resolve_rejects_other_tutors_lessons_unknown_ids_and_unenrolled_students(
    client, tutor, group, student, fake
):
    sara = student["user"]["id"]
    lesson, pid = await _imported_with_one_unmatched(client, tutor, group, fake)
    base = f"/api/v1/lessons/{lesson['id']}/participants"

    other_headers, other_user = await _other_tutor(client, "other@example.com")
    foreign = await client.post(
        f"{base}/{pid}/resolve", json={"student_id": sara}, headers=other_headers
    )
    assert foreign.status_code == 404
    assert (
        await client.get(f"/api/v1/lessons/{lesson['id']}/meeting", headers=other_headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/lessons/{lesson['id']}/attendance/import", headers=other_headers
        )
    ).status_code == 404

    assert (
        await client.post(
            f"{base}/9999/resolve", json={"student_id": sara}, headers=tutor["headers"]
        )
    ).status_code == 404
    # A real user who is not in this class: the tutor themselves, and another org's tutor.
    for outsider in (tutor["user"]["id"], other_user["id"]):
        resp = await client.post(
            f"{base}/{pid}/resolve", json={"student_id": outsider}, headers=tutor["headers"]
        )
        assert resp.status_code == 404
    async with async_session() as s:
        part = (await s.scalars(select(MeetingParticipant))).one()
        assert part.resolved_by_id is None and part.matched_student_id is None
        assert (
            await s.scalars(
                select(LessonAttendance).where(LessonAttendance.state == AttendanceState.present)
            )
        ).all() == []


async def test_changing_the_link_drops_what_was_imported_from_the_old_meeting(
    client, tutor, group, student, fake
):
    lesson, _ = await _imported_with_one_unmatched(client, tutor, group, fake)
    same = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"meeting_link": ZOOM_LINK},
        headers=tutor["headers"],
    )
    assert same.status_code == 200
    async with async_session() as s:
        assert len((await s.scalars(select(MeetingParticipant))).all()) == 1
    await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"meeting_link": MEET_LINK},
        headers=tutor["headers"],
    )
    meeting = await client.get(f"/api/v1/lessons/{lesson['id']}/meeting", headers=tutor["headers"])
    assert meeting.json()["participants"] == [] and meeting.json()["last_import"] is None


async def test_deleting_a_lesson_removes_its_provider_rows(client, tutor, group, student, fake):
    lesson, _ = await _imported_with_one_unmatched(client, tutor, group, fake)
    assert (
        await client.delete(f"/api/v1/lessons/{lesson['id']}", headers=tutor["headers"])
    ).status_code == 204
    async with async_session() as s:
        assert (await s.scalars(select(MeetingParticipant))).all() == []
        assert (await s.scalars(select(LessonMeetingImport))).all() == []


# --- The HTTP layers, against mock transports -----------------------------------------


def _mock(monkeypatch, module, handler):
    monkeypatch.setattr(
        module,
        "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_zoom_participants_are_paged_merged_and_taken_from_the_nearest_instance(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.raw_path.decode().split("?")[0]
        assert request.headers["Authorization"] == "Bearer tok"
        if path.endswith("/instances"):
            return httpx.Response(
                200,
                json={
                    "meetings": [
                        {"uuid": "OLD", "start_time": "2026-07-07T15:00:00Z"},
                        {"uuid": "/new//uuid=", "start_time": "2026-07-14T15:00:00Z"},
                    ]
                },
            )
        if "next_page_token=p2" not in str(request.url):
            return httpx.Response(
                200,
                json={
                    "next_page_token": "p2",
                    "participants": [
                        {"name": "Sara", "user_email": "Sara@Example.com", "duration": 600},
                        {"name": "Guest", "user_email": "", "user_id": "u9", "duration": 30},
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "participants": [
                    {"name": "Sara", "user_email": "sara@example.com", "duration": 300},
                    {"name": "Guest", "user_email": "", "user_id": "u9", "duration": 30},
                ]
            },
        )

    _mock(monkeypatch, zoom, handler)
    result = await zoom.fetch_participants("tok", "81234567890", MOMENT)
    assert [(p.display_name, p.email, p.duration_seconds) for p in result.participants] == [
        ("Sara", "Sara@Example.com", 900),
        ("Guest", None, 60),
    ]
    # A UUID starting with "/" or containing "//" is double-encoded, per Zoom.
    assert "/past_meetings/%252Fnew%252F%252Fuuid%253D/participants" in str(seen[1].url.raw_path)


async def test_zoom_errors_map_to_something_a_tutor_can_act_on(monkeypatch):
    for status, code in (
        (404, "not_found"),
        (403, "forbidden"),
        (401, "auth_failed"),
        (429, "rate_limited"),
        (503, "provider_error"),
    ):
        _mock(monkeypatch, zoom, lambda request, status=status: httpx.Response(status, json={}))
        with pytest.raises(MeetingProviderError) as exc:
            await zoom.fetch_participants("tok", "81234567890", MOMENT)
        assert exc.value.code == code
        assert "tok" not in exc.value.message


async def test_zoom_instance_far_from_the_lesson_date_is_not_used(monkeypatch):
    _mock(
        monkeypatch,
        zoom,
        lambda request: httpx.Response(
            200, json={"meetings": [{"uuid": "X", "start_time": "2026-06-01T10:00:00Z"}]}
        ),
    )
    with pytest.raises(MeetingProviderError) as exc:
        await zoom.fetch_participants("tok", "81234567890", MOMENT)
    assert exc.value.code == "not_found" and "2026-07-14" in exc.value.message


async def test_zoom_token_exchange_and_refusal(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Basic ")
        body = request.content.decode()
        if "bad" in body:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(
            200, json={"access_token": "A", "refresh_token": "R", "scope": "meeting:read"}
        )

    _mock(monkeypatch, zoom, handler)
    grant = await zoom.exchange_code("good")
    assert (grant.access_token, grant.refresh_token) == ("A", "R")
    with pytest.raises(MeetingProviderError) as exc:
        await zoom.refresh("bad")
    assert exc.value.code == AUTH_FAILED


async def test_google_participants_resolve_emails_and_keep_unresolvable_people(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "conferenceRecords?" in url:
            assert 'space.meeting_code = "abc-defg-hij"' in request.url.params["filter"]
            return httpx.Response(
                200,
                json={
                    "conferenceRecords": [
                        {
                            "name": "conferenceRecords/old",
                            "startTime": "2026-07-07T15:00:00.123456789Z",
                            "endTime": "2026-07-07T16:00:00Z",
                        },
                        {
                            "name": "conferenceRecords/new",
                            "startTime": "2026-07-14T15:00:00Z",
                            "endTime": "2026-07-14T16:00:00Z",
                        },
                    ]
                },
            )
        if url.endswith("conferenceRecords/new/participants?pageSize=250"):
            return httpx.Response(
                200,
                json={
                    "participants": [
                        {
                            "signedinUser": {"user": "users/111", "displayName": "Sara"},
                            "earliestStartTime": "2026-07-14T15:00:00Z",
                            "latestEndTime": "2026-07-14T15:50:00Z",
                        },
                        {
                            "signedinUser": {"user": "users/222", "displayName": "Hidden"},
                            "earliestStartTime": "2026-07-14T15:00:00Z",
                        },
                        {"anonymousUser": {"displayName": "Guest"}},
                    ]
                },
            )
        if "people:batchGet" in url:
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {
                            "requestedResourceName": "people/111",
                            "person": {
                                "emailAddresses": [
                                    {"value": "alt@example.com"},
                                    {"value": "sara@example.com", "metadata": {"primary": True}},
                                ]
                            },
                        },
                        {"requestedResourceName": "people/222", "httpStatusCode": 404},
                    ]
                },
            )
        raise AssertionError(url)

    _mock(monkeypatch, google_meet, handler)
    result = await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)
    assert [(p.display_name, p.email, p.duration_seconds) for p in result.participants] == [
        ("Sara", "sara@example.com", 3000),
        ("Hidden", None, 0),
        ("Guest", None, 0),
    ]
    assert result.warning is not None and "2 people" in result.warning


async def test_google_with_no_conference_records_explains_workspace(monkeypatch):
    _mock(monkeypatch, google_meet, lambda request: httpx.Response(200, json={}))
    with pytest.raises(MeetingProviderError) as exc:
        await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)
    assert exc.value.code == "no_data"
    assert "paid Google Workspace account" in exc.value.message


async def test_google_403_explains_workspace(monkeypatch):
    _mock(monkeypatch, google_meet, lambda request: httpx.Response(403, json={}))
    with pytest.raises(MeetingProviderError) as exc:
        await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)
    assert exc.value.code == "forbidden"
    assert "paid Google Workspace account" in exc.value.message


def _utc(day, hour, minute=0):
    return dt.datetime(2026, 7, day, hour, minute, tzinfo=dt.timezone.utc)


def test_an_evening_lesson_west_of_utc_picks_its_own_session_not_the_previous_day():
    # UTC-10, 19:00 on the 14th is 05:00Z on the 15th. The previous evening's class
    # (05:00Z on the 14th) is closer to "noon UTC on the 14th" and was wrongly picked.
    sessions = [(_utc(14, 5), "previous-evening"), (_utc(15, 5), "this-lesson")]
    moment = lesson_moment(dt.date(2026, 7, 14), dt.time(19, 0), "Pacific/Honolulu")
    assert moment.start == _utc(15, 5)
    assert pick_session(sessions, moment) == "this-lesson"
    # With no start time, the local day (10:00Z the 14th to 10:00Z the 15th) decides.
    assert pick_session(
        sessions, lesson_moment(dt.date(2026, 7, 14), None, "Pacific/Honolulu")
    ) == ("this-lesson")


def test_a_morning_lesson_east_of_utc_picks_its_own_session_not_the_next_day():
    # UTC+10, 08:00 on the 14th is 22:00Z on the 13th.
    sessions = [(_utc(13, 22), "this-lesson"), (_utc(14, 22), "next-morning")]
    moment = lesson_moment(dt.date(2026, 7, 14), dt.time(8, 0), "Australia/Brisbane")
    assert moment.start == _utc(13, 22)
    assert pick_session(sessions, moment) == "this-lesson"
    assert pick_session(
        sessions, lesson_moment(dt.date(2026, 7, 14), None, "Australia/Brisbane")
    ) == ("this-lesson")


def test_session_pick_refuses_to_guess_between_two_on_the_same_day():
    moment = lesson_moment(dt.date(2026, 7, 14), None, None)
    with pytest.raises(MeetingProviderError) as exc:
        pick_session([(_utc(14, 9), "a"), (_utc(14, 16), "b")], moment)
    assert "start time" in exc.value.message
    # With the start time known, the nearer one is chosen.
    known = lesson_moment(dt.date(2026, 7, 14), dt.time(16, 10), None)
    assert pick_session([(_utc(14, 9), "a"), (_utc(14, 16), "b")], known) == "b"
    assert pick_session([(_utc(14, 9), "a")], known) is None
    assert pick_session([], known) is None


async def test_the_import_asks_for_the_session_in_the_organizations_timezone(
    client, tutor, group, student, fake
):
    from app.models import Organization, User

    async with async_session() as s:
        owner = await s.get(User, tutor["user"]["id"])
        org = await s.get(Organization, owner.organization_id)
        org.timezone = "Pacific/Honolulu"
        await s.commit()
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _lesson(
        client, tutor, group, mode="online", meeting_link=MEET_LINK, start_time="19:00:00"
    )
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    await _import(client, tutor, lesson)
    assert fake.fetched[0][2].start == _utc(15, 5)


async def test_the_import_reads_the_lesson_on_its_classs_clock_tutor_override_first(
    client, tutor, group, student, fake
):
    from app.models import Organization, User

    async with async_session() as s:
        owner = await s.get(User, tutor["user"]["id"])
        owner.time_zone = "Europe/London"
        org = await s.get(Organization, owner.organization_id)
        org.timezone = "Asia/Dubai"
        await s.commit()
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _lesson(
        client,
        tutor,
        group,
        mode="online",
        meeting_link=MEET_LINK,
        start_time="18:00:00",
        date="2026-07-14",
    )
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    await _import(client, tutor, lesson)
    # 18:00 London (BST) is 17:00 UTC; the org's Dubai clock would give 14:00.
    assert fake.fetched[0][2].start == _utc(14, 17)


# --- Failure handling ---------------------------------------------------------------------------


async def test_an_unexpected_error_marks_the_import_failed_and_still_fails_the_job(
    client, tutor, group, student, fake
):
    from app.models import Job, JobStatus

    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    fake.crash = KeyError("secret-looking-field")
    meeting = await _import(client, tutor, lesson)
    imp = meeting["last_import"]
    assert imp["status"] == "failed" and imp["error_code"] == "provider_error"
    assert "Something went wrong" in imp["message"] and "secret-looking-field" not in imp["message"]
    async with async_session() as s:
        job = (await s.scalars(select(Job))).one()
        assert job.status == JobStatus.pending and job.error  # re-raised: the job failed, retries
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}


async def test_a_lost_race_on_the_register_is_a_failed_import_not_a_stuck_one(
    client, tutor, group, student, fake, monkeypatch
):
    from app.services import attendance

    async def conflict(*args, **kwargs):
        raise attendance.AttendanceConflict

    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    monkeypatch.setattr(attendance, "set_attendance", conflict)
    meeting = await _import(client, tutor, lesson)
    assert meeting["last_import"]["status"] == "failed"
    async with async_session() as s:
        assert (await s.scalars(select(MeetingParticipant))).all() == []  # rolled back


async def test_an_import_already_queued_is_not_queued_twice(client, tutor, group, student, fake):
    from app.models import Job

    await _connect(client, tutor["headers"], "zoom")
    lesson = await _online(client, tutor, group)
    url = f"/api/v1/lessons/{lesson['id']}/attendance/import"
    first = await client.post(url, headers=tutor["headers"])
    second = await client.post(url, headers=tutor["headers"])
    assert (first.status_code, second.status_code) == (202, 202)
    assert second.json()["status"] == "queued"
    async with async_session() as s:
        assert len((await s.scalars(select(Job))).all()) == 1
        row = (await s.scalars(select(LessonMeetingImport))).one()
        row.requested_at = row.requested_at - dt.timedelta(hours=1)  # a lost job
        await s.commit()
    await client.post(url, headers=tutor["headers"])
    async with async_session() as s:
        assert len((await s.scalars(select(Job))).all()) == 2


# --- Disconnect revokes at the provider ---------------------------------------------------------


async def test_disconnect_revokes_at_the_provider_then_deletes(client, tutor, fake):
    await _connect(client, tutor["headers"], "zoom", code="abc")
    gone = await client.delete("/api/v1/integrations/zoom", headers=tutor["headers"])
    assert gone.status_code == 204
    assert fake.revoked == [("app.services.zoom", "refresh-for-abc")]
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_a_failed_revoke_is_logged_and_the_connection_is_deleted_anyway(
    client, tutor, fake, caplog
):
    await _connect(client, tutor["headers"], "google_meet", code="tok123")
    fake.revoke_error = RuntimeError("provider down")
    with caplog.at_level("WARNING"):
        gone = await client.delete("/api/v1/integrations/google_meet", headers=tutor["headers"])
    assert gone.status_code == 204
    assert "could not revoke" in caplog.text and "tok123" not in caplog.text
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


async def test_the_revoke_calls_hit_each_providers_endpoint(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (str(request.url), request.content.decode(), request.headers.get("Authorization"))
        )
        return httpx.Response(200, json={})

    _mock(monkeypatch, zoom, handler)
    _mock(monkeypatch, google_meet, handler)
    await zoom.revoke("zr")
    await google_meet.revoke("gr")
    assert seen[0][0] == "https://zoom.us/oauth/revoke" and seen[0][1] == "token=zr"
    assert seen[0][2].startswith("Basic ")
    assert seen[1][0] == "https://oauth2.googleapis.com/revoke" and seen[1][1] == "token=gr"


# --- Provider answers that are not what we expect ----------------------------------------------


async def test_malformed_provider_answers_are_a_clear_error(monkeypatch):
    _mock(monkeypatch, zoom, lambda request: httpx.Response(200, content=b"<html>oops</html>"))
    with pytest.raises(MeetingProviderError) as exc:
        await zoom.fetch_participants("tok", "81234567890", MOMENT)
    assert exc.value.code == "provider_error" and "couldn't read" in exc.value.message

    def bad_row(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/instances"):
            return httpx.Response(
                200, json={"meetings": [{"uuid": "U", "start_time": "2026-07-14T15:00:00Z"}]}
            )
        return httpx.Response(200, json={"participants": [{"name": "A", "duration": "abc"}]})

    _mock(monkeypatch, zoom, bad_row)
    with pytest.raises(MeetingProviderError) as exc:
        await zoom.fetch_participants("tok", "81234567890", MOMENT)
    assert "couldn't read" in exc.value.message

    _mock(monkeypatch, google_meet, lambda request: httpx.Response(200, json=[1, 2]))
    with pytest.raises(MeetingProviderError):
        await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)

    _mock(monkeypatch, zoom, lambda request: httpx.Response(200, json={"refresh_token": "r"}))
    with pytest.raises(MeetingProviderError):
        await zoom.refresh("old")


def _people_handler(people_status: int, items: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "conferenceRecords?" in url:
            return httpx.Response(
                200,
                json={
                    "conferenceRecords": [
                        {
                            "name": "conferenceRecords/c",
                            "startTime": "2026-07-14T15:00:00Z",
                            "endTime": "2026-07-14T16:00:00Z",
                        }
                    ]
                },
            )
        if "people:batchGet" in url:
            return httpx.Response(people_status, json={"responses": items or []})
        return httpx.Response(
            200, json={"participants": [{"signedinUser": {"user": "users/1", "displayName": "S"}}]}
        )

    return handler


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "auth_failed"), (403, "forbidden"), (429, "rate_limited"), (503, "provider_error")],
)
async def test_a_failed_people_lookup_is_an_error_never_no_email(monkeypatch, status, code):
    _mock(monkeypatch, google_meet, _people_handler(status))
    with pytest.raises(MeetingProviderError) as exc:
        await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)
    assert exc.value.code == code


async def test_a_person_the_directory_does_not_know_is_just_without_an_email(monkeypatch):
    _mock(
        monkeypatch,
        google_meet,
        _people_handler(200, [{"requestedResourceName": "people/1", "httpStatusCode": 404}]),
    )
    result = await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)
    assert result.participants[0].email is None and result.participants[0].verified is False
    assert result.warning is not None and "didn't share an email" in result.warning
    # A per-person error that is not "not found" is a failed lookup, not absence.
    _mock(
        monkeypatch,
        google_meet,
        _people_handler(200, [{"requestedResourceName": "people/1", "httpStatusCode": 500}]),
    )
    with pytest.raises(MeetingProviderError):
        await google_meet.fetch_participants("tok", "abc-defg-hij", MOMENT)


async def test_a_google_grant_with_no_scope_at_all_is_refused(client, tutor, fake, monkeypatch):
    for scopes in ("", google_meet.DIRECTORY_SCOPE):

        async def exchange_code(code, scopes=scopes):
            return TokenGrant("a", "r", scopes)

        monkeypatch.setattr(google_meet, "exchange_code", exchange_code)
        url = await client.get(
            "/api/v1/integrations/google_meet/authorize-url", headers=tutor["headers"]
        )
        resp = await client.get(
            "/api/v1/integrations/google_meet/callback",
            params={"code": "x", "state": url.json()["state"]},
            headers=tutor["headers"],
        )
        assert resp.status_code == 400, scopes
    async with async_session() as s:
        assert (await s.scalars(select(MeetingConnection))).all() == []


def test_two_equally_near_sessions_are_ambiguous_not_first_wins():
    moment = lesson_moment(dt.date(2026, 7, 14), dt.time(12, 0), None)
    sessions = [(_utc(14, 11), "earlier"), (_utc(14, 13), "later")]
    with pytest.raises(MeetingProviderError) as exc:
        pick_session(sessions, moment)
    assert "start time" in exc.value.message
    # Either order: it never silently takes the first.
    with pytest.raises(MeetingProviderError):
        pick_session(list(reversed(sessions)), moment)
    # A strictly nearer one still wins.
    assert pick_session([*sessions, (_utc(14, 12, 5), "near")], moment) == "near"


async def test_zoom_instances_are_read_across_pages(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]
        if path.endswith("/instances"):
            seen.append(request.url.params.get("next_page_token"))
            if request.url.params.get("next_page_token") != "p2":
                return httpx.Response(
                    200,
                    json={
                        "next_page_token": "p2",
                        "meetings": [{"uuid": "OLD", "start_time": "2026-06-01T15:00:00Z"}],
                    },
                )
            return httpx.Response(
                200, json={"meetings": [{"uuid": "RIGHT", "start_time": "2026-07-14T15:00:00Z"}]}
            )
        assert "/past_meetings/RIGHT/participants" in path
        return httpx.Response(200, json={"participants": [{"name": "A", "duration": 5}]})

    _mock(monkeypatch, zoom, handler)
    result = await zoom.fetch_participants("tok", "81234567890", MOMENT)
    assert seen == [None, "p2"] and result.participants[0].display_name == "A"


async def test_a_superseded_worker_writes_nothing(client, tutor, group, student, fake):
    """A stale re-queue starts attempt 2; attempt 1's worker must not touch the register."""
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    url = f"/api/v1/lessons/{lesson['id']}/attendance/import"
    await client.post(url, headers=tutor["headers"])  # attempt 1, job 1
    async with async_session() as s:
        row = (await s.scalars(select(LessonMeetingImport))).one()
        row.requested_at = row.requested_at - dt.timedelta(hours=1)  # presumed lost
        await s.commit()
    await client.post(url, headers=tutor["headers"])  # attempt 2, job 2

    assert await process_one_job() is True  # job 1: no longer current
    assert fake.fetched == []
    assert await _register(client, tutor, lesson) == {"Sara": (None, None)}
    async with async_session() as s:
        row = (await s.scalars(select(LessonMeetingImport))).one()
        assert (row.attempt, row.status.value) == (2, "queued")

    assert await process_one_job() is True  # job 2 does the work
    assert await _register(client, tutor, lesson) == {"Sara": ("present", "google_meet")}


async def test_a_resolved_participant_cannot_be_resolved_again(client, tutor, group, student, fake):
    sara = student["user"]["id"]
    omar = await _add_student(client, tutor, group, "Omar", "omar@example.com")
    lesson, pid = await _imported_with_one_unmatched(client, tutor, group, fake)
    url = f"/api/v1/lessons/{lesson['id']}/participants/{pid}/resolve"
    first = await client.post(url, json={"student_id": sara}, headers=tutor["headers"])
    second = await client.post(url, json={"student_id": omar}, headers=tutor["headers"])
    assert (first.status_code, second.status_code) == (200, 409)
    assert await _register(client, tutor, lesson) == {
        "Sara": ("present", "tutor"),
        "Omar": (None, None),
    }
    async with async_session() as s:
        part = (await s.scalars(select(MeetingParticipant))).one()
        assert part.matched_student_id == sara


async def test_switching_a_lesson_to_in_person_drops_the_meeting_but_not_tutor_marks(
    client, tutor, group, student, fake
):
    omar = await _add_student(client, tutor, group, "Omar", "omar@example.com")
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    await _import(client, tutor, lesson)
    await client.put(
        f"/api/v1/lessons/{lesson['id']}/attendance",
        json={"entries": [{"student_id": omar, "state": "present"}]},
        headers=tutor["headers"],
    )
    patched = await client.patch(
        f"/api/v1/lessons/{lesson['id']}", json={"mode": "in_person"}, headers=tutor["headers"]
    )
    assert patched.status_code == 200
    assert (patched.json()["meeting_provider"], patched.json()["meeting_link"]) == (None, None)
    assert await _register(client, tutor, lesson) == {
        "Sara": (None, None),
        "Omar": ("present", "tutor"),
    }
    async with async_session() as s:
        assert (await s.scalars(select(MeetingParticipant))).all() == []
        assert (await s.scalars(select(LessonMeetingImport))).all() == []


# --- Changing the link ---------------------------------------------------------------------------


async def test_changing_the_link_removes_integration_marks_but_never_the_tutors(
    client, tutor, group, student, fake
):
    omar = await _add_student(client, tutor, group, "Omar", "omar@example.com")
    await _connect(client, tutor["headers"], "google_meet")
    lesson = await _online(client, tutor, group, link=MEET_LINK)
    fake.participants = [ParticipantRecord("Sara", "sara@example.com", 60, verified=True)]
    await _import(client, tutor, lesson)  # Sara present, Omar absent: both from Meet
    await client.put(
        f"/api/v1/lessons/{lesson['id']}/attendance",
        json={"entries": [{"student_id": omar, "state": "present"}]},
        headers=tutor["headers"],
    )
    await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"meeting_link": "https://meet.google.com/xyz-abcd-efg"},
        headers=tutor["headers"],
    )
    assert await _register(client, tutor, lesson) == {
        "Sara": (None, None),
        "Omar": ("present", "tutor"),
    }
