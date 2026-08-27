from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotDiscoveryResult,
    AutopilotTest,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
)
from app.services.autopilot_ir import AutopilotIRCompiler


def _analysis(tests):
    return AutopilotAnalysis(
        job_id="11111111-1111-1111-1111-111111111111",
        filename="demo.apk",
        package_name="com.qtxpert.demo",
        sha256="0" * 64,
        tests=tests,
    )


def _control(control_id, label, *, risk="safe", clickable=True, locator="id", value=None):
    return DiscoveredControl(
        control_id=control_id,
        semantic_label=label,
        class_name="android.widget.Button",
        text=label,
        resource_id=value or f"com.qtxpert.demo:id/{control_id}",
        clickable=clickable,
        enabled=True,
        risk=risk,
        locators=[DiscoveryLocator(strategy=locator, value=value or f"com.qtxpert.demo:id/{control_id}", confidence=0.97)],
    )


def _discovery():
    login = _control("login", "Sign in")
    help_control = _control("help", "Help")
    support = _control("support", "Support")
    transfer = _control("transfer", "Transfer money", risk="blocked")
    return AutopilotDiscoveryResult(
        job_id="11111111-1111-1111-1111-111111111111",
        status="completed",
        provider="appium",
        started_at="2026-08-27T00:00:00+00:00",
        finished_at="2026-08-27T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=2,
        control_count=4,
        safe_control_count=3,
        blocked_control_count=1,
        screens=[
            DiscoveredScreen(
                screen_id="screen-001",
                fingerprint="a" * 64,
                package_name="com.qtxpert.demo",
                activity_name=".MainActivity",
                controls=[login, help_control, transfer],
            ),
            DiscoveredScreen(
                screen_id="screen-002",
                fingerprint="b" * 64,
                package_name="com.qtxpert.demo",
                activity_name=".HelpActivity",
                controls=[support],
            ),
        ],
        transitions=[
            DiscoveredTransition(
                from_screen_id="screen-001",
                to_screen_id="screen-002",
                control_id="help",
                control_label="Help",
            )
        ],
    )


def test_qtx_ir_compiles_safe_smoke_to_executable_appium_python():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AUTO-SMOKE-001",
            suite="Smoke",
            title="Install and cold-launch application",
            priority="critical",
            objective="Launch safely",
            steps=["Launch"],
            expected=["Foreground package exists"],
        )
    ])

    bundle = AutopilotIRCompiler().compile_bundle(analysis)

    assert bundle.executable_count == 1
    assert bundle.discovery_required_count == 0
    generated = bundle.tests[0]
    assert generated.readiness == "executable"
    assert generated.schema_version == "qtx-ir/0.2"
    assert any(step.action == "capture_evidence" for step in generated.steps)
    compile(generated.appium_python, "<qtx-generated>", "exec")


def test_qtx_ir_does_not_fake_executability_before_runtime_discovery():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AI-001",
            suite="Functional",
            title="Authenticate retail customer",
            priority="critical",
            objective="Validate login",
            steps=["Tap Login", "Enter username", "Submit"],
            expected=["Dashboard is displayed"],
            source="ai",
        )
    ])

    bundle = AutopilotIRCompiler().compile_bundle(analysis)

    assert bundle.executable_count == 0
    assert bundle.discovery_required_count == 1
    generated = bundle.tests[0]
    assert generated.readiness == "discovery_required"
    assert "Runtime screen/element discovery" in generated.appium_python
    compile(generated.appium_python, "<qtx-generated>", "exec")


def test_qtx_ir_requires_approval_for_destructive_business_action():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AI-002",
            suite="Payments",
            title="Submit live transfer",
            priority="critical",
            objective="Validate transfer",
            steps=["Submit transfer"],
            expected=["Transfer completes"],
            source="ai",
            destructive=True,
            autonomous=False,
        )
    ])

    bundle = AutopilotIRCompiler().compile_bundle(analysis, _discovery())

    assert bundle.approval_required_count == 1
    generated = bundle.tests[0]
    assert generated.readiness == "approval_required"
    assert all(step.safe_for_autopilot is False for step in generated.steps)
    assert "Explicit customer approval" in generated.appium_python
    compile(generated.appium_python, "<qtx-generated>", "exec")


def test_qtx_ir_background_recovery_is_executable_and_uses_package_hint():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AUTO-SMOKE-002",
            suite="Smoke",
            title="Background and foreground recovery",
            priority="high",
            objective="Validate lifecycle",
            steps=["Background", "Restore"],
            expected=["Application recovers"],
        )
    ])

    generated = AutopilotIRCompiler().compile_bundle(analysis).tests[0]

    assert generated.readiness == "executable"
    assert "com.qtxpert.demo" in generated.appium_python
    assert "background_app" in generated.appium_python
    assert "activate_app" in generated.appium_python
    compile(generated.appium_python, "<qtx-generated>", "exec")


def test_runtime_discovery_promotes_resolved_safe_journey():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AI-010",
            suite="Navigation",
            title="Open help and verify support",
            priority="medium",
            objective="Validate support navigation",
            steps=["Open Help", "Verify Support"],
            expected=["Support is visible"],
            source="ai",
        )
    ])

    bundle = AutopilotIRCompiler().compile_bundle(analysis, _discovery())
    generated = bundle.tests[0]

    assert bundle.discovery_used is True
    assert bundle.promoted_count == 1
    assert generated.readiness == "executable"
    assert generated.promoted_by_discovery is True
    assert [step.action for step in generated.steps[:2]] == ["tap", "assert_visible"]
    assert generated.steps[0].screen_id == "screen-001"
    assert generated.steps[1].screen_id == "screen-002"
    assert generated.steps[0].locator_confidence == 0.97
    compile(generated.appium_python, "<qtx-generated>", "exec")


def test_input_dependent_journey_remains_discovery_required_after_discovery():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AI-011",
            suite="Authentication",
            title="Sign in",
            priority="critical",
            objective="Authenticate",
            steps=["Tap Sign in", "Enter username"],
            expected=["Home is visible"],
            source="ai",
        )
    ])

    generated = AutopilotIRCompiler().compile_bundle(analysis, _discovery()).tests[0]

    assert generated.readiness == "discovery_required"
    assert generated.promoted_by_discovery is False
    assert "Input/test-data step" in (generated.readiness_reason or "")


def test_blocked_control_cannot_be_promoted_to_tap():
    analysis = _analysis([
        AutopilotTest(
            id="QT-AI-012",
            suite="Payments",
            title="Open transfer",
            priority="high",
            objective="Navigate to transfer",
            steps=["Tap Transfer money", "Verify Transfer money"],
            expected=["Transfer money is visible"],
            source="ai",
        )
    ])

    generated = AutopilotIRCompiler().compile_bundle(analysis, _discovery()).tests[0]

    assert generated.readiness == "discovery_required"
    assert generated.promoted_by_discovery is False
    assert "No high-confidence safe control" in (generated.readiness_reason or "")
