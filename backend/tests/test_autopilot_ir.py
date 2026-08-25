from app.schemas.autopilot import AutopilotAnalysis, AutopilotTest
from app.services.autopilot_ir import AutopilotIRCompiler


def _analysis(tests):
    return AutopilotAnalysis(
        job_id="11111111-1111-1111-1111-111111111111",
        filename="demo.apk",
        package_name="com.qtxpert.demo",
        sha256="0" * 64,
        tests=tests,
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
    assert generated.schema_version == "qtx-ir/0.1"
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

    bundle = AutopilotIRCompiler().compile_bundle(analysis)

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
