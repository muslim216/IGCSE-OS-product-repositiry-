"""Which readiness factor config applies to a (organization, subject).

The one reader of `ReadinessWeights` (task 5.4a). Synthesis, the demo seed, the
settings API and the v2 read surface all resolve through here, so the
precedence cannot drift between them.

Whole-row override (decision 8): the subject's own row if it exists, else the
account row (`subject_id` NULL), else the built-in defaults. A subject row is
never merged field by field with the account row — what the tutor saw on
screen when they saved the override is exactly what applies.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadinessFactor, ReadinessWeights

FACTOR_WEIGHT_ATTR = {
    ReadinessFactor.topic_mastery: "weight_topic_mastery",
    ReadinessFactor.past_paper_performance: "weight_past_paper_performance",
    ReadinessFactor.homework_performance: "weight_homework_performance",
    ReadinessFactor.assessment_performance: "weight_assessment_performance",
    ReadinessFactor.syllabus_coverage: "weight_syllabus_coverage",
    ReadinessFactor.mistake_analysis: "weight_mistake_analysis",
}
DEFAULT_WEIGHTS = dict.fromkeys(FACTOR_WEIGHT_ATTR.values(), 1.0)
#: Mirrors the model's column default.
DEFAULT_HALF_LIFE_DAYS = 45.0
#: Mirrors the model's column default. Topic Mastery at or below this is shown
#: as weak (decision 10). Not MASTERY_THRESHOLD (readiness_v2.py): that line is
#: "mastered, for coverage", this one "weak, for surfacing" — never merge them.
DEFAULT_WEAK_THRESHOLD = 60.0

ConfigSource = Literal["subject", "account", "default"]


def enabled_attr(factor: ReadinessFactor) -> str:
    return f"enabled_{factor.value}"


@dataclass(frozen=True)
class ReadinessConfig:
    weights: dict[str, float]
    enabled: frozenset[ReadinessFactor]
    half_life_days: float
    weak_threshold: float
    source: ConfigSource


def config_from_row(row: ReadinessWeights, source: ConfigSource) -> ReadinessConfig:
    return ReadinessConfig(
        weights={attr: getattr(row, attr) for attr in DEFAULT_WEIGHTS},
        enabled=frozenset(f for f in FACTOR_WEIGHT_ATTR if getattr(row, enabled_attr(f))),
        half_life_days=row.half_life_days,
        weak_threshold=row.weak_threshold,
        source=source,
    )


async def resolve_readiness_config(
    session: AsyncSession, organization_id: int, subject_id: int | None
) -> ReadinessConfig:
    """`subject_id=None` resolves the account scope itself."""
    rows = (
        await session.scalars(
            select(ReadinessWeights).where(
                ReadinessWeights.organization_id == organization_id,
                or_(
                    ReadinessWeights.subject_id.is_(None),
                    ReadinessWeights.subject_id == subject_id,
                ),
            )
        )
    ).all()
    subject_row = next(
        (r for r in rows if subject_id is not None and r.subject_id == subject_id), None
    )
    if subject_row is not None:
        return config_from_row(subject_row, "subject")
    account_row = next((r for r in rows if r.subject_id is None), None)
    if account_row is not None:
        return config_from_row(account_row, "account")
    # A fresh dict, so no caller can edit the shared defaults through it.
    return ReadinessConfig(
        weights=dict(DEFAULT_WEIGHTS),
        enabled=frozenset(FACTOR_WEIGHT_ATTR),
        half_life_days=DEFAULT_HALF_LIFE_DAYS,
        weak_threshold=DEFAULT_WEAK_THRESHOLD,
        source="default",
    )
