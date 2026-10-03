"""Lays a subject's chapters across the real calendar (task 6.3, AV-14, E5).

Pure: plain frozen dataclasses in, planned lessons out, no session and no I/O
(`BE-4`, `CODE-3`). The AI only ever supplies the *weights*; every date comes
from here, because a model is good at "this chapter is dense" and bad at
arithmetic over a calendar with holidays (E5). Being pure also makes the same
input produce the same plan every time, which is what lets the drafting job be
re-run safely (`BE-6`).

How lessons are counted:

- A lesson falls on every date in `[start_date, exam_date)` whose weekday is a
  lesson weekday and which no break covers. The exam day is excluded: nothing is
  taught on the day of the exam.
- Lesson weekdays come from the class timetable and are used as given. Only when
  the timetable is empty are `lessons_per_week` weekdays spread evenly over the
  week (`spread_weekdays`), so a plan can still be drafted for a class nobody has
  timetabled yet. `lessons_per_week` is deliberately ignored when a timetable
  exists: the timetable is what the tutor actually teaches, and silently
  trimming it to a number typed on a form would drop real lessons.
- Chapters get lessons in proportion to weight (largest-remainder rounding, so
  the counts sum exactly to the lessons available) and keep the order they were
  passed in, which the caller sets from `Chapter.position`.

Past papers: `past_paper_start_date` is carried on the input and not used. The
teaching and past-paper phases overlap by design (AV-16), and every `PlanSlot`
names a chapter, so there is no past-paper slot to schedule.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from math import isfinite

DAYS_IN_WEEK = 7


class NotEnoughLessons(ValueError):
    """Fewer lessons are available than there are chapters.

    Raised rather than dropping chapters or squeezing two into one lesson: a
    plan that silently omits part of the syllabus looks complete and is not
    (`PROD-2`). The tutor's remedy is a later start, a closer exam date, fewer
    breaks or more lessons a week, and the message says which numbers fell short.
    """

    def __init__(self, lessons: int, chapters: int) -> None:
        self.lessons = lessons
        self.chapters = chapters
        super().__init__(
            f"Only {lessons} lesson(s) fit before the exam but the syllabus has "
            f"{chapters} chapters. Add lessons per week, remove breaks or move the exam date."
        )


@dataclass(frozen=True)
class ChapterWeight:
    chapter_id: int
    weight: float


@dataclass(frozen=True)
class DateRange:
    """Both ends inclusive; a one-day break has start == end."""

    start: date
    end: date


@dataclass(frozen=True)
class ScheduleInput:
    # In teaching order. The scheduler never reorders them.
    chapters: tuple[ChapterWeight, ...]
    start_date: date  # inclusive
    exam_date: date  # exclusive
    lesson_weekdays: tuple[int, ...]  # 0 = Monday .. 6 = Sunday; empty = use the fallback
    lessons_per_week: int
    breaks: tuple[DateRange, ...] = ()
    past_paper_start_date: date | None = None


@dataclass(frozen=True)
class ScheduledLesson:
    chapter_id: int
    scheduled_date: date
    sequence: int  # 1-based, in teaching order


def spread_weekdays(lessons_per_week: int) -> tuple[int, ...]:
    """`lessons_per_week` weekdays spread as evenly as the week allows, from Monday.

    `(i * 7) // n` for i in 0..n-1: 2 -> Mon, Thu; 3 -> Mon, Wed, Fri;
    5 -> Mon, Tue, Wed, Fri, Sat. Capped at 7 — one lesson per day, because the
    plan has no notion of two lessons on one date.
    """
    n = max(0, min(lessons_per_week, DAYS_IN_WEEK))
    return tuple((i * DAYS_IN_WEEK) // n for i in range(n))


def effective_weekdays(lesson_weekdays: tuple[int, ...], lessons_per_week: int) -> tuple[int, ...]:
    for day in lesson_weekdays:
        if not 0 <= day <= 6:
            raise ValueError(f"weekday {day} is not in 0..6")
    if lesson_weekdays:
        return tuple(sorted(set(lesson_weekdays)))
    return spread_weekdays(lessons_per_week)


def available_lesson_dates(
    start_date: date,
    exam_date: date,
    weekdays: tuple[int, ...],
    breaks: tuple[DateRange, ...] = (),
) -> list[date]:
    """Every date a lesson can fall on, ascending. See the module docstring."""
    for brk in breaks:
        if brk.end < brk.start:
            raise ValueError("a break ends before it starts")
    days = frozenset(weekdays)
    dates: list[date] = []
    current = start_date
    while current < exam_date:
        if current.weekday() in days and not any(b.start <= current <= b.end for b in breaks):
            dates.append(current)
        current += timedelta(days=1)
    return dates


def allocate_lessons(weights: tuple[float, ...], lessons: int) -> list[int]:
    """Split `lessons` across chapters in proportion to `weights`.

    Largest-remainder rounding, so the counts sum to exactly `lessons`; ties go
    to the earlier chapter. Every chapter then gets at least one: a chapter that
    rounds to zero is topped up from the chapter holding the most lessons (the
    earliest on a tie), which is the least visible place to take one from.
    Fractions rather than floats so the answer cannot depend on rounding noise.
    """
    count = len(weights)
    if lessons < count:
        raise NotEnoughLessons(lessons, count)
    for weight in weights:
        if not isfinite(weight) or weight <= 0:
            raise ValueError(f"chapter weight must be a positive number, got {weight!r}")
    exact = [Fraction(w) for w in weights]
    total = sum(exact)
    quotas = [lessons * w / total for w in exact]
    counts = [int(q) for q in quotas]  # floor: quotas are positive
    leftover = lessons - sum(counts)
    # Largest fractional part first; the index breaks ties deterministically.
    by_remainder = sorted(range(count), key=lambda i: (-(quotas[i] - counts[i]), i))
    for i in by_remainder[:leftover]:
        counts[i] += 1
    for i in range(count):
        if counts[i] == 0:
            donor = max(range(count), key=lambda j: (counts[j], -j))
            counts[donor] -= 1
            counts[i] = 1
    return counts


def schedule(spec: ScheduleInput) -> list[ScheduledLesson]:
    """The plan: one `ScheduledLesson` per available lesson date, in order.

    Raises `NotEnoughLessons` if the calendar has fewer lessons than chapters.
    """
    if not spec.chapters:
        return []
    weekdays = effective_weekdays(spec.lesson_weekdays, spec.lessons_per_week)
    dates = available_lesson_dates(spec.start_date, spec.exam_date, weekdays, spec.breaks)
    counts = allocate_lessons(tuple(c.weight for c in spec.chapters), len(dates))
    lessons: list[ScheduledLesson] = []
    cursor = 0
    for chapter, count in zip(spec.chapters, counts, strict=True):
        for _ in range(count):
            lessons.append(
                ScheduledLesson(
                    chapter_id=chapter.chapter_id,
                    scheduled_date=dates[cursor],
                    sequence=cursor + 1,
                )
            )
            cursor += 1
    return lessons
