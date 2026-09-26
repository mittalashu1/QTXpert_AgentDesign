from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotScope,
    AutopilotScopeSource,
    AutopilotTest,
    AutopilotTestProvenance,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
)
from app.services.autopilot_scope import annotate_scope_usage
from app.services.autopilot_workflow import (
    build_application_map,
    build_execution_control_payload,
    build_generation_plan,
    find_duplicate_cases,
    transition_phase,
)


def _analysis() -> AutopilotAnalysis:
    tests = [
        AutopilotTest(
            id="TC-FUNC-001",
            suite="Functional",
            bucket="functional",
            title="Open the portfolio from the signed-in home",
            objective="Confirm the observed portfolio journey opens.",
            steps=["Tap Portfolio"],
            expected=["Portfolio page is visible"],
            source_refs=["runtime:screen-home"],
            requirement_refs=["REQ-1"],
            observation_refs=["screen-home", "control-portfolio"],
            provenance=[AutopilotTestProvenance(kind="runtime", label="Observed home screen", source_id="runtime:screen-home", observed=True, confidence=0.95)],
        ),
        AutopilotTest(
            id="TC-NEG-001",
            suite="Functional",
            bucket="functional_negative",
            title="Reject an invalid portfolio search",
            objective="Confirm the observed validation message is shown.",
            steps=["Fill search with invalid value", "Tap Search"],
            expected=["An observed validation message is displayed"],
            source_refs=["runtime:screen-search"],
            requirement_refs=["REQ-2"],
            requires_test_data=True,
            autonomous_candidate=False,
        ),
    ]
    return AutopilotAnalysis(
        job_id="job-123",
        filename="investnation.apk",
        target_kind="android",
        sha256="a" * 64,
        tests=tests,
        scope=AutopilotScope(
            summary="Observed portfolio coverage",
            target="Android application",
            requested_test_types=["functional", "functional_negative"],
            sources=[
                AutopilotScopeSource(
                    source_id="runtime:screen-home",
                    kind="runtime",
                    label="Observed home screen",
                    observed=True,
                    used=True,
                    confidence=0.95,
                    trust_level="high",
                )
            ],
        ),
    )


def test_phase_transitions_are_explicit_and_idempotent():
    assert transition_phase("draft", "preflight") == "preflight"
    assert transition_phase("draft", "cases_pending_review") == "cases_pending_review"
    assert transition_phase("draft", "blocked") == "blocked"
    # A resumed checkpoint may finish discovery from plan review; it must
    # enter case review without skipping the explicit approval gate.
    assert transition_phase("plan_pending_review", "cases_pending_review") == "cases_pending_review"
    assert transition_phase("blocked", "cases_pending_review") == "cases_pending_review"
    assert transition_phase("partial", "plan_approved") == "plan_approved"
    assert transition_phase("partial", "cases_pending_review") == "cases_pending_review"
    assert transition_phase("partial", "cases_approved") == "cases_approved"
    assert transition_phase("cases_pending_review", "cases_approved") == "cases_approved"
    assert transition_phase("cases_approved", "cases_approved") == "cases_approved"
    # Discovery/setup retries can overlap an already running safe suite; the
    # continuation must remain idempotent rather than failing the job.
    assert transition_phase("running", "exploring") == "exploring"
    assert transition_phase("running", "cases_pending_review") == "cases_pending_review"

    try:
        transition_phase("draft", "running")
    except ValueError as exc:
        assert "draft -> running" in str(exc)
    else:
        raise AssertionError("an approval-gated phase jump must be rejected")


def test_generation_plan_groups_cases_and_preserves_provenance():
    analysis = _analysis()
    plan = build_generation_plan(analysis)

    assert plan.job_id == analysis.job_id
    assert plan.context_source_count == 1
    assert {item.test_type for item in plan.items} == {"functional", "functional_negative"}
    functional = next(item for item in plan.items if item.test_type == "functional")
    assert functional.source_refs == ["runtime:screen-home"]
    assert functional.requirement_refs == ["REQ-1"]
    assert functional.expected_output
    assert functional.agent == "Autopilot planner"

    annotated = annotate_scope_usage(analysis.scope, plan)
    assert "scope-001-functional" in annotated.sources[0].influenced_plan_items


def test_application_map_projects_observed_controls_without_values():
    screen = DiscoveredScreen(
        screen_id="home",
        fingerprint="b" * 64,
        page_label="Home",
        confidence=0.9,
        observation_ref="obs-home",
        controls=[
            DiscoveredControl(
                control_id="portfolio",
                semantic_label="Portfolio",
                clickable=True,
                observation_ref="obs-portfolio",
                locators=[DiscoveryLocator(strategy="id", value="portfolio", confidence=0.92)],
            ),
            DiscoveredControl(
                control_id="search",
                semantic_label="Search",
                input_capable=True,
                validation_behavior="Observed error message for an invalid value.",
            ),
        ],
    )
    transition = DiscoveredTransition(
        from_screen_id="home",
        to_screen_id="portfolio",
        control_id="portfolio",
        control_label="Portfolio",
        observation_ref="obs-transition",
    )

    application_map = build_application_map(
        job_id="job-123",
        target_kind="android",
        target_identity="com.example.app",
        screens=[screen],
        transitions=[transition],
        login_observed=True,
    )

    assert application_map.controls_count == 2
    assert application_map.login_observed is True
    assert application_map.authentication_boundaries
    assert "Observed error message for" in application_map.validation_behaviors[0]
    assert {"obs-home", "obs-portfolio", "obs-transition"}.issubset(application_map.observation_refs)
    assert application_map.confidence > 0


def test_duplicate_detection_and_execution_handoff_are_safe():
    analysis = _analysis()
    existing = [{
        "id": "existing-1",
        "title": "Open the portfolio from the signed-in home",
        "objective": "Confirm the observed portfolio journey opens.",
        "steps": ["Tap Portfolio"],
        "expected": ["Portfolio page is visible"],
    }]
    duplicates = find_duplicate_cases(analysis.tests, existing)

    assert duplicates["TC-FUNC-001"]["status"] == "duplicate"
    assert duplicates["TC-NEG-001"]["status"] == "unique"

    handoff = build_execution_control_payload(analysis.tests, run_id=analysis.job_id)
    assert handoff["run_id"] == analysis.job_id
    assert handoff["total"] == 2
    assert handoff["tests"][0]["provenance"][0]["source_id"] == "runtime:screen-home"
    assert all("password" not in str(row).casefold() for row in handoff["tests"])

