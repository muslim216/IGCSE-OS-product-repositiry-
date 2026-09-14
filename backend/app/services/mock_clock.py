"""The mock clock, which is the server's.

`AV-116`: a mock is timed from when the student first opens it, and the clock
is server-side. A countdown in the browser is a *display* of this, never the
limit — a tab can be reloaded, a device clock moved, a page left open
overnight. Every figure a student or tutor sees comes from here, computed from
one row the server wrote.

The other half of `AV-116` is that **a late submission is accepted and flagged,
never blocked**. Nothing in this module refuses anything; it reports. Refusing
would lose a student's work to punish something the tutor is better placed to
judge, and the flag is what lets them judge it.

Pure by `BE-4` apart from the one write that starts the clock: given an opening
and a duration, the arithmetic is plain values in, values out.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Mock, MockOpening
from app.models.base import utcnow


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone=True columns, and
    # every arithmetic here subtracts one stored timestamp from `utcnow()`,
    # which is aware. Postgres returns aware, so without this the whole module
    # works in CI and raises on the suite — or the other way round (`RISK-3`).
    # Same helper, same reason, as `services/invites.py`.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Clock:
    """What a student's screen needs to show, decided here rather than there."""

    opened_at: datetime
    #: None when the mock has no duration set — an untimed mock, which is a
    #: normal thing for a tutor to set. Absent, not zero (`PROD-2`, `UX-19`).
    due_at: datetime | None
    seconds_remaining: int | None
    #: True once the time is up. It never stops a submission; it labels one.
    overdue: bool


def read(
    opened_at: datetime, duration_minutes: int | None, *, now: datetime | None = None
) -> Clock:
    """The state of one student's clock. No session, no I/O."""
    now = now or utcnow()
    opened_at = _aware(opened_at)
    if duration_minutes is None:
        return Clock(opened_at=opened_at, due_at=None, seconds_remaining=None, overdue=False)
    due_at = opened_at + timedelta(minutes=duration_minutes)
    remaining = (due_at - now).total_seconds()
    # Clamped at zero so a screen never has to decide what a negative countdown
    # means, while `overdue` carries the fact that it ran out.
    return Clock(
        opened_at=opened_at,
        due_at=due_at,
        seconds_remaining=max(0, int(remaining)),
        overdue=remaining <= 0,
    )


async def start(session: AsyncSession, mock: Mock, student_id: int) -> MockOpening:
    """The student's opening row, created on the first call and returned
    unchanged on every one after.

    Idempotent in the way that matters here: the clock starts **once**, so
    closing the tab and coming back does not buy more time. Two simultaneous
    opens race, and the loser catches the unique violation and re-reads the
    winner's row rather than handing back a second start time.
    """
    existing = await session.scalar(
        select(MockOpening).where(
            MockOpening.mock_id == mock.id, MockOpening.student_id == student_id
        )
    )
    if existing is not None:
        return existing

    opening = MockOpening(mock_id=mock.id, student_id=student_id)
    try:
        # A SAVEPOINT, not the whole transaction. `uq_mock_openings_mock_id_
        # student_id` can fire here — another request created the row between
        # the read above and this flush — and on Postgres a failed statement
        # poisons the transaction until something rolls back. A plain
        # `session.rollback()` would do that by discarding *everything*
        # uncommitted in the session, silently taking any work the caller had
        # already staged. Today's only caller stages none; the next one should
        # not have to know that.
        async with session.begin_nested():
            session.add(opening)
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(
            select(MockOpening).where(
                MockOpening.mock_id == mock.id, MockOpening.student_id == student_id
            )
        )
        if winner is None:  # pragma: no cover — the row that just collided
            raise
        return winner
    return opening


def elapsed_minutes(opened_at: datetime, submitted_at: datetime | None = None) -> int:
    """How long the sitting actually took, rounded up to the minute.

    Up, not down: a student who hands in at 90 minutes and 40 seconds took 91
    minutes, and rounding that to 90 would report a sitting inside its limit
    that was not.
    """
    seconds = ((submitted_at or utcnow()) - _aware(opened_at)).total_seconds()
    return max(0, -(-int(seconds) // 60))
