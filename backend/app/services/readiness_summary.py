"""Builds a per-subject readiness summary (overall score, predicted grade, weak
topics) for a student. Shared by the readiness API and the Student CRM
aggregation so both read the same numbers."""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    ReadinessConfidence,
    ReadinessHistory,
    ReadinessSnapshot,
    Subject,
    Topic,
    TopicReadiness,
    User,
)
from app.schemas.readiness import (
    StudentReadinessSummary,
    SubjectReadiness,
    TopicReadinessOut,
    WeakTopic,
)
from app.services.averaging import subject_averaging
from app.services.grades import grade_band, predict_grade

# Topics at or below this score (with enough confidence) are surfaced as weak.
WEAK_THRESHOLD = 60.0

# Evidence at this confidence or better counts as real. One definition, because
# the two things that ask the question must agree: whether a topic is weak
# enough to surface, and whether a student counts as covered by their class's
# readiness picture (services/groups.py imports this for the latter).
CONFIDENT = frozenset({ReadinessConfidence.medium, ReadinessConfidence.high})
MIN_WEAK_CONFIDENCE = CONFIDENT

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


# Each engine reads its own history, deliberately. A direction must describe
# the score it is shown beside: pairing a v1 score with an arrow derived from v2
# snapshots would let a stale 45 sit next to an arrow computed from a series
# that ran 40 -> 85 (PROD-1). Together these also reproduce what the trend
# endpoint draws — it prefers v2 and falls back to v1, and each engine here
# calls the matching one — so the arrow and the line stay the same claim.


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


# Each engine reads its own history, deliberately. A direction must describe
# the score it is shown beside: pairing a v1 score with an arrow derived from v2
# snapshots would let a stale 45 sit next to an arrow computed from a series
# that ran 40 -> 85 (PROD-1). Together these also reproduce what the trend
# endpoint draws — it prefers v2 and falls back to v1, and each engine here
# calls the matching one — so the arrow and the line stay the same claim.


async def v1_score_points(db: AsyncSession, student_id: int, subject_id: int) -> list[ScorePoint]:
    """Ordered (oldest-first) v1 history points — what build_summary reports."""
    return [
        (at, score)
        for at, score in (
            await db.execute(
                select(ReadinessHistory.recorded_at, ReadinessHistory.score)
                .where(
                    ReadinessHistory.student_id == student_id,
                    ReadinessHistory.subject_id == subject_id,
                )
                .order_by(ReadinessHistory.recorded_at)
            )
        ).all()
    ]


async def v2_score_points(db: AsyncSession, student_id: int, subject_id: int) -> list[ScorePoint]:
    """Ordered (oldest-first) scored v2 snapshots. Snapshots with no score are
    excluded: a no-evidence run is not a point on anyone's trend line."""
    return [
        (at, score)
        for at, score in (
            await db.execute(
                select(ReadinessSnapshot.created_at, ReadinessSnapshot.score)
                .where(
                    ReadinessSnapshot.student_id == student_id,
                    ReadinessSnapshot.subject_id == subject_id,
                    ReadinessSnapshot.status == AiSynthesisStatus.ready,
                    ReadinessSnapshot.score.is_not(None),
                )
                .order_by(ReadinessSnapshot.created_at)
            )
        ).all()
    ]


async def build_summary(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    subjects_out: list[SubjectReadiness] = []
    for subject_id in subject_ids:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        topics = (await db.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
        topic_by_id = {t.id: t for t in topics}
        readiness_rows = (
            await db.scalars(
                select(TopicReadiness).where(
                    TopicReadiness.student_id == student.id,
                    TopicReadiness.topic_id.in_(list(topic_by_id.keys()) or [0]),
                )
            )
        ).all()

        topic_out: list[TopicReadinessOut] = []
        weighted_sum = 0.0
        weight_total = 0.0
        weak: list[WeakTopic] = []
        for r in readiness_rows:
            topic = topic_by_id.get(r.topic_id)
            if topic is None:
                continue
            topic_out.append(
                TopicReadinessOut(
                    topic_id=topic.id,
                    topic_code=topic.code,
                    topic_title=topic.title,
                    score=r.score,
                    confidence=r.confidence.value,
                    evidence_count=r.evidence_count,
                )
            )
            weighted_sum += topic.weight * r.score
            weight_total += topic.weight
            if r.score <= WEAK_THRESHOLD and r.confidence in MIN_WEAK_CONFIDENCE:
                weak.append(
                    WeakTopic(
                        topic_id=topic.id,
                        topic_code=topic.code,
                        topic_title=topic.title,
                        score=r.score,
                    )
                )

        overall = round(weighted_sum / weight_total, 1) if weight_total > 0 else None
        grade = predict_grade(overall, subject.grade_boundaries) if overall is not None else None
        status = grade_band(grade, subject.grade_boundaries)
        # Same boundary list as the predicted grade above, so the two grades are
        # comparable — which is the only reason showing both is useful (§3.3).
        averaging = await subject_averaging(db, student.id, subject_id)
        averaging_grade = (
            predict_grade(averaging.score, subject.grade_boundaries)
            if averaging.score is not None
            else None
        )
        # No score means no arrow: a direction beside "not enough data yet"
        # would describe a value the card is not showing (PROD-2). The month's
        # movement comes from the same points as the arrow, so the two can never
        # contradict each other on screen.
        points = await v1_score_points(db, student.id, subject_id) if overall is not None else []
        direction = trend_direction(scores_of(points)) if overall is not None else None
        delta = month_delta(points) if overall is not None else None
        # How much of the subject this score actually speaks for. A score drawn
        # from 3 of 40 topics and one drawn from 40 of 40 are different claims
        # and must not render alike (PROD-2), so the counts travel with it.
        topics_with_evidence = sum(1 for t in topic_out if t.evidence_count > 0)
        topic_out.sort(key=lambda t: t.topic_code)
        weak.sort(key=lambda w: w.score)
        subjects_out.append(
            SubjectReadiness(
                subject_id=subject.id,
                subject_name=subject.name,
                exam_board=subject.exam_board,
                grade_scale=subject.grade_scale,
                score=overall,
                predicted_grade=grade,
                status=status,
                averaging_score=averaging.score,
                averaging_grade=averaging_grade,
                marked_piece_count=averaging.marked_piece_count,
                direction=direction,
                month_delta=delta,
                topics_with_evidence=topics_with_evidence,
                topic_count=len(topics),
                topics=topic_out,
                weak_topics=weak[:5],
            )
        )
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
