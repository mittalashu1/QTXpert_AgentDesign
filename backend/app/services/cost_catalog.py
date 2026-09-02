"""Cost Center metadata, provider probes and monthly refresh persistence.

The Cost Center intentionally separates three things:

* documented portal/pricing/limit metadata (versioned in this module),
* QTXpert's own token-metered estimates, and
* optional account-specific usage returned by provider APIs.

Only the last item is refreshed.  Credentials never enter a snapshot or an
API response.  If a provider is not configured, users still get an actionable
portal link and the published service limits instead of a misleading zero.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models.cost_center import CostCenterSnapshot

logger = logging.getLogger(__name__)

COST_CATALOG_SCOPE = "workspace"
# Bump this value whenever a documented limit/link is reviewed in source.
COST_CATALOG_VERSION = "2026-08-30"
CATALOG_VERIFIED_AT = datetime(2026, 8, 30, tzinfo=timezone.utc)


# These are links users can open to verify billing and account limits.  They
# are deliberately public documentation/portal URLs; no account identifiers
# or credentials are embedded in the application.
STATIC_COST_CATALOG: dict[str, dict[str, Any]] = {
    "azure_openai": {
        "portal_url": "https://portal.azure.com/",
        "pricing_url": "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/",
        "limits": ["Quota and rate limits are deployment- and region-specific; verify the Azure quota blade."],
    },
    "gemini": {
        "portal_url": "https://console.cloud.google.com/billing",
        "pricing_url": "https://ai.google.dev/gemini-api/docs/pricing",
        "limits": ["Free quota, paid quota and rate limits vary by model and Google project."],
    },
    "openai": {
        "portal_url": "https://platform.openai.com/usage",
        "pricing_url": "https://openai.com/api/pricing/",
        "limits": ["Usage, spend limits and rate limits are account- and model-specific."],
    },
    "anthropic": {
        "portal_url": "https://console.anthropic.com/",
        "pricing_url": "https://www.anthropic.com/pricing",
        "limits": ["Usage and spend limits depend on the Anthropic account and selected model."],
    },
    "bedrock": {
        "portal_url": "https://console.aws.amazon.com/bedrock/",
        "pricing_url": "https://aws.amazon.com/bedrock/pricing/",
        "limits": ["Model quotas and regional throughput are account-specific; check AWS Service Quotas."],
    },
    "render_backend": {
        "portal_url": "https://dashboard.render.com/",
        "pricing_url": "https://render.com/pricing",
        "limits": ["Starter (configured): 0.5 CPU / 512 MB; confirm the service plan in Render."],
    },
    "render_frontend": {
        "portal_url": "https://dashboard.render.com/",
        "pricing_url": "https://render.com/pricing",
        "limits": ["Free: spins down after 15 minutes idle, 750 instance-hours/month and ephemeral filesystem."],
    },
    "neon_postgresql": {
        "portal_url": "https://console.neon.tech/",
        "pricing_url": "https://neon.com/pricing",
        "limits": [
            "Launch reference: up to 16 CU, 10 branches/project included and 7-day restore; verify the account plan.",
            "$0.106/CU-hour and $0.35/GB-month are usage-based Launch reference rates; confirm current pricing in Neon.",
        ],
    },
    "redis_worker": {
        "portal_url": "https://dashboard.render.com/",
        "pricing_url": "https://render.com/pricing",
        "limits": ["Capacity, persistence and retention depend on the selected managed Redis/worker plan."],
    },
    "cloudflare_r2": {
        "portal_url": "https://dash.cloudflare.com/",
        "pricing_url": "https://developers.cloudflare.com/r2/pricing/",
        "limits_url": "https://developers.cloudflare.com/r2/platform/limits/",
        "limits": [
            "Standard reference rates: $0.015/GB-month storage, $4.50/million Class A and $0.36/million Class B requests; egress is free.",
            "Standard free tier: 10 GB-month storage, 1M Class A and 10M Class B requests/month; egress is free.",
            "5 TiB/object; 5 GiB single-part upload or 4.995 TiB multipart; 10,000 multipart parts.",
        ],
    },
    "browserstack": {
        "portal_url": "https://app-automate.browserstack.com/",
        "pricing_url": "https://www.browserstack.com/pricing",
        "limits_url": "https://www.browserstack.com/docs/app-automate/api-reference/appium/plan",
        "limits": ["Parallel-session and queue limits are returned live from the App Automate plan API when connected."],
    },
    "pinecone": {
        "portal_url": "https://app.pinecone.io/",
        "pricing_url": "https://www.pinecone.io/pricing/",
        "limits": ["Storage, read/write units and index limits vary by Pinecone plan and region."],
    },
    "jira": {
        "portal_url": "https://admin.atlassian.com/",
        "pricing_url": "https://www.atlassian.com/software/jira/pricing",
        "limits": ["Seats, automation executions and storage allowances depend on the Jira plan."],
    },
    "confluence": {
        "portal_url": "https://admin.atlassian.com/",
        "pricing_url": "https://www.atlassian.com/software/confluence/pricing",
        "limits": ["Seats, storage and automation allowances depend on the Confluence plan."],
    },
    "github": {
        "portal_url": "https://github.com/settings/billing",
        "pricing_url": "https://github.com/pricing",
        "limits_url": "https://docs.github.com/en/billing/reference/product-usage-included",
        "limits": ["Free reference: 2,000 Actions minutes and 500 MB Actions storage/month; plan overages may apply."],
    },
    "domain_dns": {
        "portal_url": "https://dash.cloudflare.com/",
        "pricing_url": "https://www.cloudflare.com/plans/",
        "limits": ["Renewal, DNS and optional security/CDN charges depend on the registrar and DNS plan."],
    },
}


@dataclass(frozen=True)
class CostCatalogSnapshotView:
    """Safe, serializable view of persisted refresh state."""

    status: str = "unavailable"
    refreshed_at: datetime | None = None
    next_refresh_at: datetime | None = None
    error: str | None = None
    providers: dict[str, dict[str, Any]] | None = None


def _normalise_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _normalise_datetime(value)
    if not isinstance(value, str):
        return None
    try:
        return _normalise_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _snapshot_from_record(record: CostCenterSnapshot | None, settings: Settings) -> CostCatalogSnapshotView:
    if record is None:
        now = datetime.now(timezone.utc)
        return CostCatalogSnapshotView(
            status="due",
            next_refresh_at=now,
            providers={},
        )
    refreshed_at = _normalise_datetime(record.refreshed_at)
    next_refresh = (
        refreshed_at + timedelta(days=settings.COST_CENTER_REFRESH_DAYS)
        if refreshed_at
        else datetime.now(timezone.utc)
    )
    payload = record.payload if isinstance(record.payload, dict) else {}
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    return CostCatalogSnapshotView(
        status=str(record.status or "unavailable"),
        refreshed_at=refreshed_at,
        next_refresh_at=next_refresh,
        error=record.error,
        providers=providers,
    )


def surface_metadata(
    key: str,
    settings: Settings,
    snapshot: CostCatalogSnapshotView | None = None,
) -> dict[str, Any]:
    """Return links, documented limits and safe live values for a surface."""
    # Keep the legacy API key ``postgresql`` stable while exposing Neon in the
    # user-facing service name and metadata. Upload storage follows the actual
    # selected backend: R2 links for object storage, Neon links for the legacy
    # PostgreSQL-chunk fallback. This avoids claiming an R2 bill in local/dev
    # environments that have not enabled object storage.
    if key == "upload_storage":
        metadata_key = "cloudflare_r2" if settings.UPLOAD_STORAGE_BACKEND == "object_store" else "neon_postgresql"
    else:
        metadata_key = {"postgresql": "neon_postgresql"}.get(key, key)
    base = STATIC_COST_CATALOG.get(metadata_key, {})
    metadata: dict[str, Any] = {
        "portal_url": base.get("portal_url"),
        "pricing_url": base.get("pricing_url"),
        "limits_url": base.get("limits_url"),
        "limits": list(base.get("limits") or []),
        "account_plan": None,
        "live_usage": None,
        "last_verified_at": CATALOG_VERIFIED_AT,
        "provider_error": None,
    }
    if metadata_key == "render_backend":
        metadata["account_plan"] = settings.RENDER_BACKEND_PLAN
    elif metadata_key == "render_frontend":
        metadata["account_plan"] = settings.RENDER_FRONTEND_PLAN
    elif metadata_key == "neon_postgresql":
        metadata["account_plan"] = settings.NEON_PLAN or "Configured plan not supplied"
    elif metadata_key == "cloudflare_r2" and settings.OBJECT_STORAGE_BUCKET:
        metadata["account_plan"] = f"Bucket: {settings.OBJECT_STORAGE_BUCKET}"
    elif metadata_key == "jira" and settings.JIRA_URL:
        metadata["portal_url"] = settings.JIRA_URL.rstrip("/")
    elif metadata_key == "confluence" and settings.CONFLUENCE_URL:
        metadata["portal_url"] = settings.CONFLUENCE_URL.rstrip("/")

    live = ((snapshot.providers if snapshot else {}) or {}).get(metadata_key)
    if isinstance(live, dict):
        if live.get("account_plan"):
            metadata["account_plan"] = str(live["account_plan"])
        usage = live.get("live_usage")
        if isinstance(usage, dict) and usage:
            metadata["live_usage"] = usage
        metadata["provider_error"] = live.get("error")
        verified = _parse_datetime(live.get("last_verified_at"))
        if verified:
            metadata["last_verified_at"] = verified
    return metadata


def _metric_from_r2_class(result: dict[str, Any], storage_class: str) -> dict[str, int]:
    node = result.get(storage_class) if isinstance(result, dict) else None
    if not isinstance(node, dict):
        return {"objects": 0, "payload_bytes": 0, "metadata_bytes": 0}
    # Published objects represent stored data.  Fall back to uploaded when an
    # account has no published branch in the response.
    metric = node.get("published")
    if not isinstance(metric, dict):
        metric = node.get("uploaded")
    metric = metric if isinstance(metric, dict) else {}
    return {
        "objects": int(metric.get("objects") or 0),
        "payload_bytes": int(metric.get("payloadSize") or 0),
        "metadata_bytes": int(metric.get("metadataSize") or 0),
    }


def _merge_provider_snapshots(
    previous: dict[str, Any],
    current: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge a refresh while retaining last-known values for failed probes."""
    merged = {
        key: dict(value)
        for key, value in previous.items()
        if isinstance(value, dict)
    }
    for provider_key, provider_value in current.items():
        if provider_value.get("error") and isinstance(merged.get(provider_key), dict):
            merged[provider_key] = {
                **merged[provider_key],
                "error": provider_value["error"],
            }
        else:
            merged[provider_key] = provider_value
    return merged


