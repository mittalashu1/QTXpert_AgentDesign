"""Response models for workspace-wide usage and cost reporting."""
from datetime import datetime
from typing import Literal

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


class AzureActualCost(BaseModel):
    configured: bool = False
    connected: bool = False
    actual_cost: float | None = None
    currency: str | None = None
    last_synced_at: datetime | None = None
    scope: str | None = None
    resource_name: str | None = None
    error: str | None = None


class CostSurface(BaseModel):
    key: str
    category: str
    service: str
    configured: bool | None = None
    coverage: Literal["actual", "estimated", "manual", "not_configured"]
    actual_cost: float | None = None
    estimated_cost_usd: float | None = None
    currency: str | None = None
    billing_source: str
    note: str
    action: str | None = None


class AICostSummary(BaseModel):
    period_days: int = Field(ge=1)
    since: datetime
    request_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    unpriced_requests: int = 0
    by_model: list[AICostBreakdown] = Field(default_factory=list)
    azure: AzureActualCost = Field(default_factory=AzureActualCost)
    variance_usd: float | None = None
    cost_surfaces: list[CostSurface] = Field(default_factory=list)
    untracked_surface_count: int = 0
