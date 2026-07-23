from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import AiUsageEvent, UserRole
from app.schemas.ai_usage import AiUsageByFeature, AiUsageSummary

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
