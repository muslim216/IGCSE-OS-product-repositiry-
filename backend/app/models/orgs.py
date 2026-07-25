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
