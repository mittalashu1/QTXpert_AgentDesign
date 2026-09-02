from types import SimpleNamespace

from app.api.routes.usage import COST_ADMIN_EMAIL, _build_cost_surfaces, _is_cost_admin_email
from app.config import Settings


def _azure_snapshot(**overrides):
    values = {
        "configured": False,
        "connected": False,
        "actual_cost": None,
        "currency": None,
        "last_synced_at": None,
        "scope": None,
        "resource_name": None,
        "error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_cost_center_owner_email_is_exact_and_case_insensitive():
    assert COST_ADMIN_EMAIL == "admin@qtxpert.com"
    assert _is_cost_admin_email("admin@qtxpert.com") is True
    assert _is_cost_admin_email(" ADMIN@QTXPERT.COM ") is True
    assert _is_cost_admin_email("other-admin@qtxpert.com") is False
    assert _is_cost_admin_email(None) is False


def test_cost_inventory_lists_unmetered_ecosystem_surfaces_without_fake_zeroes():
    settings = Settings(
        _env_file=None,
        POSTGRES_URL="postgresql+asyncpg://u:p@db.example.com:5432/qtxpert",
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
        VECTOR_DB_PROVIDER="pinecone",
        PINECONE_API_KEY="pinecone-key",
        GOOGLE_API_KEY="google-key",
    )
    surfaces = _build_cost_surfaces(settings, [], _azure_snapshot())
    by_key = {surface.key: surface for surface in surfaces}

    required = {
        "azure_openai",
        "gemini",
        "openai",
        "anthropic",
        "bedrock",
        "render_backend",
        "render_frontend",
        "postgresql",
        "browserstack",
        "pinecone",
        "github",
        "domain_dns",
        "upload_storage",
        "cloudflare_r2",
    }
    assert required.issubset(by_key)
    assert by_key["browserstack"].coverage == "manual"
    assert by_key["postgresql"].coverage == "manual"
    assert by_key["gemini"].coverage == "manual"
    assert by_key["openai"].coverage == "not_configured"
    assert by_key["postgresql"].service == "Neon Postgres Database"
    assert by_key["postgresql"].portal_url == "https://console.neon.tech/"
    assert by_key["cloudflare_r2"].pricing_url == "https://developers.cloudflare.com/r2/pricing/"
    assert by_key["cloudflare_r2"].limits
    assert all(surface.portal_url for surface in surfaces)

    for surface in surfaces:
        if surface.coverage in {"manual", "not_configured"}:
            assert surface.actual_cost is None
            assert surface.estimated_cost_usd is None


def test_azure_actual_cost_is_marked_authoritative_when_connected():
    settings = Settings(
        _env_file=None,
        AZURE_OPENAI_API_KEY="key",
        AZURE_ENDPOINT="https://example.openai.azure.com",
    )
    surfaces = _build_cost_surfaces(
        settings,
        [],
        _azure_snapshot(connected=True, configured=True, actual_cost=20.0, currency="USD"),
    )
    azure = next(surface for surface in surfaces if surface.key == "azure_openai")

    assert azure.coverage == "actual"
    assert azure.actual_cost == 20.0
    assert azure.currency == "USD"
    assert azure.portal_url == "https://portal.azure.com/"
