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
