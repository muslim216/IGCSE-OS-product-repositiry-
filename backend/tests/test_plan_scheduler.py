"""The pure plan scheduler (task 6.3). No database, no AI."""

from collections import Counter
from datetime import date, timedelta

import pytest

from app.services.plan_scheduler import (
    ChapterWeight,
    DateRange,
    NotEnoughLessons,
    ScheduleInput,
    allocate_lessons,
    effective_weekdays,
    schedule,
    spread_weekdays,
)

MON = date(2027, 1, 4)  # a Monday


def spec(chapters, **overrides) -> ScheduleInput:
    values = {
        "chapters": tuple(ChapterWeight(cid, w) for cid, w in chapters),
        "start_date": MON,
        "exam_date": MON + timedelta(weeks=3),  # three weeks
        "lesson_weekdays": (0, 3),  # Mon, Thu -> 6 lessons
        "lessons_per_week": 2,
    }
    values.update(overrides)
    return ScheduleInput(**values)


def per_chapter(lessons):
    return Counter(lesson.chapter_id for lesson in lessons)


def test_weights_one_to_two_split_the_lessons_one_to_two():
    lessons = schedule(spec([(1, 1.0), (2, 2.0)]))
    assert len(lessons) == 6
    assert per_chapter(lessons) == {1: 2, 2: 4}


def test_counts_sum_exactly_to_the_lessons_available_when_rounding_is_awkward():
    # Mon/Wed/Fri over 17 days from Mon 4 Jan: 8 lessons across three equal
    # chapters, which 8/3 does not divide.
    lessons = schedule(
        spec(
            [(1, 1.0), (2, 1.0), (3, 1.0)],
            lesson_weekdays=(0, 2, 4),
            lessons_per_week=3,
            exam_date=MON + timedelta(days=17),
        )
    )
    counts = per_chapter(lessons)
    assert sum(counts.values()) == len(lessons) == 8
    assert max(counts.values()) - min(counts.values()) <= 1
    # Ties in the remainder go to the earlier chapter.
    assert counts[1] >= counts[3]


def test_largest_remainder_goes_to_the_biggest_fraction():
    # 1:1:2 over 5 lessons -> 1.25, 1.25, 2.5: the half wins the spare lesson.
    assert allocate_lessons((1.0, 1.0, 2.0), 5) == [1, 1, 3]
    assert allocate_lessons((1.0, 1.0, 1.0, 7.0), 10) == [1, 1, 1, 7]


def test_every_chapter_gets_a_lesson_even_when_its_weight_is_tiny():
    counts = allocate_lessons((0.01, 100.0, 100.0), 6)
    assert min(counts) >= 1
    assert sum(counts) == 6


def test_sequence_runs_one_to_n_and_chapters_stay_in_the_order_given():
    lessons = schedule(spec([(30, 1.0), (10, 1.0), (20, 1.0)]))
    assert [item.sequence for item in lessons] == list(range(1, 7))
    assert [item.chapter_id for item in lessons] == [30, 30, 10, 10, 20, 20]
    dates = [item.scheduled_date for item in lessons]
    assert dates == sorted(dates)


def test_lessons_fall_only_on_timetable_weekdays():
    lessons = schedule(spec([(1, 1.0), (2, 1.0)]))
    assert {item.scheduled_date.weekday() for item in lessons} == {0, 3}


def test_exam_day_is_excluded_and_start_day_is_included():
    exam = MON + timedelta(weeks=1)  # a Monday: would be a lesson day
    lessons = schedule(spec([(1, 1.0)], exam_date=exam, lesson_weekdays=(0,), lessons_per_week=1))
    assert [item.scheduled_date for item in lessons] == [MON]


def test_nothing_is_scheduled_on_or_after_the_exam_date():
    lessons = schedule(spec([(1, 1.0), (2, 1.0)]))
    assert all(item.scheduled_date < MON + timedelta(weeks=3) for item in lessons)


def test_breaks_are_skipped_inclusive_of_both_ends():
    # Mon/Thu lessons from 4 Jan to the 29th: 4, 7, 11, 14, 18, 21, 25, 28.
    # The break 11th..18th (both ends are lesson days) removes 11, 14, 18.
    brk = DateRange(date(2027, 1, 11), date(2027, 1, 18))
    lessons = schedule(spec([(1, 1.0), (2, 1.0)], breaks=(brk,), exam_date=date(2027, 1, 29)))
    dates = [item.scheduled_date for item in lessons]
    assert dates == [date(2027, 1, d) for d in (4, 7, 21, 25, 28)]


def test_a_break_covering_a_single_day_removes_only_that_day():
    lessons = schedule(spec([(1, 1.0)], breaks=(DateRange(MON, MON),)))
    assert MON not in [item.scheduled_date for item in lessons]
    assert len(lessons) == 5


def test_same_input_gives_the_same_output():
    s = spec(
        [(1, 1.3), (2, 0.7), (3, 2.2)],
        breaks=(DateRange(date(2027, 1, 14), date(2027, 1, 14)),),
    )
    assert schedule(s) == schedule(s)


def test_too_few_lessons_raises_with_both_counts_rather_than_dropping_chapters():
    # Exam on Fri the 8th: lessons on Mon 4th and Thu 7th only.
    with pytest.raises(NotEnoughLessons) as err:
        schedule(spec([(1, 1.0), (2, 1.0), (3, 1.0)], exam_date=date(2027, 1, 8)))
    assert err.value.lessons == 2
    assert err.value.chapters == 3
    assert "2" in str(err.value) and "3" in str(err.value)


