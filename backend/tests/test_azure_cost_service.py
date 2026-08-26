import pytest

from app.config import Settings
from app.services.azure_cost_service import AzureCostService


def test_extract_resource_cost_only_counts_target_resource():
    target = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/qtxpert-ai"
    payload = {
        "properties": {
            "columns": [
                {"name": "PreTaxCost"},
                {"name": "ResourceId"},
                {"name": "Currency"},
            ],
            "rows": [
                [12.25, target, "USD"],
                [7.75, target.upper(), "USD"],
                [99.0, "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/other", "USD"],
            ],
        }
    }

    cost, currency = AzureCostService._extract_resource_cost(payload, target)

    assert cost == pytest.approx(20.0)
    assert currency == "USD"


def test_resource_name_is_derived_from_azure_openai_endpoint():
    settings = Settings(_env_file=None, AZURE_ENDPOINT="https://qtxpert-ai.openai.azure.com/")

    assert AzureCostService(settings).resource_name == "qtxpert-ai"


@pytest.mark.asyncio
async def test_unconfigured_cost_service_is_explicitly_not_connected():
    settings = Settings(_env_file=None, AZURE_ENDPOINT="https://qtxpert-ai.openai.azure.com/")

    snapshot = await AzureCostService(settings).query(days=30)

    assert snapshot.configured is False
    assert snapshot.connected is False
    assert snapshot.actual_cost is None
    assert snapshot.resource_name == "qtxpert-ai"
    assert snapshot.error is None
