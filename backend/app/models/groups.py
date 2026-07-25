import enum
from datetime import datetime, time

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.syllabus import Subject
from app.models.users import User


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    tutor: Mapped[User] = relationship()
    subject: Mapped[Subject] = relationship()
    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    schedule_slots: Mapped[list["ScheduleSlot"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(TimestampMixin, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "student_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    group: Mapped[Group] = relationship(back_populates="members")
    student: Mapped[User] = relationship()


class InviteKind(str, enum.Enum):
    student_join = "student_join"
    parent_link = "parent_link"


class Invite(TimestampMixin, Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    kind: Mapped[InviteKind] = mapped_column(
        Enum(InviteKind, native_enum=False, length=16), nullable=False
    )
    # student_join → the group being joined; parent_link → the student being linked.
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped[Group | None] = relationship()


class ParentLink(TimestampMixin, Base):
    __tablename__ = "parent_links"
    __table_args__ = (UniqueConstraint("parent_id", "student_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    parent: Mapped[User] = relationship(foreign_keys=[parent_id])
    student: Mapped[User] = relationship(foreign_keys=[student_id])


class ScheduleSlot(TimestampMixin, Base):
    """A recurring weekly time template for a group (e.g. "Tuesdays 5pm").
    Not a taught lesson — see models.lessons.Lesson for the actual dated
    event with notes, topics covered, and observations."""

    __tablename__ = "schedule_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday … 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)

    group: Mapped[Group] = relationship(back_populates="schedule_slots")
