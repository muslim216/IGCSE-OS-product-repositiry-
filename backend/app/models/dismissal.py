"""A tutor's "Not now" on something their home page asked them to do."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DismissedPrompt(TimestampMixin, Base):
    """One hidden prompt for one user. `key` is an opaque label the frontend
    chose (see `services/dismissals.py`); it points at nothing and grants nothing.

    Unique on (user_id, key) so hiding twice is one row, which is what makes the
    PUT idempotent even when two tabs race.
    """

    __tablename__ = "dismissed_prompts"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_dismissed_prompts_user_id_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
