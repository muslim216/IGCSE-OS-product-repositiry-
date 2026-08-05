from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class GoogleAccount(TimestampMixin, Base):
    """A tutor's connected Google account — one per tutor. The refresh token
    is stored encrypted (see services/google_classroom.py) and is the only
    long-lived credential; access tokens are minted on demand and never
    persisted."""

    __tablename__ = "google_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    google_email: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course_links: Mapped[list["ClassroomCourseLink"]] = relationship(
        back_populates="google_account", cascade="all, delete-orphan"
    )


class ClassroomCourseLink(TimestampMixin, Base):
    """Links one MANARA group to one Google Classroom course. A group can
    have at most one linked course."""

    __tablename__ = "classroom_course_links"
    __table_args__ = (
        UniqueConstraint(
            "google_account_id", "classroom_course_id", name="uq_course_link_account_course"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    google_account_id: Mapped[int] = mapped_column(ForeignKey("google_accounts.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), unique=True, nullable=False)
    classroom_course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    classroom_course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    google_account: Mapped[GoogleAccount] = relationship(back_populates="course_links")
    work_links: Mapped[list["ClassroomWorkLink"]] = relationship(
        back_populates="course_link", cascade="all, delete-orphan"
    )


class ClassroomWorkLink(TimestampMixin, Base):
    """Links one Classroom courseWork item to the draft Assignment the sync
    job created for it, so re-polling updates rather than duplicates."""

    __tablename__ = "classroom_work_links"
    __table_args__ = (
        UniqueConstraint(
            "course_link_id", "classroom_coursework_id", name="uq_work_link_course_coursework"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_link_id: Mapped[int] = mapped_column(
        ForeignKey("classroom_course_links.id"), nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"), unique=True, nullable=False
    )
    classroom_coursework_id: Mapped[str] = mapped_column(String(64), nullable=False)

    course_link: Mapped[ClassroomCourseLink] = relationship(back_populates="work_links")
