"""Google Meet: OAuth and the Meet REST API v2 attendance records (7.3, AV-118).

Meet attendance (`conferenceRecords` and `participants`) only exists for
meetings held under a paid Google Workspace edition; a free Google account
returns nothing. The connect screen says so up front and an empty answer is
reported as that, not as "nobody came" (`PROD-2`).

The owner registers the Google app later; this is built against Google's
documented shapes and has not yet run against the real service.
"""

from urllib.parse import urlencode

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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
MEET_API = "https://meet.googleapis.com/v2"
PEOPLE_API = "https://people.googleapis.com/v1"

#: Without this one nothing can be read, so a connection that lacks it is refused.
MEET_SCOPE = "https://www.googleapis.com/auth/meetings.space.readonly"
#: Also required: without it no participant has an email, so none can be matched.
DIRECTORY_SCOPE = "https://www.googleapis.com/auth/directory.readonly"
# Read-only throughout. The directory scope is how a Meet user id becomes an
# email, which is the only thing a participant is matched to a student by.
SCOPES = (
    MEET_SCOPE,
    DIRECTORY_SCOPE,
    "https://www.googleapis.com/auth/userinfo.email",
)

#: Said on the consent copy: the directory permission sounds broader than its use.
DIRECTORY_NOTE = (
    "Avora reads directory names and emails only to match meeting participants to your students."
)

NO_ATTENDANCE_HINT = (
    "Meet attendance needs a paid Google Workspace account — a free Google account "
    "returns no attendance."
)

_PAGE_SIZE = 100
_MAX_PAGES = 20
_PEOPLE_BATCH = 50


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_meet_client_id and settings.google_meet_client_secret)


def _config() -> tuple[str, str, str]:
    settings = get_settings()
    if not settings.google_meet_client_id or not settings.google_meet_client_secret:
        raise MeetingProviderError(
            NOT_CONFIGURED,
            "Google Meet attendance isn't set up for Avora yet. It will appear here once it is.",
        )
    return (
        settings.google_meet_client_id,
        settings.google_meet_client_secret,
        settings.google_meet_redirect_uri,
    )


def build_auth_url(state: str) -> str:
    client_id, _, redirect_uri = _config()
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            # offline + consent: Google only returns a refresh token on consent.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


async def _token_request(data: dict[str, str]) -> TokenGrant:
    client_id, client_secret, _ = _config()
    async with http_client() as http:
        try:
            resp = await http.post(
                TOKEN_URL, data={**data, "client_id": client_id, "client_secret": client_secret}
            )
        except httpx.HTTPError as exc:
            raise MeetingProviderError(
                PROVIDER_ERROR, "Couldn't reach Google. Try again shortly."
            ) from exc
    if resp.status_code in (400, 401):
        raise MeetingProviderError(
            AUTH_FAILED, "Google no longer accepts this connection. Disconnect and connect again."
        )
    raise_for_provider_status(resp, MeetingProvider.google_meet)
    with readable(MeetingProvider.google_meet):
        body = resp.json()
        return TokenGrant(
            access_token=str(body["access_token"]),
            refresh_token=body.get("refresh_token"),
            scopes=str(body.get("scope", "")),
        )


async def revoke(refresh_token: str) -> None:
    """Best-effort revoke at Google when a tutor disconnects. Raises on failure;
    the caller logs it and deletes the connection regardless."""
    async with http_client() as http:
        resp = await http.post(REVOKE_URL, data={"token": refresh_token})
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
            resp = await http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise MeetingProviderError(
                PROVIDER_ERROR, "Couldn't reach Google. Try again shortly."
            ) from exc
    raise_for_provider_status(resp, MeetingProvider.google_meet)
    with readable(MeetingProvider.google_meet):
        email = resp.json().get("email")
        return email if isinstance(email, str) and email else None


async def _get(http: httpx.AsyncClient, access_token: str, url: str, params: dict) -> dict:
    try:
        resp = await http.get(
            url, headers={"Authorization": f"Bearer {access_token}"}, params=params
        )
    except httpx.HTTPError as exc:
        raise MeetingProviderError(
            PROVIDER_ERROR, "Couldn't reach Google. Try again shortly."
        ) from exc
    if resp.status_code == 403:
        raise MeetingProviderError(
            FORBIDDEN,
            "Google wouldn't share this meeting's attendance. " + NO_ATTENDANCE_HINT,
        )
    if resp.status_code == 404:
        raise MeetingProviderError(NOT_FOUND, "Google has no record of that meeting.")
    raise_for_provider_status(resp, MeetingProvider.google_meet)
    with readable(MeetingProvider.google_meet):
        body = resp.json()
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body


