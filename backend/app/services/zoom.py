"""Zoom: user-level OAuth 2.0 and the past-meeting participant report (7.3, AV-118).

Every Zoom call is a small function here so the flow is testable against a mock
transport with no real credentials (`QA-8`). Built against Zoom's documented
shapes; the owner registers the Zoom app later, so none of this has run against
the real service yet — see the setup notes.

Zoom ROTATES the refresh token on every refresh: the old one stops working. The
caller must persist `TokenGrant.refresh_token` each time (see
`meeting_integrations.access_token_for`).
"""

from datetime import datetime
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings
from app.models import MeetingProvider
from app.services.meeting_common import (
    AUTH_FAILED,
    FORBIDDEN,
    NOT_CONFIGURED,
    NOT_FOUND,
    PROVIDER_ERROR,
    LessonMoment,
    MeetingProviderError,
    ParticipantRecord,
    ParticipantsResult,
    TokenGrant,
    http_client,
    parse_timestamp,
    pick_session,
    raise_for_provider_status,
    readable,
)

AUTH_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"
REVOKE_URL = "https://zoom.us/oauth/revoke"
API_BASE = "https://api.zoom.us/v2"

# Read-only: Avora never starts, edits or ends a meeting. Zoom takes the scopes
# from the app's registration, not from the authorize request, so none are sent
# (see the setup notes for the ones to tick: user:read and meeting:read, or their
# granular equivalents).

_PAGE_SIZE = 300
_MAX_PAGES = 20


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.zoom_client_id and settings.zoom_client_secret)


def _config() -> tuple[str, str, str]:
    settings = get_settings()
    if not settings.zoom_client_id or not settings.zoom_client_secret:
        raise MeetingProviderError(
            NOT_CONFIGURED,
            "Zoom attendance isn't set up for Avora yet. It will appear here once it is.",
        )
    return settings.zoom_client_id, settings.zoom_client_secret, settings.zoom_redirect_uri


def build_auth_url(state: str) -> str:
    client_id, _, redirect_uri = _config()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


async def _token_request(data: dict[str, str]) -> TokenGrant:
    client_id, client_secret, _ = _config()
    async with http_client() as http:
        try:
            resp = await http.post(TOKEN_URL, data=data, auth=(client_id, client_secret))
        except httpx.HTTPError as exc:
            raise MeetingProviderError(
                PROVIDER_ERROR, "Couldn't reach Zoom. Try again shortly."
            ) from exc
    if resp.status_code in (400, 401):
        # invalid_grant: revoked, expired, or the code was already used.
        raise MeetingProviderError(
            AUTH_FAILED, "Zoom no longer accepts this connection. Disconnect and connect again."
        )
    raise_for_provider_status(resp, MeetingProvider.zoom)
    with readable(MeetingProvider.zoom):
        body = resp.json()
        return TokenGrant(
            access_token=str(body["access_token"]),
            refresh_token=body.get("refresh_token"),
            scopes=str(body.get("scope", "")),
        )


async def revoke(refresh_token: str) -> None:
    """Best-effort revoke at Zoom when a tutor disconnects. Raises on failure; the
    caller logs it and deletes the connection regardless."""
    client_id, client_secret, _ = _config()
    async with http_client() as http:
        resp = await http.post(
            REVOKE_URL, data={"token": refresh_token}, auth=(client_id, client_secret)
        )
    resp.raise_for_status()


async def exchange_code(code: str) -> TokenGrant:
    _, _, redirect_uri = _config()
    return await _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    )


async def refresh(refresh_token: str) -> TokenGrant:
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


