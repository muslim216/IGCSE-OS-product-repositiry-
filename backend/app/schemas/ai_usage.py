from pydantic import BaseModel


class AiUsageByFeature(BaseModel):
    feature: str
    call_count: int
    input_tokens: int
    output_tokens: int


class AiUsageSummary(BaseModel):
    by_feature: list[AiUsageByFeature]
    total_input_tokens: int
    total_output_tokens: int


class AiCostBucket(BaseModel):
    """One row of the cost breakdown. `bucket` is the feature name, the
    provider name, or a 'YYYY-MM' month, depending on group_by."""

    bucket: str
    call_count: int
    input_tokens: int
    output_tokens: int
    # Summed estimated spend over the calls that have a configured price.
    cost_usd: float
    # Calls in this bucket whose model has no price configured, so their spend
    # is NOT in cost_usd. A non-zero value means the total is a floor, not the
    # real figure — see services/ai.py MODEL_PRICING.
    unpriced_call_count: int


class AiCostAnalytics(BaseModel):
    group_by: str
    buckets: list[AiCostBucket]
    total_cost_usd: float
    unpriced_call_count: int
