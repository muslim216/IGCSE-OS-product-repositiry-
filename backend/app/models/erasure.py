"""Erasing and exporting a child's data (launch audit P-3).

Who reads them: `services/data_export.py` (the ZIP, kept seven days) and
`services/erasure.py` (the request, the undo and the sweep).

Erasure is a request, then a 14-day undo window, then a sweep. The request hides
the child and blocks sign-in; the sweep wipes their data unless the request was
cancelled. The users row stays as a blank "Deleted student" so rows that must
outlive the child keep a valid key.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

_ORGANIZATIONS_ID = "organizations.id"
_USERS_ID = "users.id"


class ErasureRequesterRole(str, enum.Enum):
    tutor = "tutor"
    parent = "parent"
    admin = "admin"


class ErasureRequestStatus(str, enum.Enum):
    pending = "pending"
    cancelled = "cancelled"
    running = "running"
    done = "done"


class ErasureRequest(Base):
    __tablename__ = "erasure_requests"
    __table_args__ = (
        # At most one live request per child. Partial, so a cancelled one does
        # not block asking again. Declared here and in 0078 (`DB-12`).
        Index(
            "uq_erasure_requests_pending_student",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        # The sweep: pending requests whose window has passed.
        Index("ix_erasure_requests_status_scheduled_for", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey(_ORGANIZATIONS_ID, name="fk_erasure_requests_organization_id_organizations"),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey(_USERS_ID, name="fk_erasure_requests_student_id_users"), nullable=False
    )
    # SET NULL: the requester's own account may be removed later.
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            _USERS_ID, name="fk_erasure_requests_requested_by_id_users", ondelete="SET NULL"
        ),
        nullable=True,
    )
    requested_role: Mapped[ErasureRequesterRole] = mapped_column(
        Enum(ErasureRequesterRole, native_enum=False, length=16), nullable=False
    )
    status: Mapped[ErasureRequestStatus] = mapped_column(
        Enum(ErasureRequestStatus, native_enum=False, length=16),
        nullable=False,
        default=ErasureRequestStatus.pending,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stored files still to delete once the rows are gone, so a re-run of the
    # sweep finishes the job instead of orphaning them.
    pending_paths: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DataExportStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    ready = "ready"
    failed = "failed"
    expired = "expired"


class DataExport(Base):
    """A child's data as a ZIP, kept 7 days (`expires_at`)."""

    __tablename__ = "data_exports"
    __table_args__ = (Index("ix_data_exports_status_expires_at", "status", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey(_ORGANIZATIONS_ID, name="fk_data_exports_organization_id_organizations"),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey(_USERS_ID, name="fk_data_exports_student_id_users"), nullable=False
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(_USERS_ID, name="fk_data_exports_requested_by_id_users", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[DataExportStatus] = mapped_column(
        Enum(DataExportStatus, native_enum=False, length=16),
        nullable=False,
        default=DataExportStatus.pending,
    )
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
