"""Pure decision math for planned lessons: topic shares, start times, windows
(task 7.4, AV-119, AV-120). Plain values in, values out, no session (`BE-4`).

Dates and times on a plan slot are the organization's local wall clock; the
instants computed here are UTC. A zone that is unset or cannot be loaded falls
back to UTC, as `timezones.now_in` does, so the surfaces say rather than fail.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import TypeVar
from zoneinfo import ZoneInfo

T = TypeVar("T")

#: The in-app reminder appears this long before a planned lesson starts (owner, 2026-10-04).
REMINDER_LEAD = timedelta(minutes=15)


def split_topics(topics: Sequence[T], index: int, count: int) -> list[T]:
    """This lesson's share of its chapter's topics.

    `index` is the lesson's 0-based position among the chapter's non-cancelled
    planned lessons, `count` how many there are. The topics, already in teaching
    order, are cut into contiguous near-equal chunks with the larger chunks
    first: 5 topics over 3 lessons is [1, 2], [3, 4], [5]. With fewer topics than
    lessons every lesson still gets one, the nearest in proportion, so a lesson
    is never recorded as covering nothing when its chapter has something. An
    index outside the plan, or no topics, is an empty share — never someone
    else's.

    One definition for the next-lesson suggestion and the auto-record, so the two
    cannot disagree about what a lesson covers.
    """
    n = len(topics)
    if n == 0 or count <= 0 or not 0 <= index < count:
        return []
    if n < count:
        return [topics[(index * n) // count]]
    base, extra = divmod(n, count)
    start = index * base + min(index, extra)
    size = base + (1 if index < extra else 0)
    return list(topics[start : start + size])


def timetable_default(by_weekday: Mapping[int, time], day: date) -> time | None:
    """The weekly timetable's start time for this date's weekday; None when the
    timetable has none. Never midnight (`DB-9`)."""
    return by_weekday.get(day.weekday())


def _zone(name: str | None) -> timezone | ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - any tzdata failure degrades to UTC
            pass
    return timezone.utc


def local_instant(day: date, at: time, zone_name: str | None) -> datetime:
    """The aware instant for a local wall-clock date and time."""
    return datetime.combine(day, at.replace(tzinfo=None), tzinfo=_zone(zone_name))


def slot_start_utc(day: date, start: time | None, zone_name: str | None) -> datetime | None:
    """When the lesson starts, or None when it has no start time (never midnight)."""
    if start is None:
        return None
    return local_instant(day, start, zone_name).astimezone(timezone.utc)


def slot_end_utc(day: date, start: time | None, minutes: int, zone_name: str | None) -> datetime:
    """When the lesson's local end has passed from. With no start time the lesson
    is taken to end with its local day, so it is never recorded before the day is
    over."""
    if start is None:
        return local_instant(day + timedelta(days=1), time(0, 0), zone_name).astimezone(
            timezone.utc
        )
    return (local_instant(day, start, zone_name) + timedelta(minutes=minutes)).astimezone(
        timezone.utc
    )


def reminder_window_open(start: datetime | None, end: datetime, now: datetime) -> bool:
    """From fifteen minutes before the start until the end, when the auto-record
    takes over. A lesson with no start time can never have a reminder."""
    if start is None:
        return False
    return start - REMINDER_LEAD <= now < end
