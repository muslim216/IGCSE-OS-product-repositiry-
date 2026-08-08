"""The organization's timezone: validating it, and answering "what day is it".

The value arrives from a browser (Intl.DateTimeFormat().resolvedOptions()
.timeZone) and is therefore untrusted input. It is checked against the
system's own IANA database before it is ever stored, so a junk or hostile
string is rejected at the edge rather than persisted and then raising inside a
background job days later, far from the request that caused it.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

# Built once: available_timezones() walks the tzdata files on every call, and
# this is consulted on every signup and settings write.
_KNOWN = frozenset(available_timezones())


def is_valid_timezone(name: str) -> bool:
    """True when `name` is an IANA zone this system knows.

    Membership against the real database rather than a regex: "Africa/Cairo"
    and "Not/AZone" are indistinguishable by shape, and the only authority on
    which one resolves is the tzdata the server actually has.
    """
    return name in _KNOWN


def normalize_timezone(name: str | None) -> str | None:
    """The stored form of a submitted zone, or None to clear it.

    Raises ValueError for anything else, so a caller cannot quietly persist a
    zone that will fail to load later.
    """
    if name is None:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    if not is_valid_timezone(cleaned):
        raise ValueError(f"Unknown timezone: {cleaned}")
    return cleaned


def now_in(name: str | None) -> datetime:
    """The current time in the organization's zone, falling back to UTC.

    An unset zone falls back rather than failing — most organizations predate
    the column. A *stored but unloadable* zone also falls back rather than
    raising: tzdata can be trimmed or a zone retired between the write and the
    read, and a tutor's lesson list is not worth a 500. Both cases mean the
    surface is reporting UTC, which it says rather than implies.
    """
    if name:
        try:
            return datetime.now(ZoneInfo(name))
        except Exception:  # noqa: BLE001 - any tzdata failure degrades to UTC
            pass
    return datetime.now(timezone.utc)


def today_weekday(name: str | None) -> int:
    """Monday=0 .. Sunday=6 in the organization's zone.

    This is the whole point of storing the column: at 01:00 in Cairo it is
    already tomorrow's weekday, while UTC still says yesterday.
    """
    return now_in(name).weekday()