async def _probe_browserstack(settings: Settings, client: httpx.AsyncClient) -> dict[str, Any] | None:
    if not settings.browserstack_configured:
        return None
    try:
        response = await client.get(
            "https://api-cloud.browserstack.com/app-automate/plan.json",
            auth=(settings.BROWSERSTACK_USERNAME or "", settings.BROWSERSTACK_ACCESS_KEY or ""),
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        live_usage: dict[str, Any] = {
            "parallel_running": int(body.get("parallel_sessions_running") or 0),
            "parallel_max": int(body.get("parallel_sessions_max_allowed") or 0),
            "queued": int(body.get("queued_sessions") or 0),
            "queue_max": int(body.get("queued_sessions_max_allowed") or 0),
        }
        if body.get("team_parallel_sessions_max_allowed") is not None:
            live_usage["team_parallel_max"] = int(body["team_parallel_sessions_max_allowed"])
        return {
            "account_plan": body.get("automate_plan") or "App Automate",
            "live_usage": live_usage,
        }
    except httpx.HTTPStatusError as exc:
        return {"error": f"BrowserStack plan API rejected the request (HTTP {exc.response.status_code})."}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": f"BrowserStack plan API unavailable ({type(exc).__name__})."}


async def _probe_cloudflare_r2(settings: Settings, client: httpx.AsyncClient) -> dict[str, Any] | None:
    if not (settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID):
        return None
    try:
        response = await client.get(
            f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/r2/metrics",
            headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"},
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        if body.get("success") is False:
            raise ValueError("Cloudflare returned success=false")
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        standard = _metric_from_r2_class(result, "standard")
        infrequent = _metric_from_r2_class(result, "infrequentAccess")
        return {
            "live_usage": {
                "objects": standard["objects"] + infrequent["objects"],
                "payload_bytes": standard["payload_bytes"] + infrequent["payload_bytes"],
                "metadata_bytes": standard["metadata_bytes"] + infrequent["metadata_bytes"],
            }
        }
    except httpx.HTTPStatusError as exc:
        return {"error": f"Cloudflare R2 metrics API rejected the request (HTTP {exc.response.status_code})."}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": f"Cloudflare R2 metrics unavailable ({type(exc).__name__})."}


async def _probe_neon(settings: Settings, client: httpx.AsyncClient) -> dict[str, Any] | None:
    if not (settings.NEON_API_KEY and settings.NEON_ORG_ID):
        return None
    try:
        response = await client.get(
            f"https://console.neon.tech/api/v2/organizations/{settings.NEON_ORG_ID}/billing/spending_limit",
            headers={"Authorization": f"Bearer {settings.NEON_API_KEY}"},
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        cents = body.get("spending_limit_cents")
        usage: dict[str, Any] = {
            "spending_limit_usd": (float(cents) / 100) if cents is not None else None,
            "spending_limit_configured": cents is not None,
        }
        return {"account_plan": settings.NEON_PLAN, "live_usage": usage}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Neon billing API rejected the request (HTTP {exc.response.status_code})."}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": f"Neon billing API unavailable ({type(exc).__name__})."}


async def _probe_provider_catalog(settings: Settings) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Run configured probes concurrently within one bounded timeout."""
    probes = {
        "browserstack": _probe_browserstack,
        "cloudflare_r2": _probe_cloudflare_r2,
        "neon_postgresql": _probe_neon,
    }
    configured = {
        "browserstack": settings.browserstack_configured,
        "cloudflare_r2": bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID),
        "neon_postgresql": bool(settings.NEON_API_KEY and settings.NEON_ORG_ID),
    }
    active = [(key, probes[key]) for key, enabled in configured.items() if enabled]
    if not active:
        return {}, []
    timeout = httpx.Timeout(settings.COST_CENTER_REFRESH_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            *(probe(settings, client) for _, probe in active),
            return_exceptions=True,
        )
    providers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    for (key, _), result in zip(active, results):
        if isinstance(result, Exception):
            providers[key] = {"error": f"Provider probe failed ({type(result).__name__})."}
            errors.append(f"{key}: probe failed ({type(result).__name__})")
            continue
        item = dict(result or {})
        item["last_verified_at"] = now
        providers[key] = item
        if item.get("error"):
            errors.append(f"{key}: {item['error']}")
    return providers, errors


async def _load_record(db: AsyncSession) -> CostCenterSnapshot | None:
    result = await db.execute(
        select(CostCenterSnapshot).where(CostCenterSnapshot.scope == COST_CATALOG_SCOPE)
    )
    return result.scalar_one_or_none()


async def _safe_rollback(db: AsyncSession) -> None:
    """Rollback without masking the original database/provider failure."""
    try:
        await db.rollback()
    except Exception as rollback_error:  # pragma: no cover - driver dependent
        logger.debug("Cost Center rollback failed: %s", type(rollback_error).__name__)


async def refresh_cost_catalog(
    db: AsyncSession,
    settings: Settings,
    *,
    force: bool = False,
) -> CostCatalogSnapshotView:
    """Refresh configured providers and persist non-sensitive results."""
    now = datetime.now(timezone.utc)
    existing: CostCenterSnapshot | None = None
    try:
        if not force:
            existing = await _load_record(db)
            existing_view = _snapshot_from_record(existing, settings)
            if existing and existing_view.next_refresh_at and existing_view.next_refresh_at > now:
                return existing_view

        providers, errors = await _probe_provider_catalog(settings)
        status = "partial" if errors else "fresh"
        error = "; ".join(errors) if errors else None
        record = existing or await _load_record(db)

        # Preserve a provider's last known account values when its connector
        # has a transient failure.  The current error is surfaced alongside
        # those stale values so the UI never turns an outage into a misleading
        # blank or zero. Successful probes replace the old provider snapshot.
        previous_payload = record.payload if record and isinstance(record.payload, dict) else {}
        previous_providers = previous_payload.get("providers") if isinstance(previous_payload.get("providers"), dict) else {}
        merged_providers = _merge_provider_snapshots(previous_providers, providers)

        payload = {"catalog_version": COST_CATALOG_VERSION, "providers": merged_providers}
        if record is None:
            record = CostCenterSnapshot(
                scope=COST_CATALOG_SCOPE,
                status=status,
                payload=payload,
                refreshed_at=now,
                error=error,
            )
            db.add(record)
        else:
            record.status = status
            record.payload = payload
            record.refreshed_at = now
            record.error = error
        try:
            await db.commit()
        except IntegrityError:
            # Two admins can open Cost Center at the same time on a cold
            # deployment.  Retry as an update after the unique scope race.
            await _safe_rollback(db)
            record = await _load_record(db)
            if record is None:
                raise
            record.status = status
            record.payload = payload
            record.refreshed_at = now
            record.error = error
            await db.commit()
        return CostCatalogSnapshotView(
            status=status,
            refreshed_at=now,
            next_refresh_at=now + timedelta(days=settings.COST_CENTER_REFRESH_DAYS),
            error=error,
            providers=merged_providers,
        )
    except Exception as exc:  # pragma: no cover - provider/database dependent
        await _safe_rollback(db)
        logger.warning("Cost Center catalog refresh unavailable: %s", type(exc).__name__)
        return CostCatalogSnapshotView(
            status="unavailable",
            refreshed_at=None,
            next_refresh_at=now + timedelta(days=settings.COST_CENTER_REFRESH_DAYS),
            error=f"Catalog refresh unavailable ({type(exc).__name__}).",
            providers={},
        )


async def refresh_cost_catalog_if_due(
    db: AsyncSession,
    settings: Settings,
) -> CostCatalogSnapshotView:
    """Load a snapshot and refresh it at most once per configured period."""
    try:
        record = await _load_record(db)
    except Exception as exc:  # pragma: no cover - provider/database dependent
        await _safe_rollback(db)
        logger.warning("Cost Center catalog snapshot unavailable: %s", type(exc).__name__)
        return CostCatalogSnapshotView(
            status="unavailable",
            next_refresh_at=datetime.now(timezone.utc),
            error=f"Catalog snapshot unavailable ({type(exc).__name__}).",
            providers={},
        )
    view = _snapshot_from_record(record, settings)
    if settings.COST_CENTER_AUTO_REFRESH_ENABLED and (
        record is None or view.next_refresh_at is None or view.next_refresh_at <= datetime.now(timezone.utc)
    ):
        return await refresh_cost_catalog(db, settings, force=True)
    return view