async def fetch_account_email(access_token: str) -> str | None:
    async with http_client() as http:
        try:
            resp = await http.get(
                f"{API_BASE}/users/me", headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as exc:
            raise MeetingProviderError(
                PROVIDER_ERROR, "Couldn't reach Zoom. Try again shortly."
            ) from exc
    raise_for_provider_status(resp, MeetingProvider.zoom)
    with readable(MeetingProvider.zoom):
        email = resp.json().get("email")
        return email if isinstance(email, str) and email else None


def _uuid_path(uuid: str) -> str:
    # Zoom: a UUID that begins with "/" or contains "//" must be double-encoded.
    once = quote(uuid, safe="")
    return quote(once, safe="") if uuid.startswith("/") or "//" in uuid else once


async def _get(http: httpx.AsyncClient, access_token: str, path: str, params: dict) -> dict:
    try:
        resp = await http.get(
            f"{API_BASE}{path}", headers={"Authorization": f"Bearer {access_token}"}, params=params
        )
    except httpx.HTTPError as exc:
        raise MeetingProviderError(
            PROVIDER_ERROR, "Couldn't reach Zoom. Try again shortly."
        ) from exc
    if resp.status_code == 404:
        raise MeetingProviderError(
            NOT_FOUND,
            "Zoom has no finished meeting with that ID on your account. The meeting must have "
            "ended, and it must have been hosted by the Zoom account you connected.",
        )
    if resp.status_code == 403:
        raise MeetingProviderError(
            FORBIDDEN,
            "Zoom wouldn't share this meeting's participants. Participant reports need a paid "
            "Zoom plan, and Avora needs the meeting permission when you connect.",
        )
    raise_for_provider_status(resp, MeetingProvider.zoom)
    with readable(MeetingProvider.zoom):
        body = resp.json()
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body


async def _instance_uuid(
    http: httpx.AsyncClient, access_token: str, meeting_id: str, moment: LessonMoment
) -> str:
    """A meeting ID is reused by every occurrence; the report is per instance."""
    found: list[tuple[datetime, str]] = []
    token = ""
    for _ in range(_MAX_PAGES):
        params: dict[str, str | int] = {"page_size": _PAGE_SIZE}
        if token:
            params["next_page_token"] = token
        body = await _get(http, access_token, f"/past_meetings/{meeting_id}/instances", params)
        with readable(MeetingProvider.zoom):
            found.extend(
                (parse_timestamp(m["start_time"]), str(m["uuid"]))
                for m in body.get("meetings", [])
                if m.get("uuid") and m.get("start_time")
            )
            token = body.get("next_page_token") or ""
        if not token:
            break
    uuid = pick_session(found, moment)
    if uuid is None:
        raise MeetingProviderError(
            NOT_FOUND,
            f"Zoom has no meeting with that ID on {moment.local_date.isoformat()}. Check the "
            "link on this lesson and the lesson's date and start time.",
        )
    return uuid


async def fetch_participants(
    access_token: str, meeting_id: str, moment: LessonMoment
) -> ParticipantsResult:
    """Everyone Zoom lists for the instance of `meeting_id` that this lesson was.
    A person who left and rejoined is several rows in Zoom's report; they are
    folded into one, durations summed. Participants without an email are kept —
    they are what the tutor resolves by hand.

    No email here is `verified`: Zoom's report has no field saying the participant
    signed in (its `user_id` is a per-meeting join id, `internal_user` only covers
    the host's own account), and a guest types their own email, so any joiner can
    claim a classmate's. Every Zoom email match is a suggestion the tutor confirms."""
    merged: dict[str, ParticipantRecord] = {}
    async with http_client() as http:
        uuid = await _instance_uuid(http, access_token, meeting_id, moment)
        token = ""
        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"page_size": _PAGE_SIZE}
            if token:
                params["next_page_token"] = token
            body = await _get(
                http, access_token, f"/past_meetings/{_uuid_path(uuid)}/participants", params
            )
            with readable(MeetingProvider.zoom):
                for row in body.get("participants", []):
                    name = str(row.get("name") or "").strip() or "Unknown participant"
                    email = str(row.get("user_email") or "").strip() or None
                    seconds = int(row.get("duration") or 0)
                    key = email.lower() if email else f"name:{row.get('user_id') or name.lower()}"
                    prior = merged.get(key)
                    if prior is None:
                        merged[key] = ParticipantRecord(name, email, seconds)
                    else:
                        merged[key] = ParticipantRecord(
                            prior.display_name, prior.email, prior.duration_seconds + seconds
                        )
                token = body.get("next_page_token") or ""
            if not token:
                break
    return ParticipantsResult(list(merged.values()))
