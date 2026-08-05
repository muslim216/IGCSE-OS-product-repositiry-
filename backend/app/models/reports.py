import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReportAudience(str, enum.Enum):
    student = "student"
    tutor = "tutor"
    parent = "parent"


class ReportStatus(str, enum.Enum):
    generating = "generating"
    ready = "ready"
    failed = "failed"


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    generated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    audience: Mapped[ReportAudience] = mapped_column(
        Enum(ReportAudience, native_enum=False, length=12), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False, length=12),
        default=ReportStatus.generating,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
