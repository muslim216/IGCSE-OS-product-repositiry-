"""Shared pieces of the Zoom and Google Meet attendance integrations (7.3, AV-118).

Kept apart from both providers so neither imports the other, and so the one
HTTP client factory is the single choke point tests replace (`QA-8`: no test
reaches a real provider). Async client only (`BE-13`).
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TypeVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from app.models import MeetingProvider

HTTP_TIMEOUT = 20.0
_T = TypeVar("_T")

# Machine-readable reasons a provider call failed. The import row stores one, so
# the tutor sees why and what to do rather than an empty register.
NOT_CONFIGURED = "not_configured"
NOT_CONNECTED = "not_connected"
AUTH_FAILED = "auth_failed"
FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
NO_DATA = "no_data"
RATE_LIMITED = "rate_limited"
PROVIDER_ERROR = "provider_error"

PROVIDER_LABEL = {MeetingProvider.zoom: "Zoom", MeetingProvider.google_meet: "Google Meet"}


class MeetingProviderError(RuntimeError):
    """A provider call failed for a reason the tutor should be told. `message`
    is written for them and never contains a token."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MeetingLinkError(ValueError):
    """The pasted text is not a Zoom or Google Meet meeting link."""


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    #: Zoom rotates it on every refresh; Google returns one only on first consent.
    refresh_token: str | None
    scopes: str


@dataclass(frozen=True)
class ParticipantRecord:
    display_name: str
    email: str | None
    duration_seconds: int
    #: True only when the PROVIDER authenticated this email (a signed-in Google
    #: account). An email a Zoom guest typed in is not verified: anyone can type
    #: a classmate's address, so it is only ever a suggestion for the tutor.
    verified: bool = False


@dataclass(frozen=True)
class ParticipantsResult:
    participants: list[ParticipantRecord]
    #: Something the tutor should know about even though the import worked.
    warning: str | None = None


def http_client() -> httpx.AsyncClient:
    """The one place an HTTP client is built, so tests substitute a mock transport."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT)


_ZOOM_PATH = re.compile(r"^/(?:j/|wc/join/|wc/)(\d{9,11})(?:/join)?/?$")
_MEET_PATH = re.compile(r"^/([a-z]{3}-[a-z]{4}-[a-z]{3})/?$")


def parse_meeting_link(link: str) -> tuple[MeetingProvider, str]:
    """A Zoom or Google Meet link -> (provider, meeting id / meet code). Anything
    else is rejected: a link to some other site would only fail later, at import."""
    try:
        parts = urlsplit(link.strip())
    except ValueError as exc:
        raise MeetingLinkError("That isn't a Zoom or Google Meet link.") from exc
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise MeetingLinkError("Paste the full https:// meeting link from Zoom or Google Meet.")
    if host == "zoom.us" or host.endswith(".zoom.us"):
        match = _ZOOM_PATH.match(parts.path)
        if match:
            return MeetingProvider.zoom, match.group(1)
        raise MeetingLinkError(
            "That Zoom link doesn't contain a meeting ID. Use the invite link "
            "(zoom.us/j/…), not a personal room link."
        )
    if host == "meet.google.com":
        match = _MEET_PATH.match(parts.path.lower())
        if match:
            return MeetingProvider.google_meet, match.group(1)
        raise MeetingLinkError(
            "That Google Meet link doesn't contain a meeting code (meet.google.com/abc-defg-hij)."
        )
    raise MeetingLinkError("That isn't a Zoom or Google Meet link.")


def canonical_link(provider: MeetingProvider, ref: str) -> str:
    """The link rebuilt from what we store. A Zoom invite's passcode is dropped on
    purpose: it is a secret the import never needs."""
    if provider == MeetingProvider.zoom:
        return f"https://zoom.us/j/{ref}"
    return f"https://meet.google.com/{ref}"


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class LessonMoment:
    """When a lesson was held, as UTC instants, built from the lesson's local date
    (and start time, if known) in the class's zone (tutor override, else organization). Provider times are
    UTC; comparing them to a bare date at noon UTC picks the wrong session for an
    evening lesson west of Greenwich or a morning one east of it."""

    local_date: date
    #: The lesson's start instant; None when its start time is unknown (`DB-9`).
    start: datetime | None
    day_start: datetime
    day_end: datetime


#: How far a session's start may be from the lesson's recorded start time.
START_TOLERANCE = timedelta(hours=6)


def lesson_moment(
    lesson_date: date, start_time: time | None, zone_name: str | None
) -> LessonMoment:
    zone = ZoneInfo(zone_name or "UTC")
    day_start = datetime.combine(lesson_date, time.min, tzinfo=zone)
    day_end = datetime.combine(lesson_date + timedelta(days=1), time.min, tzinfo=zone)
    start = datetime.combine(lesson_date, start_time, tzinfo=zone) if start_time else None
    return LessonMoment(
        local_date=lesson_date,
        start=start.astimezone(timezone.utc) if start else None,
        day_start=day_start.astimezone(timezone.utc),
        day_end=day_end.astimezone(timezone.utc),
    )


def pick_session(items: list[tuple[datetime, _T]], moment: LessonMoment) -> _T | None:
    """Of one meeting link's sessions, the one this lesson was. A link reused every
    week otherwise imports the wrong week. With a start time: the nearest session
    within a few hours of it. Without: the one session on the lesson's local day.
    Returns None when there is none, and raises when it cannot tell which of
    several on that day — guessing would import someone else's class."""
    if moment.start is not None:
        near = [
            (abs(start - moment.start), item)
            for start, item in items
            if abs(start - moment.start) <= START_TOLERANCE
        ]
        if not near:
            return None
        best = min(distance for distance, _ in near)
        closest = [item for distance, item in near if distance == best]
        if len(closest) > 1:
            # Two sessions equally near: taking the first would import someone
            # else's class.
            raise MeetingProviderError(
                NOT_FOUND,
                "There was more than one meeting that could be this lesson with this link. "
                "Set the lesson's start time (or check the link) so Avora can tell which one "
                "it was.",
            )
        return closest[0]
    that_day = [item for start, item in items if moment.day_start <= start < moment.day_end]
    if len(that_day) > 1:
        raise MeetingProviderError(
            NOT_FOUND,
            "There was more than one meeting on that day with this link. Set the lesson's "
            "start time so Avora can tell which one was this lesson.",
        )
    return that_day[0] if that_day else None


@contextmanager
def readable(provider: MeetingProvider) -> Iterator[None]:
    """A provider answer missing a field, or not JSON, is a clear error for the
    tutor rather than a crash that leaves their import stuck."""
    try:
        yield
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise MeetingProviderError(
            PROVIDER_ERROR,
            f"{PROVIDER_LABEL[provider]} sent back something Avora couldn't read. "
            "Try again shortly.",
        ) from exc


def raise_for_provider_status(response: httpx.Response, provider: MeetingProvider) -> None:
    """Turn a non-2xx answer into a tutor-readable `MeetingProviderError`."""
    label = PROVIDER_LABEL[provider]
    status = response.status_code
    if status < 400:
        return
    if status == 401:
        raise MeetingProviderError(
            AUTH_FAILED, f"{label} no longer accepts this connection. Disconnect and connect again."
        )
    if status == 429:
        raise MeetingProviderError(
            RATE_LIMITED, f"{label} is limiting requests right now. Try again in a few minutes."
        )
    if status >= 500:
        raise MeetingProviderError(
            PROVIDER_ERROR, f"{label} had a problem on its side. Try again shortly."
        )
    raise MeetingProviderError(PROVIDER_ERROR, f"{label} refused the request (HTTP {status}).")
