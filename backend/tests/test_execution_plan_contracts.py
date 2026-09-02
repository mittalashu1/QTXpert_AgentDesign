import pytest
from uuid import uuid4

from app.api.routes.execution_plans import _compact_plan_name, _input_requirements, _plan_payload, _preflight_plan
from app.api.routes.executions import _compile_mobile_steps
from app.database.models.execution_plan import ExecutionPlan, ExecutionPlanCase
from app.schemas.execution import ExecutionPlanExecute, ExecutionPlanPreflight


def _case(*, selected=True, mode="automated", steps=None, candidate=True):
    return ExecutionPlanCase(
        source_test_case_id=uuid4(),
        selection_order=0,
        selected=selected,
        execution_mode=mode,
        readiness="pending",
        test_case_key="TC-001",
        test_type="functional",
        scenario="Open the public landing page",
        objective="Verify the page can be opened",
        priority="high",
        severity="major",
        steps=steps or ["assert-text Example Domain"],
        expected_result="The page is visible",
        is_automation_candidate=candidate,
        risk_level="low",
    )


def test_compact_plan_name_respects_database_limit_and_word_boundary():
    long_title = "Test coverage targets the primary customer journeys and state transitions " * 8

    compacted = _compact_plan_name(long_title)

    assert len(compacted) <= 255
    assert compacted.endswith("…")
    assert not compacted.endswith(" ")


def test_web_target_url_is_deferred_to_execution_target_validation():
    """A target request must reach the route's actionable URL validator.

    FastAPI's HttpUrl parser could reject browser-entered targets first,
    returning an unhelpful 422.  The route now owns URL and network policy so
    malformed or unsafe targets can return a specific error instead.
    """
    for model in (ExecutionPlanPreflight, ExecutionPlanExecute):
        for value in ("https://investnation.com", "investnation.com"):
            payload = model(target_kind="web", provider="playwright", base_url=value)
            assert payload.base_url == value


@pytest.mark.asyncio
async def test_preflight_marks_supported_selected_case_ready():
    plan = ExecutionPlan(name="Smoke", suite_type="smoke", status="draft")
    plan.cases.append(_case())

    await _preflight_plan(plan, "https://example.com")

    assert plan.status == "ready"
    assert plan.cases[0].readiness == "ready"
    assert plan.cases[0].blocker_reason is None
    assert _plan_payload(plan)["ready_cases"] == 1


@pytest.mark.asyncio
async def test_preflight_blocks_unsupported_generated_prose():
    plan = ExecutionPlan(name="Feature", suite_type="feature", status="draft")
    plan.cases.append(_case(steps=["Log in as a valid customer"]))

    await _preflight_plan(plan, "https://example.com")

    assert plan.status == "blocked"
    assert plan.cases[0].readiness == "blocked"
    assert "Unsupported automation step" in (plan.cases[0].blocker_reason or "")


@pytest.mark.asyncio
async def test_manual_case_is_visible_but_not_runnable():
    plan = ExecutionPlan(name="Regression", suite_type="regression", status="draft")
    plan.cases.append(_case(mode="manual", candidate=False))

    await _preflight_plan(plan, "https://example.com")

    assert plan.status == "draft"
    assert plan.cases[0].readiness == "manual_review"
    assert "manual execution" in (plan.cases[0].blocker_reason or "")


def test_mobile_dsl_compiles_safe_actions_and_assertions():
    assert _compile_mobile_steps([
        "launch app",
        "tap accessibility_id :: Sign in",
        "fill id :: email :: qa@example.com",
        "assert-text Welcome",
        "assert-visible id :: account-menu",
        "back",
    ]) == [
        ("tap", "accessibility_id", "Sign in"),
        ("fill", "id", "email :: qa@example.com"),
        ("assert-text", None, "Welcome"),
        ("assert-visible", "id", "account-menu"),
        ("back", None, None),
    ]


def test_mobile_dsl_blocks_unknown_prose():
    with pytest.raises(ValueError, match="Unsupported mobile automation step"):
        _compile_mobile_steps(["Transfer funds to the beneficiary"])


@pytest.mark.asyncio
async def test_mobile_preflight_allows_target_validation_to_defer_step_support():
    plan = ExecutionPlan(name="Android smoke", suite_type="smoke", status="draft")
    plan.cases.append(_case(steps=["tap accessibility_id :: Sign in"]))

    await _preflight_plan(plan, None, target_kind="android")

    assert plan.status == "ready"
    assert plan.cases[0].readiness == "ready"


@pytest.mark.asyncio
async def test_preflight_surfaces_auth_and_data_setup_instead_of_a_dead_end():
    plan = ExecutionPlan(name="Authenticated flow", suite_type="feature", status="draft")
    plan.cases.append(_case(
        steps=["Log in with a valid customer", "click #portfolio"],
    ))

    await _preflight_plan(plan, "https://example.com")

    assert plan.status == "blocked"
    assert plan.cases[0].readiness == "blocked"
    assert "Authentication setup is required" in (plan.cases[0].blocker_reason or "")
    requirements = _input_requirements(plan)
    assert {item["key"] for item in requirements} >= {
        "authentication_reference",
        "test_data_reference",
    }
    assert all(not item["provided"] for item in requirements if item["key"] in {"authentication_reference", "test_data_reference"})


@pytest.mark.asyncio
async def test_setup_references_and_explicit_steps_make_case_runnable():
    plan = ExecutionPlan(name="Authenticated flow", suite_type="feature", status="draft")
    plan.runtime_inputs = {
        "authentication_reference": "vault://qa/customer",
        "test_data_reference": "dataset://seeded/customer-01",
    }
    plan.cases.append(_case(
        steps=["navigate /login", "fill #email :: qa@example.com", "click #submit", "assert-url /home"],
    ))

    await _preflight_plan(plan, "https://example.com")

    assert plan.status == "ready"
    assert plan.cases[0].readiness == "ready"
    assert not [item for item in _input_requirements(plan) if not item["provided"]]


@pytest.mark.asyncio
async def test_mobile_preflight_blocks_prose_and_offers_conversion_requirement():
    plan = ExecutionPlan(name="Mobile flow", suite_type="smoke", status="draft")
    plan.cases.append(_case(steps=["Open the account screen and verify the balance"]))

    await _preflight_plan(plan, None, target_kind="android")

    assert plan.status == "blocked"
    assert plan.cases[0].readiness == "blocked"
    assert "Unsupported mobile automation step" in (plan.cases[0].blocker_reason or "")
    assert any(item["category"] == "automation" for item in _input_requirements(plan))

