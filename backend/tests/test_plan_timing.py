"""Pure decision math behind the reminder and the auto-record (task 7.4, AV-119/AV-120)."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.services.plan_timing import (
    REMINDER_LEAD,
    local_instant,
    reminder_window_open,
    slot_end_utc,
    split_topics,
    timetable_default,
)


def _chunks(n_topics: int, n_lessons: int) -> list[list[int]]:
    topics = list(range(1, n_topics + 1))
    return [split_topics(topics, i, n_lessons) for i in range(n_lessons)]


def test_five_topics_over_three_lessons_is_contiguous_and_front_loaded():
    assert _chunks(5, 3) == [[1, 2], [3, 4], [5]]


def test_even_split_and_single_lesson_takes_everything():
    assert _chunks(4, 2) == [[1, 2], [3, 4]]
    assert _chunks(3, 1) == [[1, 2, 3]]


def test_every_topic_is_taught_exactly_once_when_there_are_enough_topics():
    for n_topics in range(1, 20):
        for n_lessons in range(1, n_topics + 1):
            flat = [t for chunk in _chunks(n_topics, n_lessons) for t in chunk]
            assert flat == list(range(1, n_topics + 1)), (n_topics, n_lessons)
            sizes = [len(c) for c in _chunks(n_topics, n_lessons)]
            assert max(sizes) - min(sizes) <= 1


def test_fewer_topics_than_lessons_every_lesson_gets_one_nearest_topic():
    assert _chunks(2, 4) == [[1], [1], [2], [2]]
    assert _chunks(1, 3) == [[1], [1], [1]]
    assert all(len(c) == 1 for c in _chunks(3, 7))


def test_no_topics_means_no_topics_and_bad_index_is_empty():
    assert split_topics([], 0, 3) == []
    assert split_topics([1, 2], 5, 3) == []  # never IndexError, never a wrong lesson's share
    assert split_topics([1, 2], -1, 3) == []
    assert split_topics([1, 2], 0, 0) == []


def test_timetable_default_picks_the_weekday_and_never_midnight():
    by_weekday = {0: time(17, 0), 2: time(9, 30)}
    assert timetable_default(by_weekday, date(2026, 10, 5)) == time(17, 0)  # Monday
    assert timetable_default(by_weekday, date(2026, 10, 7)) == time(9, 30)  # Wednesday
    assert timetable_default(by_weekday, date(2026, 10, 6)) is None  # Tuesday: unknown


def test_local_instant_uses_the_org_zone_not_utc():
    # 01:00 on 5 Oct in Cairo (UTC+3 in October 2026) is still 4 Oct in UTC.
    got = local_instant(date(2026, 10, 5), time(1, 0), "Africa/Cairo")
    assert got.astimezone(timezone.utc).date() == date(2026, 10, 4)
    assert got.tzinfo is not None


def test_local_instant_falls_back_to_utc_for_unset_or_unloadable_zone():
    for name in (None, "", "Not/AZone"):
        assert local_instant(date(2026, 10, 5), time(9, 0), name) == datetime(
            2026, 10, 5, 9, 0, tzinfo=timezone.utc
        )


def test_slot_end_is_start_plus_minutes_in_the_local_zone():
    end = slot_end_utc(date(2026, 10, 5), time(17, 0), 60, "Africa/Cairo")
    assert end == datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)  # 18:00 local


def test_slot_end_without_a_start_is_the_end_of_the_local_day():
    end = slot_end_utc(date(2026, 10, 5), None, 60, "Africa/Cairo")
    assert end == local_instant(date(2026, 10, 6), time(0, 0), "Africa/Cairo")
    # Not UTC midnight: the boundary must move with the zone.
    assert end != datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)


def test_reminder_window_opens_fifteen_minutes_before_and_closes_at_the_end():
    start = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=60)
    assert timedelta(minutes=15) == REMINDER_LEAD
    assert not reminder_window_open(start, end, start - timedelta(minutes=15, seconds=1))
    assert reminder_window_open(start, end, start - timedelta(minutes=15))
    assert reminder_window_open(start, end, start + timedelta(minutes=30))
    assert not reminder_window_open(start, end, end)  # the auto-record owns it from here


@pytest.mark.parametrize("bad", [None])
def test_reminder_cannot_fire_without_a_start(bad):
    assert not reminder_window_open(
        bad, datetime(2026, 10, 5, tzinfo=timezone.utc), datetime.now(timezone.utc)
    )


def test_end_is_fold_safe_across_a_fall_back():
    # New York falls back at 02:00 EDT on 1 Nov 2026. 00:30 EDT + 90 minutes is
    # 06:00 UTC; wall-clock arithmetic (02:00 "local", read as EST) gives 07:00.
    end = slot_end_utc(date(2026, 11, 1), time(0, 30), 90, "America/New_York")
    assert end == datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)


def test_an_offset_aware_start_time_is_refused_not_silently_dropped():
    with pytest.raises(ValueError):
        local_instant(date(2026, 10, 5), time(9, 0, tzinfo=timezone.utc), "Africa/Cairo")
