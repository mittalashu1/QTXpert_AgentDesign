import pytest
from uuid import uuid4

from app.api.routes.execution_plans import _plan_payload, _preflight_plan
from app.database.models.execution_plan import ExecutionPlan, ExecutionPlanCase


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

