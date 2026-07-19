from sqlalchemy import JSON, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("exam_board", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_board: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # "9-1" (Edexcel IGCSE) or "A*-E" (Cambridge O Level)
    grade_scale: Mapped[str] = mapped_column(String(16), nullable=False)
    # Ordered list of {"grade": "9", "min": 90} — readiness % → predicted grade.
    grade_boundaries: Mapped[list] = mapped_column(JSON, nullable=False)

    topics: Mapped[list["Topic"]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="topics")
