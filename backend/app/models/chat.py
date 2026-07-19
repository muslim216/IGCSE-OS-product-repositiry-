import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ChatConversation(TimestampMixin, Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="New chat", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(
        Enum(ChatRole, native_enum=False, length=12), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
