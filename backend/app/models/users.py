import enum

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    student = "student"
    tutor = "tutor"
    parent = "parent"
    admin = "admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Either email or username must be set. Younger students may not have an
    # email address, so tutors can create username-only accounts for them.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Every user belongs to an organization — auto-created for a tutor at
    # signup; students/parents inherit the org of the tutor who created or
    # invited them. Multi-tenant backbone, single-tutor UX (see CLAUDE.md).
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Bumped on logout/password change to invalidate any refresh tokens issued
    # before that point — JWTs are otherwise stateless and can't be revoked.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
