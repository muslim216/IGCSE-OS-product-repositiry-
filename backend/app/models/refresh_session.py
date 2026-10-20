"""One sign-in's chain of refresh tokens (`SA-11`)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class RefreshSession(Base):
    """A sign-in on one browser, and which of its refresh tokens is current.

    Every refresh token names its session and a `generation`. Using the current
    one moves the session on a generation and hands back the next token, so a
    token works once. Presenting an older one is how a stolen copy shows
    itself — the thief and the owner cannot both keep using the same chain — and
    ends every session of the account (`services/refresh_sessions.py`).

    No `organization_id`: a session belongs to one user and is never read except
    through that user's own token, so there is nothing for a tenant filter to do.
    """

    __tablename__ = "refresh_sessions"
    # Declared here as well as in migration 0074 so the test schema matches
    # production (`DB-12`).
    __table_args__ = (Index("ix_refresh_sessions_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
