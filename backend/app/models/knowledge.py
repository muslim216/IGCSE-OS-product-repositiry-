import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeEntryKind(str, enum.Enum):
    teaching_method = "teaching_method"
    solving_approach = "solving_approach"
    resource = "resource"
    marking_preference = "marking_preference"
    ai_instruction = "ai_instruction"
    note = "note"


class KnowledgeEntry(TimestampMixin, Base):
    """One piece of a tutor's Knowledge Base — teaching methods, preferred
    solving approaches, resources, marking preferences, direct AI
    instructions, or general notes. Compiled by build_tutor_context() and
    injected into every AI surface so the AI behaves like this specific
    tutor."""

    __tablename__ = "knowledge_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Null = applies across every subject; set = only injected for that subject.
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    kind: Mapped[KnowledgeEntryKind] = mapped_column(
        Enum(KnowledgeEntryKind, native_enum=False, length=24), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