async def _conference_record(
    http: httpx.AsyncClient, access_token: str, code: str, moment: LessonMoment
) -> str:
    """A Meet code is reused by every occurrence; attendance is per conference."""
    records: list = []
    token = ""
    for _ in range(_MAX_PAGES):
        params: dict[str, str | int] = {
            "filter": f'space.meeting_code = "{code}"',
            "pageSize": _PAGE_SIZE,
        }
        if token:
            params["pageToken"] = token
        body = await _get(http, access_token, f"{MEET_API}/conferenceRecords", params)
        records.extend(body.get("conferenceRecords", []))
        token = body.get("nextPageToken") or ""
        if not token:
            break
    if not records:
        raise MeetingProviderError(
            "no_data",
            "Google returned no meeting for that code. " + NO_ATTENDANCE_HINT,
        )
    with readable(MeetingProvider.google_meet):
        found = [
            (parse_timestamp(r["startTime"]), str(r["name"]))
            for r in records
            if r.get("name") and r.get("startTime") and r.get("endTime")
        ]
    name = pick_session(found, moment)
    if name is None:
        raise MeetingProviderError(
            NOT_FOUND,
            f"Google has no finished meeting with that code on {moment.local_date.isoformat()}. "
            "Check the link on this lesson and the lesson's date and start time.",
        )
    return name


async def _emails(
    http: httpx.AsyncClient, access_token: str, user_ids: list[str]
) -> dict[str, str]:
    """Meet identifies a signed-in participant by user id, not email. Resolved
    through the People API. A person with no email there is simply absent from the
    result and is surfaced to the tutor rather than guessed at. A FAILED lookup
    (revoked or under-scoped token, rate limit, outage) is an error, never "no
    email": treating it as absence would hide that nobody could be identified."""
    found: dict[str, str] = {}
    for i in range(0, len(user_ids), _PEOPLE_BATCH):
        chunk = user_ids[i : i + _PEOPLE_BATCH]
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("personFields", "emailAddresses"),
            *[("resourceNames", f"people/{uid}") for uid in chunk],
        ]
        try:
            resp = await http.get(
                f"{PEOPLE_API}/people:batchGet",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
        except httpx.HTTPError as exc:
            raise MeetingProviderError(
                PROVIDER_ERROR, "Couldn't reach Google. Try again shortly."
            ) from exc
        if resp.status_code == 403:
            raise MeetingProviderError(
                FORBIDDEN,
                "Google wouldn't let Avora look up participants' emails. The directory "
                "permission may be missing: disconnect and connect again, leaving every "
                "permission ticked.",
            )
        raise_for_provider_status(resp, MeetingProvider.google_meet)
        with readable(MeetingProvider.google_meet):
            for item in resp.json().get("responses", []):
                status = int(item.get("httpStatusCode") or 200)
                if status == 404:
                    continue  # no such person: genuinely no email
                if status >= 400:
                    raise MeetingProviderError(
                        PROVIDER_ERROR,
                        "Google couldn't look up some participants' emails. Try again shortly.",
                    )
                person = item.get("person") or {}
                addresses = person.get("emailAddresses") or []
                primary = next(
                    (a for a in addresses if (a.get("metadata") or {}).get("primary")), None
                )
                chosen = primary or (addresses[0] if addresses else None)
                resource = str(item.get("requestedResourceName") or "")
                if chosen and chosen.get("value") and resource.startswith("people/"):
                    found[resource.removeprefix("people/")] = str(chosen["value"])
    return found


async def fetch_participants(
    access_token: str, meeting_code: str, moment: LessonMoment
) -> ParticipantsResult:
    """Everyone Meet lists for the conference of `meeting_code` that this lesson
    was. Duration is first join to last leave — an upper bound, not time connected.
    An email resolved for a signed-in Google account is `verified`: Google, not the
    joiner, said whose it is."""
    async with http_client() as http:
        record = await _conference_record(http, access_token, meeting_code, moment)
        rows: list = []
        token = ""
        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"pageSize": 250}
            if token:
                params["pageToken"] = token
            body = await _get(http, access_token, f"{MEET_API}/{record}/participants", params)
            with readable(MeetingProvider.google_meet):
                rows.extend(body.get("participants", []))
                token = body.get("nextPageToken") or ""
            if not token:
                break
        with readable(MeetingProvider.google_meet):
            user_ids = [
                str(r["signedinUser"]["user"]).removeprefix("users/")
                for r in rows
                if (r.get("signedinUser") or {}).get("user")
            ]
        emails = await _emails(http, access_token, user_ids) if user_ids else {}

    participants: list[ParticipantRecord] = []
    with readable(MeetingProvider.google_meet):
        for r in rows:
            signed_in = r.get("signedinUser") or {}
            who = signed_in or r.get("anonymousUser") or r.get("phoneUser") or {}
            name = str(who.get("displayName") or "").strip() or "Unknown participant"
            email = None
            if signed_in.get("user"):
                email = emails.get(str(signed_in["user"]).removeprefix("users/"))
            seconds = 0
            if r.get("earliestStartTime") and r.get("latestEndTime"):
                span = parse_timestamp(r["latestEndTime"]) - parse_timestamp(r["earliestStartTime"])
                seconds = max(0, int(span.total_seconds()))
            participants.append(ParticipantRecord(name, email, seconds, verified=email is not None))
    missing = sum(1 for p in participants if p.email is None)
    notes = []
    if missing:
        notes.append(
            f"Google didn't share an email for {missing} "
            f"{'person' if missing == 1 else 'people'} (guests, phone callers, or accounts "
            "outside your organisation)."
        )
    return ParticipantsResult(participants, " ".join(notes) or None)
