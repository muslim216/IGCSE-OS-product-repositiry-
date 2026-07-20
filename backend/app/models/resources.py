import enum

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ResourceKind(str, enum.Enum):
    file = "file"
    recording = "recording"


class GroupResource(TimestampMixin, Base):
    """A file or recording link a tutor shares with a group, powering the
    student Files and Recordings tabs."""

    __tablename__ = "group_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[ResourceKind] = mapped_column(
        Enum(ResourceKind, native_enum=False, length=16), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
