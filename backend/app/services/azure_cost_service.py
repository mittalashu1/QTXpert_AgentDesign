"""Optional Azure Cost Management reconciliation for the admin dashboard.

This service is deliberately independent from Azure OpenAI request metering.
QTXpert's LLM meter estimates application-attributable token cost; Azure Cost
Management reports the billed/actual Azure resource cost, which can include
older usage, usage outside QTXpert, and billing adjustments.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from app.config import Settings


@dataclass(frozen=True)
class AzureCostSnapshot:
    configured: bool
    connected: bool
    actual_cost: float | None = None
    currency: str | None = None
    last_synced_at: datetime | None = None
    scope: str | None = None
    resource_name: str | None = None
    error: str | None = None


class AzureCostService:
    """Read actual Azure cost for the Azure OpenAI resource used by QTXpert."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def resource_name(self) -> str | None:
        if self._settings.AZURE_COST_RESOURCE_NAME:
            return self._settings.AZURE_COST_RESOURCE_NAME.strip()
        endpoint = (self._settings.AZURE_ENDPOINT or "").strip()
        if not endpoint:
            return None
        hostname = urlparse(endpoint).hostname or ""
        return hostname.split(".")[0] or None

    @property
    def configured(self) -> bool:
        return all(
            (
                self._settings.AZURE_COST_TENANT_ID,
                self._settings.AZURE_COST_CLIENT_ID,
                self._settings.AZURE_COST_CLIENT_SECRET,
                self._settings.AZURE_COST_SUBSCRIPTION_ID,
                self._settings.AZURE_COST_RESOURCE_GROUP,
                self.resource_name,
            )
        )

    @property
    def scope(self) -> str | None:
        if not self._settings.AZURE_COST_SUBSCRIPTION_ID or not self._settings.AZURE_COST_RESOURCE_GROUP:
            return None
        return (
            f"/subscriptions/{self._settings.AZURE_COST_SUBSCRIPTION_ID}"
            f"/resourceGroups/{self._settings.AZURE_COST_RESOURCE_GROUP}"
        )

    @property
    def target_resource_id(self) -> str | None:
        if not self.scope or not self.resource_name:
            return None
        return (
            f"{self.scope}/providers/Microsoft.CognitiveServices/accounts/"
            f"{self.resource_name}"
        )

    async def query(self, days: int = 30) -> AzureCostSnapshot:
        if not self.configured:
            return AzureCostSnapshot(
                configured=False,
                connected=False,
                scope=self.scope,
                resource_name=self.resource_name,
            )

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        try:
            async with httpx.AsyncClient(timeout=self._settings.AZURE_COST_TIMEOUT_SECONDS) as client:
                token = await self._get_token(client)
                payload = {
                    "type": "Usage",
                    "timeframe": "Custom",
                    "timePeriod": {
                        "from": since.isoformat().replace("+00:00", "Z"),
                        "to": now.isoformat().replace("+00:00", "Z"),
                    },
                    "dataset": {
                        "granularity": "None",
                        "aggregation": {
                            "totalCost": {"name": "PreTaxCost", "function": "Sum"}
                        },
                        "grouping": [{"type": "Dimension", "name": "ResourceId"}],
                    },
                }
                response = await client.post(
                    (
                        "https://management.azure.com"
                        f"{self.scope}/providers/Microsoft.CostManagement/query"
                    ),
                    params={"api-version": self._settings.AZURE_COST_API_VERSION},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json() if response.content else {}
                amount, currency = self._extract_resource_cost(body, self.target_resource_id or "")
                return AzureCostSnapshot(
                    configured=True,
                    connected=True,
                    actual_cost=amount,
                    currency=currency,
                    last_synced_at=now,
                    scope=self.scope,
                    resource_name=self.resource_name,
                )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = "Azure Cost Management request was rejected"
            if status in {401, 403}:
                detail = "Azure Cost Management credentials or permissions are insufficient"
            return AzureCostSnapshot(
                configured=True,
                connected=False,
                scope=self.scope,
                resource_name=self.resource_name,
                error=f"{detail} (HTTP {status})",
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return AzureCostSnapshot(
                configured=True,
                connected=False,
                scope=self.scope,
                resource_name=self.resource_name,
                error=f"Azure Cost Management is temporarily unavailable: {type(exc).__name__}",
            )

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        token_response = await client.post(
            (
                "https://login.microsoftonline.com/"
                f"{self._settings.AZURE_COST_TENANT_ID}/oauth2/v2.0/token"
            ),
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.AZURE_COST_CLIENT_ID,
                "client_secret": self._settings.AZURE_COST_CLIENT_SECRET,
                "scope": "https://management.azure.com/.default",
            },
        )
        token_response.raise_for_status()
        token = token_response.json().get("access_token")
        if not token:
            raise ValueError("Azure token response did not contain access_token")
        return str(token)

    @staticmethod
    def _extract_resource_cost(payload: dict, target_resource_id: str) -> tuple[float, str | None]:
        """Extract target resource cost from a Cost Management query response."""
        properties = payload.get("properties") or {}
        columns = properties.get("columns") or []
        rows = properties.get("rows") or []
        names = [str(column.get("name", "")) for column in columns]
        lower_names = [name.lower() for name in names]

        def column_index(*candidates: str) -> int | None:
            for candidate in candidates:
                candidate = candidate.lower()
                if candidate in lower_names:
                    return lower_names.index(candidate)
            return None

        cost_index = column_index("PreTaxCost", "Cost", "CostUSD")
        resource_index = column_index("ResourceId")
        currency_index = column_index("Currency", "BillingCurrency")
        if cost_index is None or resource_index is None:
            return 0.0, None

        target = target_resource_id.rstrip("/").lower()
        total = 0.0
        currencies: set[str] = set()
        for row in rows:
            if not isinstance(row, list) or max(cost_index, resource_index) >= len(row):
                continue
            resource_id = str(row[resource_index] or "").rstrip("/").lower()
            if resource_id != target:
                continue
            try:
                total += float(row[cost_index] or 0)
            except (TypeError, ValueError):
                continue
            if currency_index is not None and currency_index < len(row) and row[currency_index]:
                currencies.add(str(row[currency_index]).upper())

        currency = next(iter(currencies)) if len(currencies) == 1 else None
        return total, currency
