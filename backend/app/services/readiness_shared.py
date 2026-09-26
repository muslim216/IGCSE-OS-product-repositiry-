"""Readiness helpers shared across surfaces — trend direction, the
score-window maths behind "this month", and the v2 history queries that feed
them.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiSynthesisStatus, FactorConfidence, ReadinessSnapshot

# Topics at or below this score (with enough confidence) are surfaced as weak.
# The one copy until 5.6 makes it tutor-set (decision 10).
WEAK_THRESHOLD = 60.0

# Evidence at this confidence or better counts as real. One definition, because
# the two things that ask the question must agree: whether a topic is weak
# enough to surface, and whether a student counts as covered by their class's
# readiness picture (services/groups.py imports this for the latter).
CONFIDENT = frozenset({FactorConfidence.medium, FactorConfidence.high})

# A net change of this many points (or less) across the trend counts as no
# movement. A readiness score is a noisy estimate, so without a dead-zone the
# smallest re-computation would flip an arrow and the direction would mean
# nothing. Three points on the 0-100 scale is about the smallest change a tutor
# would call real; below it, "flat" is the honest answer (CODE-12, UX-31).
DIRECTION_NOISE_BAND = 3.0

# The window "this month" means, in days. Calendar months are 28-31 days long,
# so a calendar-month comparison would make the same amount of progress score
# differently in February than in March; a fixed window is one claim all year.
MONTH_WINDOW_DAYS = 30


def trend_direction(scores: Sequence[float]) -> str | None:
    """Direction of travel from an ordered (oldest-first) score series.

    Returns "up" | "flat" | "down", or None when there are fewer than two
    points — one point is not a trend, and its direction must read as absent,
    never as "flat" (UX-31, PROD-2, edge case 7). Compares the latest score to
    the earliest in the series: the net movement across the window a user can
    see, so the arrow agrees with the trend line rather than chasing the last
    noisy tick.
    """
    if len(scores) < 2:
        return None
    delta = scores[-1] - scores[0]
    if abs(delta) <= DIRECTION_NOISE_BAND:
        return "flat"
    return "up" if delta > 0 else "down"


# A dated point on a trend line. The timestamp is carried rather than dropped at
# the query because two things are asked of the same series and they must not
# disagree: which way it is going, and how far it has moved this month. Reading
# them from two queries is how a surface ends up printing "up" beside "-4".
ScorePoint = tuple[datetime, float]


def scores_of(points: Sequence[ScorePoint]) -> list[float]:
    """Just the scores, oldest first — what trend_direction takes."""
    return [score for _, score in points]


def window_start(now: datetime, periods_ago: int = 0) -> datetime:
    """Midnight UTC, MONTH_WINDOW_DAYS * (periods_ago + 1) days back.

    `periods_ago=0` is the start of "this month"; 1 is the start of the month
    before it. Rolling 30-day windows rather than calendar months, so the same
    amount of progress is scored the same way in February as in March.
    """
    # A naive `now` is treated as UTC, the same rule `_aware` applies to every
    # point timestamp — otherwise astimezone() would read it as host-local time
    # and shift the whole window by the machine's offset.
    midnight = (
        _aware(now).astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    return midnight - timedelta(days=MONTH_WINDOW_DAYS * (periods_ago + 1))


def period_delta(
    points: Sequence[ScorePoint], now: datetime | None = None, periods_ago: int = 0
) -> float | None:
    """Net movement across one MONTH_WINDOW_DAYS window, or None when the series
    does not span it.

    None is the honest answer for a student who joined three days ago: their
    score has no month behind it, and reporting the change since their first
    ever computation as "this month" would credit them with a month of progress
    they have not had. It is also None when nothing was recorded inside the
    window — there is no movement to report, which is not the same as no
    movement, and it is the difference the improvement ranking's first gate
    turns on (a class of eight including one joiner has seven real deltas).

    The baseline is the newest point at or before the window's start, so the
    comparison is against where the student actually stood then rather than
    against their oldest record.

    The window is anchored to midnight UTC, not to the moment of the request.
    Two reasons, and both matter: the number is stable through the day rather
    than drifting between two page loads, and the improvement ranking — this
    same function applied to a whole class — cannot then be used to correlate a
    rank change with a single submission a few minutes earlier.
    """
    now = now or datetime.now(timezone.utc)
    start = window_start(now, periods_ago)
    # Every window — the current one included — ends on a midnight boundary, not
    # at the request time. The current window closes at *today's* midnight, so a
    # snapshot written during the day does not move the delta (or, for the whole
    # class, the rank) until the next day. Ending the current window at `now`
    # instead would let a rank shift minutes after a submission, which is exactly
    # the correlation the midnight anchor exists to prevent (Qodo, CodeRabbit).
    end = window_start(now, periods_ago - 1)
    baseline = [score for at, score in points if _aware(at) <= start]
    if not baseline:
        return None
    inside = [score for at, score in points if start < _aware(at) <= end]
    if not inside:
        return None
    return round(inside[-1] - baseline[-1], 1)


def month_delta(points: Sequence[ScorePoint], now: datetime | None = None) -> float | None:
    """Movement over the current window — what the readiness summary reports."""
    return period_delta(points, now)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes for timezone-aware columns; comparing
    one against an aware `now` raises. Treat a naive value as UTC, which is what
    every writer in this codebase stores."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def v2_score_series(
    db: AsyncSession, student_ids: Sequence[int], subject_id: int
) -> dict[int, list[ScorePoint]]:
    """Ordered (oldest-first) scored v2 snapshots for many students of one
    subject, in one query. A snapshot with no score is excluded: a no-evidence
    run is not a point on anyone's trend line."""
    if not student_ids:
        return {}
    series: dict[int, list[ScorePoint]] = defaultdict(list)
    for student_id, at, score in (
        await db.execute(
            select(
                ReadinessSnapshot.student_id,
                ReadinessSnapshot.created_at,
                ReadinessSnapshot.score,
            )
            .where(
                ReadinessSnapshot.student_id.in_(list(student_ids)),
                ReadinessSnapshot.subject_id == subject_id,
                ReadinessSnapshot.status == AiSynthesisStatus.ready,
                ReadinessSnapshot.score.is_not(None),
            )
            .order_by(ReadinessSnapshot.created_at, ReadinessSnapshot.id)
        )
    ).all():
        series[student_id].append((at, score))
    return dict(series)


async def v2_score_points(db: AsyncSession, student_id: int, subject_id: int) -> list[ScorePoint]:
    """One student's series — the same query as v2_score_series, so the profile
    arrow and the class page arrow cannot drift apart."""
    return (await v2_score_series(db, [student_id], subject_id)).get(student_id, [])
