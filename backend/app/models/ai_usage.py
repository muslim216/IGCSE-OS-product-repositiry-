import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class AiFeature(str, enum.Enum):
    marking = "marking"
    chat = "chat"
    report = "report"
    extraction = "extraction"
    readiness = "readiness"


class AiUsageEvent(Base):
    """One AI API call, metered at the services/ai.py choke point. Foundation
    for a future tutor AI allowance + student pay-as-you-go top-ups — no
    enforcement or payments yet, this is usage tracking only."""

    __tablename__ = "ai_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    feature: Mapped[AiFeature] = mapped_column(
        Enum(AiFeature, native_enum=False, length=16), nullable=False
    )
    # "anthropic" | "gemini" — see services/ai.py AiProvider. Kept as a plain
    # string so adding a provider never needs a migration.
    provider: Mapped[str] = mapped_column(String(16), default="anthropic", nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which version of the surface's system prompt produced this call — see
    # services/prompts.py. Null for calls made before prompt versioning.
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Estimated spend from the configured per-token pricing. NULL means "no
    # price configured for this model" — never a guessed figure.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
