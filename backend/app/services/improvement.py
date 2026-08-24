"""The improvement ranking: a student's own position, and nothing about anyone
else.

**What leaves this module.** For each of the reader's subjects: the reader's own
movement, the reader's own placing, a count of how many people were ranked, and
the reader's own earlier placings. That is the whole payload. No classmate's
score, grade, delta, name, initials or identity is computed into a response
here, and no marker points at a row belonging to someone else — there are no
rows. The ranking exists; the ranked do not appear.

**Why this shape rather than an anonymous board.** A security review of the
drawn design — anonymous rows each carrying an exact delta, the reader marked
"you", gated at five students — returned *do not ship*, on four decisive
vectors. Every one of them needs a per-classmate value to exist somewhere in the
response:

1. **Screenshot collusion.** One shared board where only the "you" marker moves;
   two students comparing screens label two rows, four label the class. It works
   at any class size, so no headcount gate closes it. Closed here because there
   is no shared board: two students comparing screens learn each other's rank
   number and nothing else.
2. **Exact-delta fingerprinting.** Integer deltas rarely collide at n=5-15, so a
   reader who roughly knows one classmate's performance matches them to a row by
   arithmetic. Closed: no classmate's delta is transmitted.
3. **Join/leave landmarks.** A "joined this month" tag or a vanished row *is* a
   name when exactly one student joined or left. Closed: no rows. The
   denominator moves, which reveals only what the class list already shows.
4. **Achievement-event correlation.** The top scorer announces it themselves and
   is then attributable to the board's largest delta. Closed: no largest delta
   is published.

**Three residual risks, accepted rather than solved.** They are recorded because
a later change that reintroduces per-classmate values must know what it is
reopening.

1. *The whole class comparing ranks reconstructs the order.* A "post your rank"
   group chat in a class of eight is one message, and it yields the complete
   ordinal ranking with real names on it. Magnitude and attainment stay hidden,
   but who improved least becomes common knowledge. Nothing in the product can
   prevent this — any ranking a student can see is a ranking a student can
   retype. What the design does is strip everything except the ordinal, so the
   reconstructed artefact is an ordering rather than a record. **The headcount
   floor raises the coordination cost; it does not close this.**
2. *Your own rank moving tells you about someone else.* A student who submitted
   nothing and still fell has learned that a classmate improved. Irreducible in
   any ranking — relative position is by definition information about other
   people — and bounded here to "somebody in this class moved".
3. *Low rank is still a message.* Mitigated by never rendering a bare bottom
   placing: exact rank in the top half, a band below it.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    Group,
    GroupMember,
    ReadinessHistory,
    ReadinessSnapshot,
    Subject,
    Topic,
    TopicReadiness,
    User,
)
from app.schemas.improvement import FocusTopic, ImprovementPeriod, SubjectImprovement
from app.services.readiness_summary import (
    CONFIDENT,
    MONTH_WINDOW_DAYS,
    ScorePoint,
    period_delta,
)

# How many classmates must have a real delta for the full window before a rank
# is shown. Not how many are enrolled: a class of eight including one student
# who joined last week has seven data points, and a headcount test would rank
# them anyway.
#
# Five was the spec's number and it was doing anonymity work. Once no
# per-classmate value is released, k-anonymity stops being the question, so five
# would be defensible purely as a statistical-validity floor. It is raised to
# eight for one reason: at five, organising the whole class to compare ranks is
# a five-message group chat. Eight raises the coordination cost and dilutes the
# result if it happens anyway. **This is defence-in-depth, not an anonymity
# mechanism** — a later change must not read it as one and conclude residual
# risk 1 is closed.
MIN_RANKED = 8

# And how much of the class must be represented. Ranking the three students who
# have evidence out of twelve is not a ranking (PROD-2): the reader would be
# told they are "2nd of 3" in a class of twelve, which is a different and much
# more flattering claim than the one the data supports.
MIN_RANKED_FRACTION = 0.5

# How many earlier windows the tab shows under YOUR MONTHS. Three windows of
# history is enough to see a trend in one's own placing and short enough that
# every point in it was computed from evidence the student can still remember.
HISTORY_PERIODS = 3

PERIOD_LABELS = ["This month", "Last month", "Two months ago", "Three months ago"]


@dataclass(frozen=True)
class Placing:
    """One period's outcome for the reader. `rank` is None when a gate is not
    met — which is a complete answer, not a degraded one: their own movement
    still renders."""

    delta: float | None
    rank: int | None
    ranked_count: int
    banded: bool


def rank_of(reader_delta: float, deltas: list[float]) -> tuple[int, bool]:
    """The reader's competition rank among `deltas` (which includes their own),
    and whether it must be shown as a band rather than a number.

    **Ties share the better rank.** Two students who both improved by 6 are
    joint 3rd; the next student is 5th. The alternative — breaking ties by
    student id, or by name — invents an ordering the data does not contain and
    puts one of two identical performances above the other.

    **Top half is `rank <= floor(n / 2)`.** At n=11 ranks 1-5 are exact and 6-11
    are banded. Below the halfway line the tab says "in the second half this
    month" instead of a number, because a bare "9th of 11" discourages even with
    nobody named — the exact failure the home surfaces are designed against.

    **A tie spanning the boundary is banded for everyone in it.** Three students
    tied on rank 5 at n=11 occupy positions 5, 6 and 7; showing all three "5th"
    would render the exact placing this rule exists to avoid for two of them,
    and showing them different numbers would break the tie rule above. So the
    whole tie group is banded. This is the off-by-one the design calls out by
    name, and it is why the check below tests the *last* position the tie
    occupies rather than its rank.

    `deltas` must contain `reader_delta` exactly once — every count below
    (`better`, `tie_size`, `n`) is only correct with the reader counted in.
    `placing()`, the sole caller, always includes them. Enforced rather than
    only documented, so a future caller that passes a peers-only list fails
    loudly instead of silently returning an off-by-one rank (Qodo).
    """
    assert deltas.count(reader_delta) >= 1, "deltas must include the reader's own value"
    n = len(deltas)
    better = sum(1 for d in deltas if d > reader_delta)
    rank = better + 1
    tie_size = sum(1 for d in deltas if d == reader_delta)
    cutoff = n // 2
    last_position = rank + tie_size - 1
    return rank, last_position > cutoff


def placing(reader_id: int, deltas: dict[int, float], member_count: int) -> Placing:
    """Apply both gates, then rank. Order matters only for clarity — a class that
    fails either gate gets the same answer."""
    reader_delta = deltas.get(reader_id)
    ranked = list(deltas.values())
    gated = len(ranked) < MIN_RANKED or (
        member_count > 0 and len(ranked) / member_count < MIN_RANKED_FRACTION
    )
    if reader_delta is None or gated:
        # The reader's own movement still travels: it is theirs, it needs no
        # class to be true, and a surface with only that on it is complete.
        return Placing(delta=reader_delta, rank=None, ranked_count=len(ranked), banded=False)
    rank, banded = rank_of(reader_delta, ranked)
    return Placing(delta=reader_delta, rank=rank, ranked_count=len(ranked), banded=banded)


async def _peer_points(
    db: AsyncSession, student_ids: list[int], subject_id: int
) -> dict[int, list[ScorePoint]]:
    """Every ranked student's score series for one subject, engine of record per
    student, in two queries.

    Each student is measured on the engine their own surfaces report — v2 where
    a scored snapshot exists, v1 otherwise — which is what makes the reader's
    delta here identical to the one on their Progress page rather than a second
    number with the same label (PROD-1).

    Mixing engines inside one ranking sounds like it should be a problem and is
    not, because of what is being ranked: a *change* in a 0-100 readiness score,
    not the score. A student who gained a v2 series mid-window has no v2 point at
    or before the window's start, so period_delta returns None for them and they
    drop out of the ranking — which is exactly the treatment the "full period"
    gate demands.
    """
    if not student_ids:
        return {}
    v2: dict[int, list[ScorePoint]] = {}
    for sid, at, score in (
        await db.execute(
            select(
                ReadinessSnapshot.student_id,
                ReadinessSnapshot.created_at,
                ReadinessSnapshot.score,
            )
            .where(
                ReadinessSnapshot.student_id.in_(student_ids),
                ReadinessSnapshot.subject_id == subject_id,
                ReadinessSnapshot.status == AiSynthesisStatus.ready,
                ReadinessSnapshot.score.is_not(None),
            )
            .order_by(ReadinessSnapshot.created_at)
        )
    ).all():
        v2.setdefault(sid, []).append((at, score))

    v1: dict[int, list[ScorePoint]] = {}
    for sid, at, score in (
        await db.execute(
            select(
                ReadinessHistory.student_id, ReadinessHistory.recorded_at, ReadinessHistory.score
            )
            .where(
                ReadinessHistory.student_id.in_(student_ids),
                ReadinessHistory.subject_id == subject_id,
            )
            .order_by(ReadinessHistory.recorded_at)
        )
    ).all():
        v1.setdefault(sid, []).append((at, score))

    return {sid: v2.get(sid) or v1.get(sid, []) for sid in student_ids}


async def _classmates(db: AsyncSession, student: User, subject_id: int) -> list[int]:
    """Everyone the reader shares a class in this subject with, including
    themselves.

    Scoped by **(organization, subject)**, never subject alone. Subjects are
    global — every organization teaches the same Chemistry row — so a
    subject-only scope would rank a student against strangers in another
    tenant's classes and publish the size of that tenant's cohort (SEC-8). The
    organization comes from the authenticated reader, never from a parameter
    (SEC-7).
    """
    return list(
        (
            await db.scalars(
                select(GroupMember.student_id)
                .join(Group, Group.id == GroupMember.group_id)
                .where(
                    Group.subject_id == subject_id,
                    Group.organization_id == student.organization_id,
                    Group.id.in_(
                        select(GroupMember.group_id).where(GroupMember.student_id == student.id)
                    ),
                )
                .distinct()
            )
        ).all()
    )


async def _focus_topics(
    db: AsyncSession, student_id: int, subject_id: int, limit: int = 3
) -> list[tuple[str, str, float | None]]:
    """WHAT WOULD MOVE YOU UP — the reader's own weakest topics, and only theirs.

    A topic with no confident evidence carries no score: it is returned with
    None so the surface says "not enough data yet" rather than printing a number
    the engine did not stand behind (PROD-2).
    """
    # Filter to confident rows *before* ordering and limiting. Otherwise the
    # three lowest-score rows are taken first and a low-confidence topic can fill
    # a slot a confident, actionable topic should have held — leaving the reader
    # three "not enough data yet" lines under a heading that promises the
    # opposite (CodeRabbit).
    rows = (
        await db.execute(
            select(Topic.code, Topic.title, TopicReadiness.score)
            .join(TopicReadiness, TopicReadiness.topic_id == Topic.id)
            .where(
                TopicReadiness.student_id == student_id,
                Topic.subject_id == subject_id,
                TopicReadiness.confidence.in_(CONFIDENT),
            )
            .order_by(TopicReadiness.score)
            .limit(limit)
        )
    ).all()
    return [(code, title, score) for code, title, score in rows]


async def build_improvement(
    db: AsyncSession, student: User, subject_ids: list[int], now: datetime | None = None
) -> list[SubjectImprovement]:
    """The reader's improvement view, one entry per subject they are enrolled in."""
    now = now or datetime.now(timezone.utc)
    out: list[SubjectImprovement] = []

    # One read for every subject, not one db.get per subject in the loop below.
    subjects = {
        s.id: s
        for s in (await db.scalars(select(Subject).where(Subject.id.in_(subject_ids)))).all()
    }
    for subject_id in subject_ids:
        subject = subjects.get(subject_id)
        if subject is None:
            continue
        peers = await _classmates(db, student, subject_id)
        if student.id not in peers:
            # Enrolled in the subject but in no class for it — there is no
            # cohort to rank against, and inventing one from the organization at
            # large would rank them against people they have never met.
            continue
        member_count = len(peers)
        points = await _peer_points(db, peers, subject_id)

        periods: list[ImprovementPeriod] = []
        for index in range(HISTORY_PERIODS + 1):
            deltas = {
                sid: delta
                for sid, series in points.items()
                if (delta := period_delta(series, now, index)) is not None
            }
            result = placing(student.id, deltas, member_count)
            if result.delta is None and result.rank is None and index > 0:
                # An empty earlier window is left out rather than listed as a
                # row saying nothing happened — the student may simply not have
                # been here yet (UX-29).
                continue
            periods.append(
                ImprovementPeriod(
                    label=PERIOD_LABELS[index],
                    delta=result.delta,
                    rank=result.rank,
                    ranked_count=result.ranked_count,
                    banded=result.banded,
                )
            )

        out.append(
            SubjectImprovement(
                subject_id=subject.id,
                subject_name=subject.name,
                window_days=MONTH_WINDOW_DAYS,
                member_count=member_count,
                periods=periods,
                focus=[
                    FocusTopic(topic_code=code, topic_title=title, score=score)
                    for code, title, score in await _focus_topics(db, student.id, subject_id)
                ],
            )
        )
    return out
