from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    AutopilotTest,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveryLocator,
)
from app.services.autopilot_scope import (
    add_test_provenance,
    compile_scope,
    update_scope_with_discovery,
)


def test_scope_compiler_keeps_plain_language_document_and_change_context():
    scope = compile_scope(
        profile_id="uae_fintech",
        profile_name="UAE Digital Banking & Wealth",
        target_kind="web",
        target_url="https://investnation.com",
        application_name="InvestNation",
        context=(
            "Focus on functional positive and negative journeys, UAT, accessibility, and regression.\n"
            "Change impact: the new portfolio page should not break existing customer journeys."
        ),
        document_asset_ids=["11111111-1111-1111-1111-111111111111"],
        document_analysis_run_id="22222222-2222-2222-2222-222222222222",
        document_context=(
            "Documents reviewed: investnation-prd.docx (PRD)\n"
            "Functional requirements: Customers can view a portfolio.\n"
            "Acceptance criteria: A customer sees the current portfolio balance.\n"
            "Change impact signals: Portfolio navigation was updated in this release."
        ),
    )

    assert scope.target.startswith("Website · investnation.com")
    assert "Core journeys" in scope.functional_scope
    assert "Screen clarity and accessibility" in scope.non_functional_scope
    assert "Business acceptance" in scope.requested_test_types
    assert any(item.title == "Functional requirements" for item in scope.document_sections)
    assert any("updated" in item.casefold() for item in scope.change_impact)
    assert any(item.kind == "document" for item in scope.sources)
    assert "Runtime Discovery" in scope.authentication_gate
    assert scope.editable is True


def test_editable_brief_is_not_mislabelled_as_repository_document():
    scope = compile_scope(
        profile_id="custom",
        profile_name="Custom profile",
        target_kind="web",
        target_url="https://example.com",
        context="Functional requirements: browse public pages and search. Acceptance criteria: no broken links.",
    )

    assert scope.document_sections == []
    assert all(item.source != "document" for item in scope.scope_sections)


def test_functional_only_scope_keeps_named_journeys_without_adding_quality_cases():
    scope = compile_scope(
        profile_id="general_mobile",
        profile_name="General mobile",
        target_kind="android",
        application_name="FH Money",
        context=(
            "Testing scope: Functional only\n"
            "Modules: Login, Profile, Dashboard, Cards, Send Money, AANI\n"
            "User ID: qa.user@example.test\n"
            "Password: [REDACTED]"
        ),
    )

    assert scope.requested_test_types == ["Functional only"]
    assert scope.non_functional_scope == []
    assert [item.title for item in scope.requested_journeys] == [
        "Login", "Profile", "Dashboard", "Cards", "Send Money", "AANI"
    ]
    assert all(item.status == "planned" for item in scope.requested_journeys)


def test_named_journey_is_marked_observed_only_after_matching_runtime_evidence():
    scope = compile_scope(
        profile_id="general_mobile",
        profile_name="General mobile",
        target_kind="android",
        context="Modules: Login, Profile",
    )
    discovery = AutopilotDiscoveryResult(
        job_id="66666666-6666-4666-8666-666666666666",
        status="completed",
        provider="appium",
        started_at="2026-09-20T00:00:00+00:00",
        finished_at="2026-09-20T00:00:01+00:00",
        duration_seconds=1,
        device_name="Android smoke device",
        screens=[
            DiscoveredScreen(
                screen_id="profile",
                fingerprint="g" * 64,
                journey="Account",
                page_label="Profile",
                controls=[],
            )
        ],
        screen_count=1,
        control_count=0,
    )

    updated = update_scope_with_discovery(scope, discovery)

    states = {item.title: item.status for item in updated.requested_journeys}
    assert states == {"Login": "planned", "Profile": "observed"}


def test_test_provenance_retains_target_profile_context_documents_and_public_signal():
    test = AutopilotTest(
        id="scope-001",
        suite="Functional",
        title="Open the portfolio safely",
        objective="Confirm the public portfolio journey opens.",
        source="ai",
    )
    enriched = add_test_provenance(
        test,
        target_kind="web",
        profile_id="uae_fintech",
        context_present=True,
        document_asset_ids=["33333333-3333-3333-3333-333333333333"],
        research_sources=[
            {
                "kind": "internet",
                "label": "Central Bank guidance",
                "reference": "https://www.centralbank.ae/guidance",
                "summary": "Public reference signal",
            }
        ],
    )

    kinds = {item.kind for item in enriched.provenance}
    references = {item.reference for item in enriched.provenance}
    assert {"target", "profile", "user_context", "document", "internet", "system"}.issubset(kinds)
    assert "document:33333333-3333-3333-3333-333333333333" in references
    assert "ai:planner" in references


def test_runtime_discovery_updates_scope_without_erasing_static_sources():
    initial = compile_scope(
        profile_id="general_mobile",
        profile_name="General mobile",
        target_kind="android",
        application_name="InvestNation",
        context="Focus on functional journeys.",
        document_asset_ids=["44444444-4444-4444-4444-444444444444"],
    )
    discovery = AutopilotDiscoveryResult(
        job_id="55555555-5555-5555-5555-555555555555",
        status="completed",
        provider="appium",
        started_at="2026-09-13T00:00:00+00:00",
        finished_at="2026-09-13T00:00:01+00:00",
        duration_seconds=1,
        device_name="Android smoke device",
        screens=[
            DiscoveredScreen(
                screen_id="login",
                fingerprint="f" * 64,
                journey="Authentication",
                page_label="Sign in",
                controls=[
                    DiscoveredControl(
                        control_id="username",
                        semantic_label="User ID",
                        class_name="android.widget.EditText",
                        input_capable=True,
                        locators=[DiscoveryLocator(strategy="id", value="user", confidence=0.9)],
                    )
                ],
            )
        ],
        screen_count=1,
        control_count=1,
    )

    updated = update_scope_with_discovery(initial, discovery)

    assert updated.runtime_observed is True
    assert any(item.title == "Authentication · Sign in" for item in updated.scope_sections)
    assert any(item.kind == "document" for item in updated.sources)
    assert any(item.kind == "runtime" and item.observed for item in updated.sources)
    assert "Observed safe journeys" in updated.functional_scope
    assert updated.login_observed is True
    assert "credentials are required" in updated.authentication_gate

