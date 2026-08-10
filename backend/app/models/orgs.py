from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Organization(TimestampMixin, Base):
    """The multi-tenant backbone. Auto-created per tutor at signup — the product
    UX stays single-tutor even though every aggregate is org-scoped underneath,
    so a later move to multi-tutor organizations needs no schema change."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # IANA zone name ("Africa/Cairo"), captured from the browser at tutor
    # signup and editable in Settings. Nullable because every organization
    # created before this column existed has none, and because the browser can
    # fail to report one — callers fall back to UTC and say that they have.
    #
    # It lives on the organization, not the user: a tutor's whole roster shares
    # one timetable, and ScheduleSlot carries a bare weekday and start_time
    # with no zone of its own. This column is what those have always meant
    # implicitly. 64 chars is generous — the longest IANA name is in the
    # mid-thirties — without inviting junk.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