def test_exam_before_start_has_zero_lessons():
    with pytest.raises(NotEnoughLessons) as err:
        schedule(spec([(1, 1.0)], exam_date=MON - timedelta(days=1)))
    assert err.value.lessons == 0


def test_exactly_as_many_lessons_as_chapters_gives_one_each():
    lessons = schedule(spec([(1, 5.0), (2, 1.0), (3, 1.0), (4, 1.0), (5, 1.0), (6, 1.0)]))
    assert per_chapter(lessons) == dict.fromkeys(range(1, 7), 1)


def test_no_chapters_means_no_lessons():
    assert schedule(spec([])) == []


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_non_positive_or_non_finite_weight_is_rejected(bad):
    with pytest.raises(ValueError):
        schedule(spec([(1, 1.0), (2, bad)]))


def test_a_break_that_ends_before_it_starts_is_rejected():
    with pytest.raises(ValueError):
        schedule(spec([(1, 1.0)], breaks=(DateRange(MON + timedelta(days=2), MON),)))


def test_a_weekday_outside_the_week_is_rejected():
    with pytest.raises(ValueError):
        schedule(spec([(1, 1.0)], lesson_weekdays=(7,)))


@pytest.mark.parametrize(
    ("per_week", "expected"),
    [
        (1, (0,)),
        (2, (0, 3)),
        (3, (0, 2, 4)),
        (5, (0, 1, 2, 4, 5)),
        (7, (0, 1, 2, 3, 4, 5, 6)),
        (12, (0, 1, 2, 3, 4, 5, 6)),
    ],
)
def test_the_fallback_spreads_lessons_across_the_week(per_week, expected):
    assert spread_weekdays(per_week) == expected


def test_an_empty_timetable_falls_back_to_lessons_per_week():
    lessons = schedule(spec([(1, 1.0), (2, 1.0)], lesson_weekdays=(), lessons_per_week=3))
    assert {item.scheduled_date.weekday() for item in lessons} == {0, 2, 4}
    assert len(lessons) == 9  # three weeks of three


def test_lessons_per_week_equal_to_the_timetable_uses_the_timetable():
    assert effective_weekdays((3, 0), 2) == (0, 3)


def test_fewer_lessons_per_week_than_the_timetable_keeps_an_even_pick_of_its_days():
    # Mon, Wed, Fri, Sat; the tutor wants two a week.
    assert effective_weekdays((0, 2, 4, 5), 2) == (0, 4)
    assert effective_weekdays((0, 2, 4, 5), 1) == (0,)
    lessons = schedule(spec([(1, 1.0)], lesson_weekdays=(0, 2, 4), lessons_per_week=2))
    assert {item.scheduled_date.weekday() for item in lessons} == {0, 2}


def test_more_lessons_per_week_than_the_timetable_adds_days_preferring_the_spread():
    # Timetable Mon only, tutor wants 3: spread(3) = Mon, Wed, Fri.
    assert effective_weekdays((0,), 3) == (0, 2, 4)
    # Timetable Tue, want 2: spread(2) = Mon, Thu; Tue is kept, Mon is the first add.
    assert effective_weekdays((1,), 2) == (0, 1)
    # Always exactly k distinct days, timetable included.
    for timetable in [(1,), (1, 3), (2, 3, 4), (6,)]:
        for k in range(len(timetable), 8):
            days = effective_weekdays(timetable, k)
            assert len(days) == k and set(timetable) <= set(days)


def test_the_tutors_lessons_per_week_wins_over_a_timetable_in_the_schedule():
    lessons = schedule(spec([(1, 1.0)], lesson_weekdays=(1,), lessons_per_week=3))
    assert {item.scheduled_date.weekday() for item in lessons} == {0, 1, 2}


def test_kept_lessons_are_credited_against_their_chapters_share():
    # Six free dates; chapter 2 already holds 2 lessons on other dates. Equal
    # weights over 8 total lessons -> 4 each, so chapter 2 generates only 2.
    lessons = schedule(
        ScheduleInput(
            chapters=(ChapterWeight(1, 1.0), ChapterWeight(2, 1.0, kept_lessons=2)),
            start_date=MON,
            exam_date=MON + timedelta(weeks=3),
            lesson_weekdays=(0, 3),
            lessons_per_week=2,
        )
    )
    assert per_chapter(lessons) == {1: 4, 2: 2}


def test_a_chapter_with_more_kept_lessons_than_its_share_generates_none():
    lessons = schedule(
        ScheduleInput(
            chapters=(ChapterWeight(1, 1.0), ChapterWeight(2, 1.0, kept_lessons=5)),
            start_date=MON,
            exam_date=MON + timedelta(weeks=3),
            lesson_weekdays=(0, 3),
            lessons_per_week=2,
        )
    )
    assert per_chapter(lessons) == {1: 6}


def test_the_past_paper_date_is_carried_and_does_not_truncate_teaching():
    base = schedule(spec([(1, 1.0), (2, 1.0)]))
    carried = schedule(spec([(1, 1.0), (2, 1.0)], past_paper_start_date=MON + timedelta(days=7)))
    assert carried == base
