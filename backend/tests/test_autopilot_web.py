from pathlib import Path

import pytest

from app.schemas.autopilot import DiscoveredControl, DiscoveryLocator
from app.services.autopilot_web import AutopilotWebService, _capture_screenshot, _redact_html


class _ScreenshotPage:
    def __init__(self, fail_full_page: bool = False, fail_viewport: bool = False):
        self.fail_full_page = fail_full_page
        self.fail_viewport = fail_viewport
        self.calls: list[dict] = []

    async def screenshot(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("full_page") and self.fail_full_page:
            raise TimeoutError("font wait timed out")
        if not kwargs.get("full_page") and self.fail_viewport:
            raise TimeoutError("viewport capture timed out")


@pytest.mark.asyncio
async def test_screenshot_falls_back_to_viewport_after_full_page_timeout(tmp_path: Path):
    page = _ScreenshotPage(fail_full_page=True)

    captured, warning = await _capture_screenshot(page, tmp_path / "launch.png")

    assert captured == str(tmp_path / "launch.png")
    assert warning and "viewport evidence captured" in warning
    assert [call["full_page"] for call in page.calls] == [True, False]


@pytest.mark.asyncio
async def test_screenshot_is_optional_when_both_capture_modes_fail(tmp_path: Path):
    page = _ScreenshotPage(fail_full_page=True, fail_viewport=True)

    captured, warning = await _capture_screenshot(page, tmp_path / "launch.png")

    assert captured is None
    assert warning and warning.startswith("Screenshot unavailable:")
    assert [call["full_page"] for call in page.calls] == [True, False]


def test_persisted_web_html_redacts_typed_values_but_keeps_structure():
    html = '<input id="user" value="qa@example.test" aria-valuetext="qa@example.test"><button>Sign in</button>'
    redacted = _redact_html(html)
    assert "qa@example.test" not in redacted
    assert 'value=""' in redacted
    assert 'aria-valuetext=""' in redacted
    assert "Sign in" in redacted


def test_unlabelled_web_login_fields_are_promoted_before_checkpointing():
    controls = [
        DiscoveredControl(
            control_id="field-1",
            semantic_label="field1",
            class_name="input",
            input_capable=True,
            locators=[DiscoveryLocator(strategy="css", value="#field1", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="field-2",
            semantic_label="field2",
            class_name="input",
            input_capable=True,
            locators=[DiscoveryLocator(strategy="css", value="#field2", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="continue",
            semantic_label="Continue",
            class_name="button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="css", value="#continue", confidence=0.95)],
        ),
    ]

    normalized = AutopilotWebService._ensure_auth_input_semantics(controls)
    inputs = [control for control in normalized if control.input_capable]
    assert [control.semantic_label for control in inputs] == ["User ID / email", "Password"]
    assert [control.input_kind for control in inputs] == ["credential", "credential"]


def test_ambiguous_generic_submit_does_not_guess_authentication():
    controls = [
        DiscoveredControl(
            control_id="field-1",
            semantic_label="field1",
            class_name="input",
            input_capable=True,
            locators=[DiscoveryLocator(strategy="css", value="#field1", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="field-2",
            semantic_label="field2",
            class_name="input",
            input_capable=True,
            locators=[DiscoveryLocator(strategy="css", value="#field2", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="submit",
            semantic_label="Submit",
            class_name="button",
            clickable=True,
            risk="blocked",
            locators=[DiscoveryLocator(strategy="css", value="#submit", confidence=0.95)],
        ),
    ]

    normalized = AutopilotWebService._ensure_auth_input_semantics(controls)
    inputs = [control for control in normalized if control.input_capable]
    assert [control.semantic_label for control in inputs] == ["field1", "field2"]
    assert [control.input_kind for control in inputs] == [None, None]
    assert AutopilotWebService._auth_submit_control(normalized) is None


def test_generic_continue_does_not_promote_a_single_search_field():
    controls = [
        DiscoveredControl(
            control_id="search",
            semantic_label="Search",
            class_name="input",
            input_capable=True,
            locators=[DiscoveryLocator(strategy="css", value="#search", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="continue",
            semantic_label="Continue",
            class_name="button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="css", value="#continue", confidence=0.95)],
        ),
    ]

    normalized = AutopilotWebService._ensure_auth_input_semantics(controls)
    assert normalized[0].input_kind is None
    assert normalized[0].semantic_label == "Search"


def test_public_email_form_is_not_misclassified_as_authentication():
    controls = [
        DiscoveredControl(
            control_id="newsletter-email",
            semantic_label="Email",
            class_name="input",
            input_capable=True,
            input_kind="test_data",
            locators=[DiscoveryLocator(strategy="css", value="#email", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="subscribe",
            semantic_label="Subscribe",
            class_name="button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="css", value="#subscribe", confidence=0.95)],
        ),
    ]

    normalized = AutopilotWebService._ensure_auth_input_semantics(controls)

    assert AutopilotWebService._auth_submit_control(normalized) is None
    assert normalized[0].input_kind == "test_data"
    assert normalized[0].semantic_label == "Email"


def test_email_and_password_with_sign_in_are_classified_as_authentication():
    controls = [
        DiscoveredControl(
            control_id="email",
            semantic_label="Email",
            class_name="input",
            input_capable=True,
            input_kind="test_data",
            locators=[DiscoveryLocator(strategy="css", value="#email", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="password",
            semantic_label="Password",
            class_name="input",
            input_capable=True,
            input_kind="credential",
            locators=[DiscoveryLocator(strategy="css", value="#password", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="sign-in",
            semantic_label="Sign in",
            class_name="button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="css", value="#sign-in", confidence=0.95)],
        ),
    ]

    normalized = AutopilotWebService._ensure_auth_input_semantics(controls)
    inputs = [control for control in normalized if control.input_capable]

    assert [control.input_kind for control in inputs] == ["credential", "credential"]
    assert AutopilotWebService._auth_submit_control(normalized).semantic_label == "Sign in"

