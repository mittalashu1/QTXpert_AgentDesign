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
from app.llm.metering import load_cost_rates
from app.schemas.usage import (
    AICostBreakdown,
    AICostSummary,
    AzureActualCost,
    CostCatalogInfo,
    CostSurface,
)
from app.services.azure_cost_service import AzureCostService
from app.services.cost_catalog import (
    CostCatalogSnapshotView,
    refresh_cost_catalog,
    refresh_cost_catalog_if_due,
    surface_metadata,
)

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


def _provider_estimates(
    model_rows,
    rates: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict[str, float | int]]:
    providers: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"requests": 0, "estimated_cost_usd": 0.0, "unpriced": 0}
    )
    for row in model_rows:
        key = str(row.provider or "unknown").lower()
        estimated_cost, unpriced = _reprice_usage_row(row, rates or {})
        providers[key]["requests"] += int(row.request_count or 0)
        providers[key]["estimated_cost_usd"] += estimated_cost
        providers[key]["unpriced"] += unpriced
    return dict(providers)


def _reprice_usage_row(row, rates: dict[str, dict[str, float]]) -> tuple[float, int]:
    """Re-price legacy NULL estimates when an explicit model rate is known."""
    persisted_cost = _as_float(row.estimated_cost_usd)
    unpriced_requests = int(row.unpriced_requests or 0)
    rate = rates.get(f"{str(row.provider or '').lower()}:{row.model}")
    if not rate or not unpriced_requests:
        return persisted_cost, unpriced_requests
    input_tokens = int(getattr(row, "unpriced_input_tokens", 0) or 0)
    output_tokens = int(getattr(row, "unpriced_output_tokens", 0) or 0)
    repriced = (
        input_tokens * float(rate.get("input", 0) or 0)
        + output_tokens * float(rate.get("output", 0) or 0)
    ) / 1_000_000
    return persisted_cost + repriced, 0


