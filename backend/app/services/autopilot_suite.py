"""Bounded executor for QTX Test IR.

The suite runner never executes generated Python. It interprets a small allowlist
of QTX IR actions so autonomous execution remains reviewable and safety-bounded.
Only tests already classified as ``executable`` by the IR compiler are eligible.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    AutopilotSuiteRequest,
    AutopilotSuiteResult,
    AutopilotSuiteTestResult,
    QTXIRStep,
    QTXTestIR,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.autopilot_ir import AutopilotIRCompiler


class AutopilotSuiteService:
    """Execute a bounded set of deterministic, safe QTX IR cases."""

    SUPPORTED_ACTIONS = {
        "launch_app",
        "background_app",
        "restore_app",
        "capture_evidence",
        "inspect_ui",
        "tap",
        "assert_visible",
    }

    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    async def run(
        self,
        job_id: str,
        request: AutopilotSuiteRequest,
        discovery: AutopilotDiscoveryResult | None,
    ) -> AutopilotSuiteResult:
        job = await self.prototype.load_job(job_id)
        analysis = await self.prototype.load_analysis(job_id)
        bundle = AutopilotIRCompiler().compile_bundle(analysis, discovery)

        requested_ids = set(request.test_ids)
        candidates = [
            test
            for test in bundle.tests
            if test.readiness == "executable"
            and self._supported(test)
            and (not requested_ids or test.test_id in requested_ids)
        ][: request.max_tests]

        started = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        if not candidates:
            finished = datetime.now(timezone.utc)
            return AutopilotSuiteResult(
                job_id=job_id,
                status="blocked",
                provider=request.provider,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                duration_seconds=round(time.perf_counter() - start_perf, 2),
                device_name=request.device_name,
                selected_count=0,
                error="No safe deterministic executable tests are available for the requested selection.",
            )

        apk_path = Path(job.get("apk_path") or "")
        if not apk_path.is_file() and not request.appium_app:
            raise RuntimeError("Uploaded APK artifact is unavailable for autonomous suite execution")

        app_reference = request.appium_app or str(apk_path)
        appium_url = self.prototype.resolve_appium_url(request)
        browserstack_options: Dict[str, Any] | None = None
        if request.provider == "browserstack":
            app_reference = await self.prototype._browserstack_app_url(job_id, apk_path, analysis.sha256)
            appium_url = self.settings.BROWSERSTACK_HUB_URL
            browserstack_options = {
                "userName": self.settings.BROWSERSTACK_USERNAME,
                "accessKey": self.settings.BROWSERSTACK_ACCESS_KEY,
                "projectName": self.settings.BROWSERSTACK_PROJECT_NAME,
                "buildName": f"Autopilot Suite {analysis.app_name or analysis.package_name or job['filename']}",
                "sessionName": f"Safe Suite {job_id[:8]}",
                "debug": True,
                "networkLogs": True,
            }

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._run_sync,
                    job_id,
                    appium_url,
                    app_reference,
                    request,
                    candidates,
                    analysis.package_name,
                    browserstack_options,
                    self.settings.AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS * 1000,
                ),
                timeout=self.settings.AUTOPILOT_SUITE_TIMEOUT_SECONDS,
            )
            error = None
        except Exception as exc:
            finished = datetime.now(timezone.utc)
            blocked = self.prototype._looks_like_connector_problem(exc)
            return AutopilotSuiteResult(
                job_id=job_id,
                status="blocked" if blocked else "failed",
                provider=request.provider,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                duration_seconds=round(time.perf_counter() - start_perf, 2),
                device_name=request.device_name,
                selected_count=len(candidates),
                promoted_count=sum(test.promoted_by_discovery for test in candidates),
                error=f"{type(exc).__name__}: {exc}"[:1200],
            )

        passed = sum(item.status == "passed" for item in results)
        failed = sum(item.status == "failed" for item in results)
        skipped = sum(item.status in {"skipped", "blocked"} for item in results)
        if failed == 0 and passed == len(results):
            overall = "passed"
        elif passed > 0:
            overall = "partial"
        else:
            overall = "failed"

        finished = datetime.now(timezone.utc)
        return AutopilotSuiteResult(
            job_id=job_id,
            status=overall,
            provider=request.provider,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(time.perf_counter() - start_perf, 2),
            device_name=request.device_name,
            selected_count=len(candidates),
            executed_count=len(results),
            passed_count=passed,
            failed_count=failed,
            skipped_count=skipped,
            promoted_count=sum(test.promoted_by_discovery for test in candidates),
            error=error,
            tests=results,
        )

    def _supported(self, test: QTXTestIR) -> bool:
        return bool(test.steps) and all(step.action in self.SUPPORTED_ACTIONS for step in test.steps)

    def _run_sync(
        self,
        job_id: str,
        appium_url: str,
        app_reference: str,
        request: AutopilotSuiteRequest,
        tests: list[QTXTestIR],
        package_hint: str | None,
        browserstack_options: Dict[str, Any] | None,
        install_timeout_ms: int,
        server_launch_timeout_ms: int,
        adb_exec_timeout_ms: int,
    ) -> list[AutopilotSuiteTestResult]:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        capabilities: Dict[str, Any] = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:autoGrantPermissions": request.auto_grant_permissions,
            "appium:newCommandTimeout": 240,
            "appium:androidInstallTimeout": install_timeout_ms,
            "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
            "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
            "appium:adbExecTimeout": adb_exec_timeout_ms,
            "appium:appWaitDuration": adb_exec_timeout_ms,
        }
        if request.platform_version:
            capabilities["appium:platformVersion"] = request.platform_version
        if browserstack_options:
            capabilities["bstack:options"] = browserstack_options

        evidence_root = self.prototype._job_dir(job_id) / "evidence" / "suite"
        evidence_root.mkdir(parents=True, exist_ok=True)
        driver = webdriver.Remote(appium_url, options=UiAutomator2Options().load_capabilities(capabilities))
        results: list[AutopilotSuiteTestResult] = []
        try:
            time.sleep(2)
            package = package_hint or getattr(driver, "current_package", None)
            for test in tests:
                test_started = time.perf_counter()
                evidence_dir = evidence_root / self._safe_name(test.test_id)
                evidence_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self._reset_to_application(driver, package)
                    evidence = self._execute_test(driver, test, evidence_dir, package)
                    status = "passed"
                    error = None
                except Exception as exc:
                    evidence = {
                        "package": getattr(driver, "current_package", None),
                        "activity": getattr(driver, "current_activity", None),
                    }
                    status = "failed"
                    error = f"{type(exc).__name__}: {exc}"[:1200]
                    try:
                        driver.get_screenshot_as_file(str(evidence_dir / "failure.png"))
                    except Exception:
                        pass
                results.append(
                    AutopilotSuiteTestResult(
                        test_id=test.test_id,
                        title=test.title,
                        status=status,
                        duration_seconds=round(time.perf_counter() - test_started, 2),
                        error=error,
                        evidence=evidence,
                    )
                )
            return results
        finally:
            driver.quit()

    @staticmethod
    def _reset_to_application(driver, package: str | None) -> None:
        if not package:
            return
        try:
            driver.terminate_app(package)
            time.sleep(0.5)
            driver.activate_app(package)
            time.sleep(1.2)
        except Exception:
            # Some remote providers restrict lifecycle APIs; if the target app is
            # already foreground, continuing is safer than failing the whole suite.
            if getattr(driver, "current_package", None) != package:
                raise

    def _execute_test(self, driver, test: QTXTestIR, evidence_dir: Path, package: str | None) -> Dict[str, Any]:
        from appium.webdriver.common.appiumby import AppiumBy

        locator_map = {
            "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
            "id": AppiumBy.ID,
            "xpath": AppiumBy.XPATH,
        }
        actions: list[dict[str, Any]] = []
        for index, step in enumerate(test.steps, start=1):
            if step.action == "launch_app":
                if package and getattr(driver, "current_package", None) != package:
                    driver.activate_app(package)
                    time.sleep(1)
            elif step.action == "inspect_ui":
                source = driver.page_source or ""
                if not source.strip():
                    raise AssertionError("No readable Android UI hierarchy was returned")
            elif step.action == "background_app":
                driver.background_app(2)
                time.sleep(0.5)
            elif step.action == "restore_app":
                if not package:
                    raise AssertionError("Unable to determine application package for restore")
                driver.activate_app(package)
                time.sleep(1)
                if getattr(driver, "current_package", None) != package:
                    raise AssertionError("Application did not recover to foreground")
            elif step.action in {"tap", "assert_visible"}:
                element = self._find_semantic_element(driver, step, locator_map)
                if step.action == "tap":
                    if not element.is_enabled():
                        raise AssertionError(f"Resolved control is disabled: {step.target}")
                    element.click()
                    time.sleep(0.9)
                elif not element.is_displayed():
                    raise AssertionError(f"Resolved control is not visible: {step.target}")
            elif step.action == "capture_evidence":
                screenshot = evidence_dir / f"step-{index:02d}.png"
                source_path = evidence_dir / f"step-{index:02d}.xml"
                driver.get_screenshot_as_file(str(screenshot))
                source_path.write_text(driver.page_source or "", encoding="utf-8")
            else:
                raise RuntimeError(f"IR action is not permitted by the safe suite runner: {step.action}")
            actions.append({
                "action": step.action,
                "target": step.target,
                "screen_id": step.screen_id,
                "locator_confidence": step.locator_confidence,
            })

        return {
            "package": getattr(driver, "current_package", None),
            "activity": getattr(driver, "current_activity", None),
            "actions": actions,
            "evidence_dir": str(evidence_dir),
        }

    @staticmethod
    def _find_semantic_element(driver, step: QTXIRStep, locator_map: Dict[str, str]):
        if not step.locator_strategy or not step.locator_value:
            raise AssertionError(f"Missing deterministic locator for semantic target: {step.target}")
        if step.locator_strategy not in locator_map:
            raise AssertionError(f"Unsupported locator strategy: {step.locator_strategy}")
        return driver.find_element(locator_map[step.locator_strategy], step.locator_value)

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:100]
