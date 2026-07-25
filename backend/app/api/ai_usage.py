from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select

from app.api.deps import CurrentUser, DbSession
from app.models import AiUsageEvent, UserRole
from app.schemas.ai_usage import (
    AiCostAnalytics,
    AiCostBucket,
    AiUsageByFeature,
    AiUsageSummary,
)

router = APIRouter(prefix="/ai-usage", tags=["ai-usage"])


@router.get("/summary", response_model=AiUsageSummary)
async def usage_summary(db: DbSession, user: CurrentUser) -> AiUsageSummary:
    """Per-feature AI token usage for the tutor's organization. Tracking
    only — no allowance enforcement or billing yet (see CLAUDE.md)."""
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    rows = (
        await db.execute(
            select(
                AiUsageEvent.feature,
                func.count(AiUsageEvent.id),
                func.coalesce(func.sum(AiUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(AiUsageEvent.output_tokens), 0),
            )
            .where(AiUsageEvent.organization_id == user.organization_id)
            .group_by(AiUsageEvent.feature)
        )
    ).all()
    by_feature = [
        AiUsageByFeature(
            feature=feature.value,
            call_count=count,
            input_tokens=input_tok,
            output_tokens=output_tok,
        )
        for feature, count, input_tok, output_tok in rows
    ]
    return AiUsageSummary(
        by_feature=by_feature,
        total_input_tokens=sum(f.input_tokens for f in by_feature),
        total_output_tokens=sum(f.output_tokens for f in by_feature),
    )


def _month_expr(dialect: str):
    """A 'YYYY-MM' label for created_at, spelled for the active database.
    SQLite (tests/local) and Postgres (deploy) have no shared date-format
    function, so the expression is chosen per dialect rather than pulling
    every row into Python to bucket it."""
    if dialect == "sqlite":
        return func.strftime("%Y-%m", AiUsageEvent.created_at)
    return func.to_char(AiUsageEvent.created_at, "YYYY-MM")


@router.get("/analytics", response_model=AiCostAnalytics)
async def cost_analytics(
    db: DbSession,
    user: CurrentUser,
    group_by: Literal["feature", "month", "provider"] = Query("feature"),
) -> AiCostAnalytics:
    """AI spend for the tutor's organization, bucketed by feature, provider or
    month. Calls on a model with no configured price are counted separately
    (unpriced_call_count) instead of being folded in as zero — an unknown cost
    is reported as unknown."""
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")

    if group_by == "feature":
        bucket = AiUsageEvent.feature
    elif group_by == "provider":
        bucket = AiUsageEvent.provider
    else:
        bucket = _month_expr(db.bind.dialect.name)

    rows = (
        await db.execute(
            select(
                bucket,
                func.count(AiUsageEvent.id),
                func.coalesce(func.sum(AiUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(AiUsageEvent.output_tokens), 0),
                func.coalesce(func.sum(AiUsageEvent.cost_usd), 0.0),
                func.coalesce(
                    func.sum(case((AiUsageEvent.cost_usd.is_(None), 1), else_=0)), 0
                ),
            )
            .where(AiUsageEvent.organization_id == user.organization_id)
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()

    buckets = [
        AiCostBucket(
            bucket=label.value if hasattr(label, "value") else str(label),
            call_count=count,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cost_usd=round(cost, 6),
            unpriced_call_count=unpriced,
        )
        for label, count, input_tok, output_tok, cost, unpriced in rows
    ]
    return AiCostAnalytics(
        group_by=group_by,
        buckets=buckets,
        total_cost_usd=round(sum(b.cost_usd for b in buckets), 6),
        unpriced_call_count=sum(b.unpriced_call_count for b in buckets),
    )