def _build_cost_surfaces(
    settings: Settings,
    model_rows,
    azure_snapshot,
    catalog_snapshot: CostCatalogSnapshotView | None = None,
    rates: dict[str, dict[str, float]] | None = None,
) -> list[CostSurface]:
    """Describe every known QTXpert billing surface without inventing zero-cost values."""
    providers = _provider_estimates(model_rows, rates or load_cost_rates(settings))

    def surface(**values) -> CostSurface:
        """Build a row and enrich it with safe portal/limit metadata."""
        key = str(values.get("key") or "")
        values.update(surface_metadata(key, settings, catalog_snapshot))
        return CostSurface(**values)

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
        return surface(
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
        azure_surface = surface(
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
        azure_surface = surface(
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
        azure_surface = surface(
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
    jira_configured = bool(settings.JIRA_URL)
    confluence_configured = bool(settings.CONFLUENCE_URL)
    r2_configured = settings.object_storage_configured or bool(
        settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID
    )
    surfaces = [
        azure_surface,
        provider_surface("gemini", "Google Gemini API", bool(settings.GOOGLE_API_KEY), "QTXpert token estimate; Google invoice not connected", "Add Google Cloud billing export/API reconciliation if actual spend is required."),
        provider_surface("openai", "OpenAI API", bool(settings.OPENAI_API_KEY), "QTXpert token estimate; OpenAI invoice not connected", "Add provider billing reconciliation when an API is available for the account."),
        provider_surface("anthropic", "Anthropic API", bool(settings.ANTHROPIC_API_KEY), "QTXpert token estimate; Anthropic invoice not connected", "Reconcile against the Anthropic billing portal/invoice."),
        provider_surface("bedrock", "AWS Bedrock", bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY), "QTXpert token estimate; AWS Cost Explorer not connected", "Connect AWS Cost Explorer/Cost and Usage Reports for actual Bedrock spend."),
        surface(
            key="render_backend",
            category="Hosting",
            service="Render · Backend Web Service",
            configured=True,
            coverage="manual",
            billing_source="Render invoice / dashboard",
            note="Runtime hosting can incur fixed plan and usage charges. QTXpert does not currently ingest the Render invoice.",
            action="Open the Render billing portal to reconcile the service plan and monthly usage.",
        ),
        surface(
            key="render_frontend",
            category="Hosting",
            service="Render · Frontend Web Service",
            configured=True,
            coverage="manual",
            billing_source="Render invoice / dashboard",
            note="Frontend hosting is a separate billing surface and is not included in the AI cost meter.",
            action="Open the Render billing portal to reconcile the frontend plan and usage.",
        ),
        surface(
            key="postgresql",
            category="Data",
            service="Neon Postgres Database",
            configured=postgres_external,
            coverage="manual" if postgres_external else "not_configured",
            billing_source="Neon billing portal / invoice",
            note="Persistent database compute/storage/backup charges are not metered by QTXpert." if postgres_external else "No external PostgreSQL billing surface detected from the configured URL.",
            action="Confirm the Neon plan, spending limit and storage growth in the billing portal." if postgres_external else None,
        ),
        surface(
            key="redis_worker",
            category="Data / Workers",
            service="Redis / Background Worker Infrastructure",
            configured=redis_external,
            coverage="manual" if redis_external else "not_configured",
            billing_source="Infrastructure provider invoice",
            note="Queue/cache infrastructure is not connected to a billing feed." if redis_external else "No external Redis service is currently detected.",
            action="Add the Redis/worker provider invoice if a managed queue is enabled." if redis_external else None,
        ),
        surface(
            key="browserstack",
            category="Device Cloud",
            service="BrowserStack App Automate",
            configured=settings.browserstack_configured,
            coverage="manual" if settings.browserstack_configured else "not_configured",
            billing_source="BrowserStack subscription / usage invoice",
            note="Real-device Autopilot sessions can consume paid BrowserStack capacity; plan capacity is refreshed when credentials are configured.",
            action="Review parallel capacity and subscription usage in BrowserStack." if settings.browserstack_configured else None,
        ),
        surface(
            key="pinecone",
            category="Data / AI",
            service="Pinecone Vector Database",
            configured=settings.VECTOR_DB_PROVIDER == "pinecone" and bool(settings.PINECONE_API_KEY),
            coverage="manual" if settings.VECTOR_DB_PROVIDER == "pinecone" and bool(settings.PINECONE_API_KEY) else "not_configured",
            billing_source="Pinecone billing portal",
            note="Vector storage/query usage is not included in QTXpert's LLM meter." if settings.VECTOR_DB_PROVIDER == "pinecone" else "Pinecone is currently disabled.",
            action="Reconcile Pinecone storage/read/write usage when enabled." if settings.VECTOR_DB_PROVIDER == "pinecone" else None,
        ),
        surface(
            key="github",
            category="Engineering",
            service="GitHub / GitHub Actions",
            configured=True,
            coverage="manual",
            billing_source="GitHub plan and Actions billing",
            note="Repository seats, Actions minutes/storage and future paid runners are not ingested by QTXpert.",
            action="Review GitHub billing monthly, especially Actions minutes and artifact storage.",
        ),
        surface(
            key="domain_dns",
            category="Platform",
            service="Domain Registration & DNS",
            configured=True,
            coverage="manual",
            billing_source="Registrar / DNS provider invoice",
            note="Domain renewal, premium DNS or optional CDN/security charges are outside application metering.",
            action="Track annual domain renewal and any paid DNS/CDN plan separately.",
        ),
        surface(
            key="jira",
            category="Integrations",
            service="Jira",
            configured=jira_configured,
            coverage="manual" if jira_configured else "not_configured",
            billing_source="Atlassian billing portal / invoice",
            note="Jira is an optional integration; QTXpert does not ingest Atlassian billing or seat usage.",
            action="Review Jira seats, automation usage and plan limits in Atlassian administration." if jira_configured else None,
        ),
        surface(
            key="confluence",
            category="Integrations",
            service="Confluence",
            configured=confluence_configured,
            coverage="manual" if confluence_configured else "not_configured",
            billing_source="Atlassian billing portal / invoice",
            note="Confluence is an optional integration; QTXpert does not ingest Atlassian billing or storage usage.",
            action="Review Confluence seats, storage and plan limits in Atlassian administration." if confluence_configured else None,
        ),
        surface(
            key="upload_storage",
            category="Storage",
            service="Upload & Test Evidence Storage",
            # QTXpert always has an application storage backend (R2 in
            # production, PostgreSQL chunks during local migration).  The
            # underlying provider is shown separately below.
            configured=True,
            coverage="manual",
            billing_source="Configured storage backend / provider invoice",
            note=f"APK, documents, screenshots, XML and future video evidence use the {settings.UPLOAD_STORAGE_BACKEND} backend.",
            action="Review the Cloudflare R2 row for provider limits and live object counts when object storage is enabled.",
        ),
        surface(
            key="cloudflare_r2",
            category="Storage",
            service="Cloudflare R2 Object Storage",
            configured=r2_configured,
            coverage="manual" if r2_configured else "not_configured",
            billing_source="Cloudflare R2 billing portal / metrics API",
            note="Private R2 storage is the durable home for APKs, documents and execution evidence. Account metrics are refreshed when a scoped Cloudflare token is configured.",
            action="Review R2 billing and metrics; enable the optional Cloudflare connector for live object counts." if r2_configured else "Configure the private R2 bucket and scoped metrics token.",
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
    unpriced_input = func.coalesce(
        func.sum(LLMUsageEvent.input_tokens).filter(LLMUsageEvent.estimated_cost_usd.is_(None)),
        0,
    ).label("unpriced_input_tokens")
    unpriced_output = func.coalesce(
        func.sum(LLMUsageEvent.output_tokens).filter(LLMUsageEvent.estimated_cost_usd.is_(None)),
        0,
    ).label("unpriced_output_tokens")
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
                unpriced_input,
                unpriced_output,
            )
            .where(LLMUsageEvent.created_at >= since)
            .group_by(LLMUsageEvent.provider, LLMUsageEvent.model, LLMUsageEvent.tier)
            .order_by(model_cost.desc(), LLMUsageEvent.provider, LLMUsageEvent.model)
        )
    ).all()

    rates = load_cost_rates(settings)
    priced_rows: list[tuple[object, float, int]] = []
    for row in model_rows:
        row_cost, row_unpriced = _reprice_usage_row(row, rates)
        priced_rows.append((row, row_cost, row_unpriced))
    estimated_cost = sum(row_cost for _row, row_cost, _unpriced in priced_rows)
    unpriced_requests = sum(row_unpriced for _row, _row_cost, row_unpriced in priced_rows)
    azure_snapshot = await AzureCostService(settings).query(days)
    variance_usd = None
    if azure_snapshot.connected and azure_snapshot.actual_cost is not None and (azure_snapshot.currency or "").upper() == "USD":
        variance_usd = azure_snapshot.actual_cost - estimated_cost

    # Provider probes are cached in Neon and refreshed at most monthly.  A
    # missing connector never prevents the static catalog from rendering.
    catalog_snapshot = await refresh_cost_catalog_if_due(db, settings)
    surfaces = _build_cost_surfaces(settings, model_rows, azure_snapshot, catalog_snapshot, rates)
    return AICostSummary(
        period_days=days,
        since=since,
        request_count=int(totals.request_count or 0),
        input_tokens=int(totals.input_tokens or 0),
        output_tokens=int(totals.output_tokens or 0),
        estimated_cost_usd=estimated_cost,
        unpriced_requests=unpriced_requests,
        by_model=[
            AICostBreakdown(
                provider=row.provider,
                model=row.model,
                tier=row.tier,
                request_count=int(row.request_count or 0),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                estimated_cost_usd=row_cost,
                unpriced_requests=row_unpriced,
            )
            for row, row_cost, row_unpriced in priced_rows
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
        catalog=CostCatalogInfo(
            status=catalog_snapshot.status,
            last_refreshed_at=catalog_snapshot.refreshed_at,
            next_refresh_at=catalog_snapshot.next_refresh_at,
            error=catalog_snapshot.error,
        ),
    )


@router.post("/cost-catalog/refresh", response_model=CostCatalogInfo)
async def refresh_cost_catalog_endpoint(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[User, Depends(require_cost_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CostCatalogInfo:
    """Force a safe provider metadata refresh for the owner Cost Center."""
    snapshot = await refresh_cost_catalog(db, settings, force=True)
    return CostCatalogInfo(
        status=snapshot.status,
        last_refreshed_at=snapshot.refreshed_at,
        next_refresh_at=snapshot.next_refresh_at,
        error=snapshot.error,
    )

