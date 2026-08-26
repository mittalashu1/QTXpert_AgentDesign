"""Admin-only LLM usage and cost reporting."""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import require_roles
from app.config import Settings, get_settings
from app.database.models.llm_usage import LLMUsageEvent
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.schemas.usage import AICostBreakdown, AICostSummary, AzureActualCost
from app.services.azure_cost_service import AzureCostService

router = APIRouter(prefix="/admin", tags=["admin"])


def _as_float(value) -> float:
    return float(value or 0)


@router.get("/ai-costs", response_model=AICostSummary)
async def get_ai_costs(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    settings: Annotated[Settings, Depends(get_settings)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AICostSummary:
    """Return internal AI metering plus optional Azure billed-cost reconciliation."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_cost = func.coalesce(func.sum(LLMUsageEvent.estimated_cost_usd), 0).label(
        "estimated_cost_usd"
    )
    totals_result = await db.execute(
        select(
            func.count(LLMUsageEvent.id).label("request_count"),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0).label("output_tokens"),
            total_cost,
            func.count(LLMUsageEvent.id)
            .filter(LLMUsageEvent.estimated_cost_usd.is_(None))
            .label("unpriced_requests"),
        ).where(LLMUsageEvent.created_at >= since)
    )
    totals = totals_result.one()

    model_cost = func.coalesce(func.sum(LLMUsageEvent.estimated_cost_usd), 0).label(
        "estimated_cost_usd"
    )
    model_rows = (
        await db.execute(
            select(
                LLMUsageEvent.provider,
                LLMUsageEvent.model,
                LLMUsageEvent.tier,
                func.count(LLMUsageEvent.id).label("request_count"),
                func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0).label("output_tokens"),
                model_cost,
                func.count(LLMUsageEvent.id)
                .filter(LLMUsageEvent.estimated_cost_usd.is_(None))
                .label("unpriced_requests"),
            )
            .where(LLMUsageEvent.created_at >= since)
            .group_by(LLMUsageEvent.provider, LLMUsageEvent.model, LLMUsageEvent.tier)
            .order_by(model_cost.desc(), LLMUsageEvent.provider, LLMUsageEvent.model)
        )
    ).all()

    estimated_cost = _as_float(totals.estimated_cost_usd)
    azure_snapshot = await AzureCostService(settings).query(days)
    variance_usd = None
    if (
        azure_snapshot.connected
        and azure_snapshot.actual_cost is not None
        and (azure_snapshot.currency or "").upper() == "USD"
    ):
        variance_usd = azure_snapshot.actual_cost - estimated_cost

    return AICostSummary(
        period_days=days,
        since=since,
        request_count=int(totals.request_count or 0),
        input_tokens=int(totals.input_tokens or 0),
        output_tokens=int(totals.output_tokens or 0),
        estimated_cost_usd=estimated_cost,
        unpriced_requests=int(totals.unpriced_requests or 0),
        by_model=[
            AICostBreakdown(
                provider=row.provider,
                model=row.model,
                tier=row.tier,
                request_count=int(row.request_count or 0),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                estimated_cost_usd=_as_float(row.estimated_cost_usd),
                unpriced_requests=int(row.unpriced_requests or 0),
            )
            for row in model_rows
        ],
        azure=AzureActualCost(
            configured=azure_snapshot.configured,
            connected=azure_snapshot.connected,
            actual_cost=azure_snapshot.actual_cost,
            currency=azure_snapshot.currency,
            last_synced_at=azure_snapshot.last_synced_at,
            scope=azure_snapshot.scope,
            resource_name=azure_snapshot.resource_name,
            error=azure_snapshot.error,
        ),
        variance_usd=variance_usd,
    )
