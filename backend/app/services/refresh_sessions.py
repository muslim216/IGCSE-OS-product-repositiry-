"""Single-use refresh tokens, and what happens when one is used twice (`SA-11`).

A refresh token used to be a 30-day bearer credential that could be replayed
any number of times, so a cookie copied off a shared school laptop worked
silently for a month. Now each sign-in is a `RefreshSession` and each token
names a generation of it: a token works once, and a second use outside the
grace window ends every session the account has (`users.token_version`, the
same switch logout and a tutor's password reset use — `SEC-1`).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import RefreshSession, User
from app.models.base import utcnow

log = logging.getLogger("auth")


def _aware(value: datetime) -> datetime:
    # SQLite hands timestamps back naive; they were written in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def expires_at(session: RefreshSession, now: datetime) -> datetime:
    """When the token about to be issued for `session` stops working: after a
    stretch of no use, and never past the sign-in's hard limit."""
    settings = get_settings()
    idle = now + timedelta(days=settings.refresh_token_expire_days)
    hard = _aware(session.created_at) + timedelta(days=settings.refresh_session_max_days)
    return min(idle, hard)


async def start(db: AsyncSession, user: User) -> RefreshSession:
    """A new sign-in for `user`. The caller commits.

    Clears the user's sessions that are past their hard limit on the way, so the
    table holds about one row per browser per user rather than one per sign-in
    for ever.
    """
    now = utcnow()
    cutoff = now - timedelta(days=get_settings().refresh_session_max_days)
    await db.execute(
        delete(RefreshSession).where(
            RefreshSession.user_id == user.id, RefreshSession.created_at < cutoff
        )
    )
    session = RefreshSession(user_id=user.id, generation=0, created_at=now, rotated_at=now)
    db.add(session)
    await db.flush()
    return session


async def rotate(
    db: AsyncSession, user: User, session_id: int, generation: int
) -> RefreshSession | None:
    """The session to issue the next token from, or None to refuse.

    The token presented must already have passed its signature, expiry, type and
    `token_version` checks. Three cases:

    - It is the current token: the session moves on one generation.
    - It is the one just replaced, within the grace window: the same browser
      refreshing from several requests at once. They all get the current token.
    - Anything older is a replay. Someone else holds a copy of this chain, and
      there is no telling which party is the owner, so the account's every
      session ends and whoever is real signs in again with the password.
    """
    now = utcnow()
    session = await db.get(RefreshSession, session_id)
    if session is None or session.user_id != user.id:
        return None
    # No expiry check here: every token's own `exp` is already capped at the
    # session's hard limit by `expires_at`, and the signature check enforces it.

    if generation == session.generation:
        # Conditional on the generation, so two requests racing on the same
        # token move the session once, not twice; the loser lands in the grace
        # branch below with the winner's token.
        moved = await db.execute(
            update(RefreshSession)
            .where(RefreshSession.id == session.id, RefreshSession.generation == generation)
            .values(generation=generation + 1, rotated_at=now)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(session)
        if moved.rowcount == 1:  # type: ignore[attr-defined]
            return session

    grace = timedelta(seconds=get_settings().refresh_reuse_grace_seconds)
    if generation == session.generation - 1 and now - _aware(session.rotated_at) <= grace:
        return session

    log.warning(
        "refresh token replayed; ending every session (user_id=%s session_id=%s)",
        user.id,
        session.id,
    )
    user.token_version += 1
    await db.delete(session)
    await db.commit()
    return None
