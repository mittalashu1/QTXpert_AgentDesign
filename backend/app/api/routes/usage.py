"""Owner-only ecosystem usage and cost reporting."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import require_roles
from app.config import Settings, get_settings
from app.database.models.llm_usage import LLMUsageEvent
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.schemas.usage import AICostBreakdown, AICostSummary, AzureActualCost, CostSurface
from app.services.azure_cost_service import AzureCostService

router = APIRouter(prefix="/admin", tags=["admin"])
COST_ADMIN_EMAIL = "admin@qtxpert.com"


def _as_float(value) -> float:
    return float(value or 0)


def _is_cost_admin_email(email: str | None) -> bool:
    return (email or "").strip().lower() == COST_ADMIN_EMAIL


async def require_cost_admin(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> User:
    """Cost information is intentionally restricted to the QTXpert owner account."""
    if not _is_cost_admin_email(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cost Center is restricted to the QTXpert owner account.",
        )
    return user


def _external_service_url(value: str | None) -> bool:
    text = (value or "").lower()
    return bool(text) and not any(token in text for token in ("localhost", "127.0.0.1", "@postgres:", "@redis:"))


def _provider_estimates(model_rows) -> dict[str, dict[str, float | int]]:
    providers: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"requests": 0, "estimated_cost_usd": 0.0, "unpriced": 0}
    )
    for row in model_rows:
        key = str(row.provider or "unknown").lower()
        providers[key]["requests"] += int(row.request_count or 0)
        providers[key]["estimated_cost_usd"] += _as_float(row.estimated_cost_usd)
        providers[key]["unpriced"] += int(row.unpriced_requests or 0)
    return dict(providers)


def _build_cost_surfaces(settings: Settings, model_rows, azure_snapshot) -> list[CostSurface]:
    """Describe every known QTXpert billing surface without inventing zero-cost values."""
    providers = _provider_estimates(model_rows)

    def provider_surface(
        key: str,
        service: str,
        configured: bool,
        billing_source: str,
        action: str,
    ) -> CostSurface:
        usage = providers.get(key, {})
        requests = int(usage.get("requests", 0) or 0)
        estimated = float(usage.get("estimated_cost_usd", 0.0) or 0.0)
        unpriced = int(usage.get("unpriced", 0) or 0)
        if requests:
            coverage = "estimated"
            estimate_value = estimated
            note = f"QTXpert metered {requests} request(s). Actual provider invoice is not connected."
            if unpriced:
                note += f" {unpriced} request(s) have no configured token rate."
        elif configured:
            coverage = "manual"
            estimate_value = None
            note = "Provider is configured, but QTXpert has no direct billing feed and no metered usage in this period."
        else:
            coverage = "not_configured"
            estimate_value = None
            note = "Provider is not currently configured. No cost should be assumed from this service."
        return CostSurface(
            key=key,
            category="AI / LLM",
            service=service,
            configured=configured,
            coverage=coverage,
            estimated_cost_usd=estimate_value,
            billing_source=billing_source,
            note=note,
            action=action,
        )

    azure_usage = providers.get("azure_openai", providers.get("azure", {}))
    azure_requests = int(azure_usage.get("requests", 0) or 0)
    azure_estimate = float(azure_usage.get("estimated_cost_usd", 0.0) or 0.0)
    azure_configured = bool(settings.AZURE_OPENAI_API_KEY and settings.AZURE_ENDPOINT)
    if azure_snapshot.connected and azure_snapshot.actual_cost is not None:
        azure_surface = CostSurface(
            key="azure_openai",
            category="AI / LLM",
            service="Azure OpenAI",
            configured=azure_configured,
            coverage="actual",
            actual_cost=azure_snapshot.actual_cost,
            estimated_cost_usd=azure_estimate if azure_requests else None,
            currency=azure_snapshot.currency or "USD",
            billing_source="Azure Cost Management + QTXpert token meter",
            note="Actual Azure billed cost is connected. QTXpert estimate remains available for reconciliation.",
            action=None,
        )
    elif azure_configured or azure_requests:
        azure_surface = CostSurface(
            key="azure_openai",
            category="AI / LLM",
            service="Azure OpenAI",
            configured=azure_configured,
            coverage="estimated" if azure_requests else "manual",
            estimated_cost_usd=azure_estimate if azure_requests else None,
            billing_source="QTXpert token meter; Azure actual billing unavailable",
            note="Azure OpenAI can incur cost, but the actual Azure Cost Management feed is not currently available.",
            action="Configure/repair Azure Cost Management credentials to reconcile the provider invoice.",
        )
    else:
        azure_surface = CostSurface(
            key="azure_openai",
            category="AI / LLM",
            service="Azure OpenAI",
            configured=False,
            coverage="not_configured",
            billing_source="Azure Cost Management",
            note="Azure OpenAI is not configured in this environment.",
            action=None,
        )

    postgres_external = _external_service_url(settings.POSTGRES_URL)
    redis_external = _external_service_url(settings.REDIS_URL)
    surfaces = [
        azure_surface,
        provider_surface("gemini", "Google Gemini API", bool(settings.GOOGLE_API_KEY), "QTXpert token estimate; Google invoice not connected", "Add Google Cloud billing export/API reconciliation if actual spend is required."),
        provider_surface("openai", "OpenAI API", bool(settings.OPENAI_API_KEY), "QTXpert token estimate; OpenAI invoice not connected", "Add provider billing reconciliation when an API is available for the account."),
        provider_surface("anthropic", "Anthropic API", bool(settings.ANTHROPIC_API_KEY), "QTXpert token estimate; Anthropic invoice not connected", "Reconcile against the Anthropic billing portal/invoice."),
        provider_surface("bedrock", "AWS Bedrock", bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY), "QTXpert token estimate; AWS Cost Explorer not connected", "Connect AWS Cost Explorer/Cost and Usage Reports for actual Bedrock spend."),
        CostSurface(
            key="render_backend",
            category="Hosting",
            service="Render · Backend Web Service",
            configured=True,
            coverage="manual",
            billing_source="Render invoice / dashboard",
            note="Runtime hosting can incur fixed plan and usage charges. QTXpert does not currently ingest Render billing.",
            action="Reconcile monthly against the Render invoice or add a Render billing feed when available.",
        ),
        CostSurface(
            key="render_frontend",
            category="Hosting",
            service="Render · Frontend Web Service",
            configured=True,
            coverage="manual",
            billing_source="Render invoice / dashboard",
            note="Frontend hosting is a separate billing surface and is not included in the AI cost meter.",
            action="Reconcile monthly against the Render invoice.",
        ),
        CostSurface(
            key="postgresql",
            category="Data",
            service="PostgreSQL Database",
            configured=postgres_external,
            coverage="manual" if postgres_external else "not_configured",
            billing_source="Database/Render invoice",
            note="Persistent database compute/storage/backup charges are not metered by QTXpert." if postgres_external else "No external PostgreSQL billing surface detected from the configured URL.",
            action="Track database plan, storage growth and backup charges in the hosting invoice." if postgres_external else None,
        ),
        CostSurface(
            key="redis_worker",
            category="Data / Workers",
            service="Redis / Background Worker Infrastructure",
            configured=redis_external,
            coverage="manual" if redis_external else "not_configured",
            billing_source="Infrastructure provider invoice",
            note="Queue/cache infrastructure is not connected to a billing feed." if redis_external else "No external Redis service is currently detected.",
            action="Add the Redis/worker provider invoice if a managed queue is enabled." if redis_external else None,
        ),
        CostSurface(
            key="browserstack",
            category="Device Cloud",
            service="BrowserStack App Automate",
            configured=settings.browserstack_configured,
            coverage="manual" if settings.browserstack_configured else "not_configured",
            billing_source="BrowserStack subscription / usage invoice",
            note="Real-device Autopilot sessions can consume paid BrowserStack capacity; QTXpert has no billing connector.",
            action="Track plan, parallel sessions and overages from BrowserStack billing." if settings.browserstack_configured else None,
        ),
        CostSurface(
            key="pinecone",
            category="Data / AI",
            service="Pinecone Vector Database",
            configured=settings.VECTOR_DB_PROVIDER == "pinecone" and bool(settings.PINECONE_API_KEY),
            coverage="manual" if settings.VECTOR_DB_PROVIDER == "pinecone" and bool(settings.PINECONE_API_KEY) else "not_configured",
            billing_source="Pinecone billing portal",
            note="Vector storage/query usage is not included in QTXpert's LLM meter." if settings.VECTOR_DB_PROVIDER == "pinecone" else "Pinecone is currently disabled.",
            action="Reconcile Pinecone storage/read/write usage when enabled." if settings.VECTOR_DB_PROVIDER == "pinecone" else None,
        ),
        CostSurface(
            key="github",
            category="Engineering",
            service="GitHub / GitHub Actions",
            configured=True,
            coverage="manual",
            billing_source="GitHub plan and Actions billing",
            note="Repository seats, Actions minutes/storage and future paid runners are not ingested by QTXpert.",
            action="Review GitHub billing monthly, especially Actions minutes and artifact storage.",
        ),
        CostSurface(
            key="domain_dns",
            category="Platform",
            service="Domain Registration & DNS",
            configured=True,
            coverage="manual",
            billing_source="Registrar / DNS provider invoice",
            note="Domain renewal, premium DNS or optional CDN/security charges are outside application metering.",
            action="Track annual domain renewal and any paid DNS/CDN plan separately.",
        ),
        CostSurface(
            key="upload_storage",
            category="Storage",
            service="Upload & Test Evidence Storage",
            configured=True,
            coverage="manual",
            billing_source="Current hosting/storage invoice",
            note="APK, documents, screenshots, XML and future video evidence can drive storage and egress cost. There is no separate storage billing feed today.",
            action="When object storage is introduced, add storage, request and egress reconciliation to this Cost Center.",
        ),
    ]
    return surfaces


@router.get("/ai-costs", response_model=AICostSummary)
async def get_ai_costs(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[User, Depends(require_cost_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AICostSummary:
    """Return AI metering, actual Azure spend and the wider ecosystem cost coverage map."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_cost = func.coalesce(func.sum(LLMUsageEvent.estimated_cost_usd), 0).label("estimated_cost_usd")
    totals_result = await db.execute(
        select(
            func.count(LLMUsageEvent.id).label("request_count"),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0).label("output_tokens"),
            total_cost,
            func.count(LLMUsageEvent.id).filter(LLMUsageEvent.estimated_cost_usd.is_(None)).label("unpriced_requests"),
        ).where(LLMUsageEvent.created_at >= since)
    )
    totals = totals_result.one()

    model_cost = func.coalesce(func.sum(LLMUsageEvent.estimated_cost_usd), 0).label("estimated_cost_usd")
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
                func.count(LLMUsageEvent.id).filter(LLMUsageEvent.estimated_cost_usd.is_(None)).label("unpriced_requests"),
            )
            .where(LLMUsageEvent.created_at >= since)
            .group_by(LLMUsageEvent.provider, LLMUsageEvent.model, LLMUsageEvent.tier)
            .order_by(model_cost.desc(), LLMUsageEvent.provider, LLMUsageEvent.model)
        )
    ).all()

    estimated_cost = _as_float(totals.estimated_cost_usd)
    azure_snapshot = await AzureCostService(settings).query(days)
    variance_usd = None
    if azure_snapshot.connected and azure_snapshot.actual_cost is not None and (azure_snapshot.currency or "").upper() == "USD":
        variance_usd = azure_snapshot.actual_cost - estimated_cost

    surfaces = _build_cost_surfaces(settings, model_rows, azure_snapshot)
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
        cost_surfaces=surfaces,
        untracked_surface_count=sum(surface.coverage == "manual" for surface in surfaces),
    )
