from app.schemas.autopilot import AutopilotContextRequest
from app.services.autopilot_research import _SearchParser, _result_url, _safe_text, AutopilotResearchService


def test_public_search_parser_keeps_title_and_snippet_together():
    parser = _SearchParser()
    parser.feed(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide">'
        "InvestNation guide</a>"
        '<div class="result__snippet">Public portfolio and account information.</div>'
    )
    parser.close()

    assert len(parser.results) == 1
    assert parser.results[0]["title"] == "InvestNation guide"
    assert "portfolio" in parser.results[0]["snippet"]
    assert _result_url(parser.results[0]["url"]) == "https://example.com/guide"


def test_public_research_redacts_secret_like_snippets_and_rejects_credentials():
    safe = _safe_text("password: SuperSecret token=abc123 public", 200)

    assert "SuperSecret" not in safe
    assert "abc123" not in safe
    assert _result_url("https://user:password@example.com/private") is None


def test_public_research_query_is_identity_scoped_and_includes_uae_domain_terms():
    request = AutopilotContextRequest(
        profile_id="uae_fintech",
        application_name="InvestNation",
        platform="Web",
        target_url="https://investnation.com",
    )

    query = AutopilotResearchService.build_query(request, "UAE Digital Banking & Wealth")

    assert "InvestNation" in query
    assert "CBUAE" in query
    assert "SCA" in query
    assert "password" not in query.casefold()

