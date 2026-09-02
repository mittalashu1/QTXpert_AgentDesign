import pytest

from app.config import Settings
from app.services.cost_catalog import (
    CostCatalogSnapshotView,
    _merge_provider_snapshots,
    _metric_from_r2_class,
    _probe_browserstack,
    _probe_cloudflare_r2,
    _probe_neon,
    surface_metadata,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Response(self.payload)


def test_r2_metrics_use_published_objects_and_payload_sizes():
    result = {
        "standard": {
            "published": {"objects": 3, "payloadSize": 2048, "metadataSize": 12},
            "uploaded": {"objects": 99, "payloadSize": 99, "metadataSize": 99},
        }
    }
    assert _metric_from_r2_class(result, "standard") == {
        "objects": 3,
        "payload_bytes": 2048,
        "metadata_bytes": 12,
    }


@pytest.mark.asyncio
async def test_provider_probes_return_safe_non_secret_values():
    browserstack = _Client(
        {
            "automate_plan": "App Automate",
            "parallel_sessions_running": 2,
            "parallel_sessions_max_allowed": 5,
            "queued_sessions": 1,
            "queued_sessions_max_allowed": 5,
        }
    )
    browserstack_result = await _probe_browserstack(
        Settings(BROWSERSTACK_USERNAME="user", BROWSERSTACK_ACCESS_KEY="secret"), browserstack
    )
    assert browserstack_result == {
        "account_plan": "App Automate",
        "live_usage": {"parallel_running": 2, "parallel_max": 5, "queued": 1, "queue_max": 5},
    }
    assert "secret" not in repr(browserstack_result)

    r2 = _Client(
        {
            "success": True,
            "result": {"standard": {"published": {"objects": 4, "payloadSize": 4096, "metadataSize": 20}}},
        }
    )
    r2_result = await _probe_cloudflare_r2(
        Settings(CLOUDFLARE_API_TOKEN="secret", CLOUDFLARE_ACCOUNT_ID="account"), r2
    )
    assert r2_result == {"live_usage": {"objects": 4, "payload_bytes": 4096, "metadata_bytes": 20}}
    assert "secret" not in repr(r2_result)

    neon = _Client({"spending_limit_cents": 2500})
    neon_result = await _probe_neon(
        Settings(NEON_API_KEY="secret", NEON_ORG_ID="org", NEON_PLAN="Launch"), neon
    )
    assert neon_result == {"account_plan": "Launch", "live_usage": {"spending_limit_usd": 25.0, "spending_limit_configured": True}}
    assert "secret" not in repr(neon_result)


def test_surface_metadata_merges_live_plan_without_exposing_credentials():
    metadata = surface_metadata(
        "browserstack",
        Settings(),
        CostCatalogSnapshotView(
            status="fresh",
            providers={"browserstack": {"account_plan": "App Automate", "live_usage": {"parallel_max": 5}}},
        ),
    )
    assert metadata["account_plan"] == "App Automate"
    assert metadata["live_usage"] == {"parallel_max": 5}
    assert metadata["portal_url"]

    postgres_storage = surface_metadata("upload_storage", Settings(NEON_PLAN="Launch"))
    assert postgres_storage["portal_url"] == "https://console.neon.tech/"
    object_storage = surface_metadata(
        "upload_storage",
        Settings(
            UPLOAD_STORAGE_BACKEND="object_store",
            OBJECT_STORAGE_BUCKET="qtxpert-artifacts",
        ),
    )
    assert object_storage["portal_url"] == "https://dash.cloudflare.com/"


def test_failed_provider_refresh_keeps_last_known_usage_and_surfaces_error():
    previous = {
        "browserstack": {
            "account_plan": "App Automate",
            "live_usage": {"parallel_max": 5},
            "last_verified_at": "2026-08-01T00:00:00+00:00",
        },
        "cloudflare_r2": {"live_usage": {"objects": 12}},
    }
    merged = _merge_provider_snapshots(
        previous,
        {
            "browserstack": {"error": "BrowserStack plan API unavailable (TimeoutException)."},
            "cloudflare_r2": {"live_usage": {"objects": 18}},
        },
    )
    assert merged["browserstack"]["account_plan"] == "App Automate"
    assert merged["browserstack"]["live_usage"] == {"parallel_max": 5}
    assert merged["browserstack"]["error"].startswith("BrowserStack")
    assert merged["cloudflare_r2"]["live_usage"] == {"objects": 18}

