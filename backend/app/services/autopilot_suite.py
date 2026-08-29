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
    AutopilotSetupProfile,
    AutopilotSuiteRequest,
    AutopilotSuiteResult,
    AutopilotSuiteTestResult,
    QTXIRStep,
    QTXTestIR,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.appium_compat import (
    expected_package_state,
    safe_app_identity,
    safe_background_application,
    safe_page_source,
    safe_quit,
)
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
        setup: AutopilotSetupProfile | None = None,
    ) -> AutopilotSuiteResult:
        job = await self.prototype.load_job(job_id)
        analysis = await self.prototype.load_analysis(job_id)
        bundle = AutopilotIRCompiler().compile_bundle(analysis, discovery, setup)

        requested_ids = set(request.test_ids)
        requested_buckets = set(request.buckets)
        selected = [
            test
            for test in bundle.tests
            if (not requested_ids or test.test_id in requested_ids)
            and (not requested_buckets or test.bucket in requested_buckets)
        ][: request.max_tests]
        candidates = [
            test
            for test in selected
            if test.readiness == "executable" and self._supported(test)
        ]
        deferred = [test for test in selected if test not in candidates]
        deferred_results = self._deferred_results(deferred) if request.include_deferred else []

        started = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        if not selected:
            finished = datetime.now(timezone.utc)
            return AutopilotSuiteResult(
                job_id=job_id,
                status="blocked",
                provider=request.provider,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                duration_seconds=round(time.perf_counter() - start_perf, 2),
                device_name=request.device_name,
                error="No tests match the requested bucket or test selection.",
                bucket_counts={},
            )
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
                selected_count=len(selected),
                executed_count=0,
                deferred_count=len(deferred),
                skipped_count=len(deferred_results),
                bucket_counts=self._bucket_counts(selected),
                error="No safe deterministic executable tests are available; deferred cases list their dependencies.",
                tests=deferred_results,
            )

        apk_path = Path(job.get("apk_path") or "")
        app_reference = request.appium_app or str(apk_path)
        browserstack_options: Dict[str, Any] | None = None
        results: list[AutopilotSuiteTestResult]
        try:
            if not apk_path.is_file() and not request.appium_app:
                raise RuntimeError("Uploaded APK artifact is unavailable for autonomous suite execution")
            if request.provider == "browserstack":
                # BrowserStack owns the hub URL; do not resolve a local Appium
                # endpoint first. That was the source of the hosted suite error.
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
            else:
                appium_url = self.prototype.resolve_appium_url(request)
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
        except Exception as exc:
            finished = datetime.now(timezone.utc)
            blocked = self.prototype._looks_like_connector_problem(exc)
            connector_error = f"{type(exc).__name__}: {exc}"[:1200]
            failure_results = [
                AutopilotSuiteTestResult(
                    test_id=test.test_id,
                    title=test.title,
                    status="blocked",
                    bucket=test.bucket,
                    readiness=test.readiness,
                    dependency=test.dependency,
                    error=connector_error,
                )
                for test in candidates
            ]
            return AutopilotSuiteResult(
                job_id=job_id,
                status="blocked" if blocked else "failed",
                provider=request.provider,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                duration_seconds=round(time.perf_counter() - start_perf, 2),
                device_name=request.device_name,
                selected_count=len(selected),
                executed_count=0,
                deferred_count=len(deferred),
                skipped_count=len(deferred_results) + len(failure_results),
                bucket_counts=self._bucket_counts(selected),
                error=connector_error,
                tests=failure_results + deferred_results,
            )

        result_map = {item.test_id: item for item in results}
        deferred_map = {item.test_id: item for item in deferred_results}
        ordered_results: list[AutopilotSuiteTestResult] = []
        for test in selected:
            item = result_map.get(test.test_id) or deferred_map.get(test.test_id)
            if item is not None:
                ordered_results.append(item)
        passed = sum(item.status == "passed" for item in ordered_results)
        failed = sum(item.status == "failed" for item in ordered_results)
        blocked_count = sum(item.status == "blocked" for item in ordered_results)
        skipped = sum(item.status == "skipped" for item in ordered_results)
        if failed == 0 and blocked_count == 0 and skipped == 0 and passed == len(results):
            overall = "passed"
        elif passed > 0:
            overall = "partial"
        else:
            overall = "blocked" if blocked_count else "failed"

        finished = datetime.now(timezone.utc)
        return AutopilotSuiteResult(
            job_id=job_id,
            status=overall,
            provider=request.provider,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(time.perf_counter() - start_perf, 2),
            device_name=request.device_name,
            selected_count=len(selected),
            executed_count=len(results),
            deferred_count=len(deferred),
            passed_count=passed,
            failed_count=failed,
            skipped_count=skipped + blocked_count,
            promoted_count=sum(test.promoted_by_discovery for test in candidates),
            bucket_counts=self._bucket_counts(selected),
            error=None,
            tests=ordered_results,
        )

    @staticmethod
    def _bucket_counts(tests: list[QTXTestIR]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for test in tests:
            counts[test.bucket] = counts.get(test.bucket, 0) + 1
        return counts

    @staticmethod
    def _deferred_results(tests: list[QTXTestIR]) -> list[AutopilotSuiteTestResult]:
        return [
            AutopilotSuiteTestResult(
                test_id=test.test_id,
                title=test.title,
                status="blocked",
                bucket=test.bucket,
                readiness=test.readiness,
                dependency=test.dependency or test.readiness_reason,
                error=test.readiness_reason or "This case is pending setup or safe deterministic locators.",
            )
            for test in tests
        ]

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
            initial_source = safe_page_source(driver)
            package = safe_app_identity(
                driver,
                page_source=initial_source,
                package_hint=package_hint,
            )["package"]
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
                    evidence = safe_app_identity(
                        driver,
                        page_source=safe_page_source(driver),
                        package_hint=package,
                    )
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
                        bucket=test.bucket,
                        readiness=test.readiness,
                        dependency=test.dependency,
                        duration_seconds=round(time.perf_counter() - test_started, 2),
                        error=error,
                        evidence=evidence,
                    )
                )
            return results
        finally:
            safe_quit(driver)

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
            if expected_package_state(driver, package) is not True:
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
                if package and expected_package_state(driver, package) is not True:
                    driver.activate_app(package)
                    time.sleep(1)
            elif step.action == "inspect_ui":
                source = driver.page_source or ""
                if not source.strip():
                    raise AssertionError("No readable Android UI hierarchy was returned")
            elif step.action == "background_app":
                safe_background_application(driver, 2)
                time.sleep(0.5)
            elif step.action == "restore_app":
                if not package:
                    raise AssertionError("Unable to determine application package for restore")
                driver.activate_app(package)
                time.sleep(1)
                if expected_package_state(driver, package) is not True:
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

        identity = safe_app_identity(
            driver,
            page_source=safe_page_source(driver),
            package_hint=package,
        )
        return {
            "package": identity["package"],
            "activity": identity["activity"],
            "identity_source": identity["identity_source"],
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

