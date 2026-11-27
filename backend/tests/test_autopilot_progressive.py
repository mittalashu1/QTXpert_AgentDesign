"""Regression coverage for write-only run intake and progressive replay."""
import json

import pytest

from app.schemas.autopilot import (
    AutopilotBusinessAnswer,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveryLocator,
    QTXIRStep,
    QTXTestIR,
)
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_instructions import (
    auth_binding_key,
    parse_run_instructions,
    scope_allows_case,
    scope_allows_navigation,
)
from app.services.autopilot_progress import apply_business_answer


def test_prompt_binds_inputs_before_context_is_used():
    brief = parse_run_instructions(
        "Only test the Cards module. Exercise viewing and freezing.\n"
        "User ID is fixture@example.test and password is QA-test!67\n"
        "Login data: Member number = QA456\n"
        "Test data: Card nickname = Frosted; Branch = Test branch\n"
        "Please use pre-filled values."
    )
    assert brief.modules == ["Cards"]
    assert brief.reuse is True
    assert "Exercise viewing and freezing" in brief.context
    values = {item.label: item.value for item in brief.inputs}
    assert json.loads(values["UAT sign-in credentials"]) == {
        "username": "fixture@example.test", "password": "QA-test!67",
    }
    assert {key: values[key] for key in ("Member number", "Card nickname", "Branch")} == {
        "Member number": "QA456", "Card nickname": "Frosted", "Branch": "Test branch",
    }
    for value in ("fixture@example.test", "QA-test!67", "QA456", "Frosted", "Test branch"):
        assert value not in brief.context
        assert value not in repr(brief.inputs)


def test_user_gets_only_the_observed_missing_sign_in_field():
    driver = AutopilotDiscoveryService
    member_number = DiscoveredControl(
        control_id="member", semantic_label="Member number", input_capable=True, input_kind="credential",
        locators=[DiscoveryLocator(strategy="id", value="member", confidence=0.99)],
    )
    sign_in = DiscoveredControl(
        control_id="sign-in", semantic_label="Sign in", clickable=True, risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="sign-in", confidence=0.99)],
    )
    screen = DiscoveredScreen(screen_id="screen-001", fingerprint="auth", controls=[member_number, sign_in])
    missing = driver._authentication_checkpoint_reason(screen, {"__auth_approved": "1", "__username": "unrelated"})
    assert missing and "Member number" in missing and "Password" not in missing
    bound = {"__auth_approved": "1", auth_binding_key("Member number"): "QA456"}
    assert driver._authentication_checkpoint_reason(screen, bound) is None


def test_email_password_shorthand_keeps_the_remaining_instructions():
    brief = parse_run_instructions("fixture@example.test/QA!456 Only test Profile.")

    assert brief.modules == ["Profile"]
    assert json.loads(brief.inputs[0].value) == {"username": "fixture@example.test", "password": "QA!456"}
    assert "fixture@example.test" not in brief.context
    assert "QA!456" not in brief.context


@pytest.mark.parametrize("instruction", ["OTP: 123456", "Login data: verification code = 123456"])
def test_fresh_codes_stay_in_the_observed_checkpoint(instruction):
    with pytest.raises(ValueError) as error:
        parse_run_instructions(instruction)
    assert "123456" not in str(error.value)


def test_module_scope_keeps_transit_navigation_and_excludes_sibling_cases():
    modules = parse_run_instructions("Only test Cards.").modules
    assert scope_allows_navigation(modules, "Open menu", inside=False)
    assert scope_allows_navigation(modules, "Cards Tab 3 of 4", inside=False)
    assert not scope_allows_navigation(modules, "Investments Tab 2 of 4", inside=True)
    assert not scope_allows_navigation(modules, "Investments", inside=True, global_navigation=True)
    card_case = QTXTestIR(test_id="C", title="Open Cards", suite="Fixture", priority="high", readiness="executable",
                          source="deterministic", journey="Home", steps=[
                              QTXIRStep(action="tap", target="Cards Tab 3 of 4", description="Open Cards"),
                          ])
    investments = card_case.model_copy(update={
        "journey": "Cards", "steps": [QTXIRStep(action="tap", target="Investments Tab 2 of 4", description="Open Investments")],
    })
    assert scope_allows_case(modules, card_case, set())
    assert not scope_allows_case(modules, investments, {"cards-screen"})


def test_feedback_updates_only_the_matching_case_and_adds_a_visible_assertion():
    case = QTXTestIR(test_id="case-cards", title="Cards overview", suite="Fixture", priority="high", readiness="executable",
                     source="deterministic", steps=[QTXIRStep(action="launch_app", description="Launch app")])
    answer = AutopilotBusinessAnswer(
        finding_id="case-observation", case_id=case.test_id, title=case.title,
        expected_behavior="A signed-in member can see card controls.",
        visible_text="Cards overview", saved_at="2026-11-26T00:00:00Z",
    )
    updated = apply_business_answer(case, [answer])
    assert updated.assertions == [answer.expected_behavior]
    assert updated.steps[-1].action == "assert_business_text"
    assert updated.steps[-1].assertion == "Cards overview"
    unrelated = case.model_copy(update={"test_id": "case-investments", "title": "Investments"})
    assert apply_business_answer(unrelated, [answer]) == unrelated
