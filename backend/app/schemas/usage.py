"""Response models for workspace-wide usage and cost reporting."""
from datetime import datetime

from pydantic import BaseModel, Field


class AICostBreakdown(BaseModel):
    provider: str
    model: str
    tier: str
    request_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    unpriced_requests: int = 0


class AICostSummary(BaseModel):
    period_days: int = Field(ge=1)
    since: datetime
    request_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    unpriced_requests: int = 0
    by_model: list[AICostBreakdown] = Field(default_factory=list)
