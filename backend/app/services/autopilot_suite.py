"""Bounded executor for QTX Test IR.

The suite runner never executes generated Python. It interprets a small allowlist
of QTX IR actions so autonomous execution remains reviewable and safety-bounded.
Only tests already classified as ``executable`` by the IR compiler are eligible.
"""
from __future__ import annotations

import asyncio
import base64
import re
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
    ProviderLifecycleUnavailable,
    expected_package_state,
    safe_app_identity,
    safe_background_application,
    safe_page_source,
    safe_quit,
    validate_target_surface,
)
from app.services.autopilot_ir import AutopilotIRCompiler


class AutopilotSuiteService:
    """Execute a bounded set of deterministic, safe QTX IR cases."""

    SUPPORTED_ACTIONS = {
        "launch_app",
        "background_app",
        "restore_app",
        "scroll",
        "capture_evidence",
        "inspect_ui",
        "wait_for_state",
        "tap",
        "click",
        "fill",
        "clear",
        "select",
        "press",
        "reset",
        "assert_visible",
        "assert_text",
        "assert_validation_feedback",
    }
    # Record only user-journey coverage.  Installation, discovery, security
    # and performance checks keep their lighter screenshot/XML evidence.
    VIDEO_BUCKETS = frozenset({
        "functional",
        "functional_positive",
        "functional_negative",
        "uat",
    })

    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    async def run(
        self,
        job_id: str,
        request: AutopilotSuiteRequest,
        discovery: AutopilotDiscoveryResult | None,
        setup: AutopilotSetupProfile | None = None,
        input_values: Dict[str, str] | None = None,
        sensitive_input_keys: set[str] | None = None,
    ) -> AutopilotSuiteResult:
        job = await self.prototype.load_job(job_id)
        analysis = await self.prototype.load_analysis(job_id)
        target_kind = str(job.get("target_kind") or analysis.target_kind or "android")
        if request.target_kind != target_kind:
            request = request.model_copy(update={"target_kind": target_kind})
        bundle = AutopilotIRCompiler().compile_bundle(
            analysis,
            discovery,
            setup,
            input_values=input_values,
        )

        requested_ids = set(request.test_ids)
        requested_buckets = set(request.buckets)
        selected = [
            test
            for test in bundle.tests
            if (not requested_ids or test.test_id in requested_ids)
            and (not requested_buckets or test.bucket in requested_buckets)
        ]
        selected.sort(key=lambda test: not (test.readiness == "executable" and self._supported(test)))
        selected = selected[: request.max_tests]
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
                target_kind=target_kind,
                target_url=job.get("target_url"),
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
                target_kind=target_kind,
                target_url=job.get("target_url"),
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
                    input_values=input_values or {},
                    sensitive_input_keys=sensitive_input_keys or set(),
                    discovery=discovery,
                ),
                timeout=self.settings.AUTOPILOT_SUITE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            finished = datetime.now(timezone.utc)
            # A session that is connected to the provider but showing system
            # UI is a lifecycle/target failure, not a test assertion failure.
            # Keep it blocked and expose the actionable provider diagnostic to
            # the report instead of counting any platform check as a pass.
            blocked = isinstance(exc, ProviderLifecycleUnavailable) or self.prototype._looks_like_connector_problem(exc)
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
                    journey=test.journey,
                    page_label=test.page_label,
                    page_url=test.page_url,
                )
                for test in candidates
            ]
            return AutopilotSuiteResult(
                job_id=job_id,
                status="blocked" if blocked else "failed",
                target_kind=target_kind,
                target_url=job.get("target_url"),
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
            target_kind=target_kind,
            target_url=job.get("target_url"),
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
                journey=test.journey,
                page_label=test.page_label,
                page_url=test.page_url,
            )
            for test in tests
        ]

    def _supported(self, test: QTXTestIR) -> bool:
        return bool(test.steps) and all(step.action in self.SUPPORTED_ACTIONS for step in test.steps)

    @classmethod
    def _is_video_case(cls, test: QTXTestIR) -> bool:
        """Return whether a case belongs to the functional journey evidence scope."""

        return test.bucket in cls.VIDEO_BUCKETS

    @staticmethod
    def _test_touches_sensitive_input(
        test: QTXTestIR,
        input_values: Dict[str, str],
        sensitive_input_keys: set[str],
    ) -> bool:
        """Conservatively identify a case that could render a secret on screen."""

        return any(
            step.action == "fill"
            and step.input_key in sensitive_input_keys
            and step.input_key in input_values
            for step in test.steps
        )

    def _start_video_recording(self, driver) -> tuple[bool, str]:
        """Start Appium screen recording without making it a test failure.

        Appium and hosted device providers expose slightly different method
        signatures. Try the bounded form first, then progressively simpler
        calls. An unsupported recording endpoint is reported as metadata only;
        the functional test itself continues to run.
        """

        starter = getattr(driver, "start_recording_screen", None)
        if not callable(starter):
            return False, "unsupported"
        bounded = {
            "time_limit": self.settings.AUTOPILOT_VIDEO_MAX_SECONDS * 1000,
            "video_size": f"{self.settings.AUTOPILOT_VIDEO_WIDTH}x{self.settings.AUTOPILOT_VIDEO_HEIGHT}",
            "bit_rate": self.settings.AUTOPILOT_VIDEO_BIT_RATE,
            "video_fps": self.settings.AUTOPILOT_VIDEO_FPS,
        }
        for kwargs in (bounded, {"time_limit": bounded["time_limit"]}, {}):
            try:
                starter(**kwargs)
                return True, "recording"
            except TypeError:
                continue
            except Exception:
                # A provider may reject one optional capability while still
                # accepting a simpler form. Never echo the provider message,
                # which can contain command arguments.
                continue
        return False, "unsupported"

    def _stop_video_recording(
        self,
        driver,
        path: Path,
        *,
        suppress: bool,
    ) -> tuple[Path | None, str]:
        """Stop and materialize a bounded Appium recording, if available."""

        stopper = getattr(driver, "stop_recording_screen", None)
        if not callable(stopper):
            return None, "unsupported"
        try:
            payload = stopper()
        except Exception:
            return None, "stop_failed"
        if suppress:
            return None, "suppressed_sensitive_input"
        if not payload:
            return None, "empty"
        if isinstance(payload, bytes):
            # The Appium client normally returns an ASCII base64 string, but a
            # few custom endpoints return decoded bytes.  Decode only when the
            # byte payload is valid base64; otherwise preserve the bytes as-is.
            raw = payload
            try:
                encoded = b"".join(payload.split()).decode("ascii")
                decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
                if decoded:
                    raw = decoded
            except Exception:
                pass
        else:
            try:
                encoded = str(payload).strip()
                if "," in encoded and encoded.lower().startswith("data:"):
                    encoded = encoded.split(",", 1)[1]
                raw = base64.b64decode(encoded.encode("ascii"), validate=False)
            except Exception:
                raw = b""
        if not raw:
            return None, "invalid"
        if len(raw) > self.settings.AUTOPILOT_VIDEO_MAX_BYTES:
            return None, "too_large"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        except OSError:
            return None, "write_failed"
        return path, "captured"

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
        input_values: Dict[str, str] | None = None,
        sensitive_input_keys: set[str] | None = None,
        discovery: AutopilotDiscoveryResult | None = None,
    ) -> list[AutopilotSuiteTestResult]:
        from appium import webdriver

        input_values = input_values or {}
        sensitive_input_keys = sensitive_input_keys or set()

        is_ios = request.target_kind == "ios"
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:newCommandTimeout": 240,
        }
        if package_hint:
            capabilities["appium:appPackage"] = package_hint
        if is_ios:
            capabilities.update(
                {
                    "appium:wdaLaunchTimeout": server_launch_timeout_ms,
                    "appium:wdaConnectionTimeout": adb_exec_timeout_ms,
                    "appium:useNewWDA": False,
                }
            )
        else:
            capabilities.update(
                {
                    "appium:autoGrantPermissions": request.auto_grant_permissions,
                    "appium:androidInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
                    "appium:adbExecTimeout": adb_exec_timeout_ms,
                    "appium:appWaitDuration": adb_exec_timeout_ms,
                }
            )
        if request.platform_version:
            capabilities["appium:platformVersion"] = request.platform_version
        if browserstack_options:
            capabilities["bstack:options"] = browserstack_options

        evidence_root = self.prototype._job_dir(job_id) / "evidence" / "suite"
        evidence_root.mkdir(parents=True, exist_ok=True)
        if is_ios:
            from appium.options.ios import XCUITestOptions

            options = XCUITestOptions().load_capabilities(capabilities)
        else:
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options().load_capabilities(capabilities)
        driver = webdriver.Remote(appium_url, options=options)
        results: list[AutopilotSuiteTestResult] = []
        try:
            time.sleep(2)
            initial_source = safe_page_source(driver)
            identity = safe_app_identity(
                driver,
                page_source=initial_source,
                package_hint=package_hint,
            )
            package = identity["package"]
            target_ready, target_reason, _ = validate_target_surface(
                driver,
                expected_package=package_hint,
                page_source=initial_source,
            )
            if not target_ready:
                raise ProviderLifecycleUnavailable(target_reason)
            for test in tests:
                test_started = time.perf_counter()
                evidence_dir = evidence_root / self._safe_name(test.test_id)
                evidence_dir.mkdir(parents=True, exist_ok=True)
                evidence: Dict[str, Any] = {}
                video_requested = self._is_video_case(test)
                video_started = False
                video_status: str | None = None
                sensitive_touched = self._test_touches_sensitive_input(
                    test,
                    input_values,
                    sensitive_input_keys,
                )
                try:
                    if video_requested:
                        video_started, video_status = self._start_video_recording(driver)
                    self._reset_to_application(driver, package)
                    case_target_ready, case_target_reason, _ = validate_target_surface(
                        driver,
                        expected_package=package,
                        page_source=safe_page_source(driver),
                    )
                    if not case_target_ready:
                        raise ProviderLifecycleUnavailable(case_target_reason)
                    if self._would_repeat_failed_auth_submission(test, discovery):
                        raise ProviderLifecycleUnavailable(
                            "Runtime Discovery already tried the approved sign-in once but remained on the "
                            "sign-in screen. Saved credentials were not submitted again during this safe batch; "
                            "verify the UAT account or any additional sign-in verification before retrying."
                        )
                    setup_navigation = self._prepare_test_screen(
                        driver,
                        test,
                        discovery,
                        package,
                    )
                    evidence = self._execute_test(
                        driver,
                        test,
                        evidence_dir,
                        package,
                        request.target_kind,
                        input_values=input_values,
                        sensitive_input_keys=sensitive_input_keys,
                    )
                    if setup_navigation:
                        evidence["setup_navigation"] = setup_navigation
                    status = "passed"
                    error = None
                    dependency = test.dependency
                except ProviderLifecycleUnavailable as exc:
                    evidence = safe_app_identity(
                        driver,
                        page_source=safe_page_source(driver),
                        package_hint=package,
                    )
                    # Keep the evidence location internal; the API route
                    # replaces it with repository asset IDs before returning
                    # the durable result.
                    evidence["evidence_dir"] = str(evidence_dir)
                    status = "blocked"
                    error = str(exc)[:1200]
                    dependency = str(exc)[:1200]
                except Exception as exc:
                    evidence = safe_app_identity(
                        driver,
                        page_source=safe_page_source(driver),
                        package_hint=package,
                    )
                    evidence["evidence_dir"] = str(evidence_dir)
                    status = "failed"
                    error = f"{type(exc).__name__}: {exc}"[:1200]
                    dependency = test.dependency
                    # A password/OTP may be rendered in the native hierarchy
                    # while a failure screenshot is captured. Suppress that
                    # artifact whenever this test touched a sensitive input.
                    if not sensitive_touched:
                        try:
                            driver.get_screenshot_as_file(str(evidence_dir / "failure.png"))
                        except Exception:
                            pass
                finally:
                    if video_requested:
                        if video_started:
                            video_path, stopped_status = self._stop_video_recording(
                                driver,
                                evidence_dir / "functional-journey.mp4",
                                suppress=sensitive_touched,
                            )
                            video_status = stopped_status
                            if video_path is not None:
                                evidence["video_path"] = str(video_path)
                        if video_status and video_status != "captured":
                            evidence["video_status"] = video_status
                        elif video_status == "captured":
                            evidence["video_status"] = "captured"
                results.append(
                    AutopilotSuiteTestResult(
                        test_id=test.test_id,
                        title=test.title,
                        status=status,
                        bucket=test.bucket,
                        readiness=test.readiness,
                        dependency=dependency,
                        duration_seconds=round(time.perf_counter() - test_started, 2),
                        error=error,
                        evidence=evidence,
                        journey=test.journey,
                        page_label=test.page_label,
                        page_url=test.page_url,
                    )
                )
            return results
        finally:
            safe_quit(driver)

    @staticmethod
    def _reset_to_application(driver, package: str | None) -> None:
        if not package:
            return
        # A hosted device can preserve the app's navigation state even when a
        # new session is created with ``noReset=false``.  Replayable runtime
        # cases must start from the same launch state that Discovery observed,
        # otherwise a locator from the first screen is searched on a later
        # screen and is reported as a misleading NoSuchElementException.
        resetter = getattr(driver, "reset", None)
        provider_reset_succeeded = False
        if callable(resetter):
            try:
                resetter()
                provider_reset_succeeded = True
                time.sleep(1.8)
            except Exception:
                # BrowserStack and some local providers do not expose the
                # optional reset endpoint. Fall back to the portable lifecycle
                # sequence below.
                pass

        # A number of hosted Android drivers implement ``reset`` as a session
        # reset but keep the last activity/view in the foreground.  That makes
        # a locator observed on the discovery root disappear on the next case
        # and is reported as a misleading NoSuchElementException.  Always use
        # the portable terminate/activate pair when it is available, even
        # after a provider reset, so every replay starts at a cold app entry
        # point.  If a provider restricts either lifecycle call, retain the
        # successful reset and continue rather than turning capability limits
        # into a suite failure.
        terminator = getattr(driver, "terminate_app", None)
        activator = getattr(driver, "activate_app", None)
        if callable(terminator) and callable(activator):
            try:
                terminator(package)
                time.sleep(0.5)
                activator(package)
                time.sleep(2.0)
                if expected_package_state(driver, package) is not False:
                    return
            except Exception:
                if provider_reset_succeeded and expected_package_state(driver, package) is not False:
                    return

        # A provider reset is still preferable to an unsupported lifecycle
        # sequence.  Some drivers do not expose package identity immediately;
        # an unknown state must not trigger a second unsupported call.
        if provider_reset_succeeded and expected_package_state(driver, package) is not False:
            return
        try:
            if not callable(terminator):
                driver.terminate_app(package)
            time.sleep(0.5)
            if not callable(activator):
                driver.activate_app(package)
            time.sleep(2.0)
        except Exception:
            # Some remote providers restrict lifecycle APIs; if the target app is
            # already foreground, continuing is safer than failing the whole suite.
            if expected_package_state(driver, package) is not True:
                raise


    @staticmethod
    def _auth_submit_label(value: str | None) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
        return normalized in {
            "login",
            "log in",
            "sign in",
            "sign in to account",
            "continue to account",
            "continue",
            "next",
            "unlock",
            "authenticate",
            "submit",
        }

    @classmethod
    def _would_repeat_failed_auth_submission(
        cls,
        test: QTXTestIR,
        discovery: AutopilotDiscoveryResult | None,
    ) -> bool:
        if not discovery or "sign-in returned to the same screen" not in (discovery.stop_reason or "").casefold():
            return False
        screens = {screen.screen_id: screen for screen in discovery.screens}
        for step in test.steps:
            if step.action not in {"tap", "click"} or not step.screen_id:
                continue
            screen = screens.get(step.screen_id)
            if screen is None:
                continue
            credentials_present = any(
                control.input_capable
                and control.input_kind == "credential"
                and control.enabled
                for control in screen.controls
            )
            if not credentials_present:
                continue
            control = next(
                (
                    item
                    for item in screen.controls
                    if (
                        step.locator_strategy
                        and step.locator_value
                        and any(
                            locator.strategy == step.locator_strategy
                            and locator.value == step.locator_value
                            for locator in item.locators
                        )
                    )
                    or (
                        step.target
                        and cls._normalize_screen_text(item.semantic_label)
                        == cls._normalize_screen_text(step.target)
                    )
                ),
                None,
            )
            if control and cls._auth_submit_label(control.semantic_label):
                return True
        return False

    @staticmethod
    def _normalize_screen_text(value: str | None) -> str:
        return re.sub(r"\\s+", " ", str(value or "").casefold().replace("_", " ").replace("-", " ")).strip()

    @classmethod
    def _screen_tokens(cls, screen) -> set[str]:
        generic = {
            "button", "view", "control", "image", "imageview", "textview", "edittext",
            "field", "input", "container", "scrollview", "linearlayout", "framelayout",
        }
        tokens: set[str] = set()
        for control in screen.controls:
            for value in (
                control.semantic_label,
                control.text,
                control.content_description,
                control.resource_id,
            ):
                token = cls._normalize_screen_text(value)
                if len(token) < 3 or token in generic:
                    continue
                tokens.add(token)
                if "/" in token:
                    suffix = token.rsplit("/", 1)[-1]
                    if len(suffix) >= 3 and suffix not in generic:
                        tokens.add(suffix)
        return tokens

    @classmethod
    def _identify_discovered_screen(
        cls,
        driver,
        discovery: AutopilotDiscoveryResult,
        package: str | None,
    ):
        from app.services.autopilot_discovery import AutopilotDiscoveryService

        source = safe_page_source(driver)
        identity = safe_app_identity(driver, page_source=source, package_hint=package)
        try:
            controls = AutopilotDiscoveryService.parse_controls(source or "")
            fingerprint = AutopilotDiscoveryService.fingerprint(
                identity.get("package"),
                identity.get("activity"),
                controls,
            )
            exact = next(
                (screen for screen in discovery.screens if screen.fingerprint == fingerprint),
                None,
            )
            if exact is not None:
                return exact
        except Exception:
            pass

        haystack = cls._normalize_screen_text(source)
        ranked: list[tuple[float, int, object]] = []
        for screen in discovery.screens:
            tokens = cls._screen_tokens(screen)
            if not tokens:
                continue
            matches = sum(token in haystack for token in tokens)
            ranked.append((matches / len(tokens), matches, screen))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not ranked:
            return None
        score, matches, best = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if matches >= 2 and score >= 0.40 and score - runner_up >= 0.10:
            return best
        return None

    @classmethod
    def _safe_discovery_path(
        cls,
        discovery: AutopilotDiscoveryResult,
        start_screen_id: str,
        target_screen_id: str,
    ):
        if start_screen_id == target_screen_id:
            return []
        screens = {screen.screen_id: screen for screen in discovery.screens}
        if start_screen_id not in screens or target_screen_id not in screens:
            return None
        queue: list[tuple[str, list[tuple[object, object]]]] = [(start_screen_id, [])]
        visited = {start_screen_id}
        while queue:
            source_id, path = queue.pop(0)
            source = screens[source_id]
            credential_screen = any(
                control.input_capable
                and control.input_kind == "credential"
                and control.enabled
                for control in source.controls
            )
            for transition in discovery.transitions:
                if (
                    transition.from_screen_id != source_id
                    or transition.to_screen_id not in screens
                    or transition.duplicate_state
                    or transition.action != "tap"
                    or transition.to_screen_id in visited
                ):
                    continue
                control = next(
                    (item for item in source.controls if item.control_id == transition.control_id),
                    None,
                )
                if (
                    control is None
                    or not control.clickable
                    or not control.enabled
                    or control.input_capable
                    or control.risk != "safe"
                ):
                    continue
                if credential_screen and cls._auth_submit_label(transition.control_label):
                    continue
                next_path = path + [(transition, control)]
                if transition.to_screen_id == target_screen_id:
                    return next_path
                visited.add(transition.to_screen_id)
                queue.append((transition.to_screen_id, next_path))
        return None

    @staticmethod
    def _step_locator_available(driver, step: QTXIRStep, locator_map: Dict[str, str]) -> bool:
        candidates = []
        if step.locator_strategy and step.locator_value and step.locator_strategy in locator_map:
            candidates.append((step.locator_strategy, step.locator_value))
        candidates.extend(
            (item.strategy, item.value)
            for item in step.locator_fallbacks
            if item.strategy in locator_map
            and (item.strategy, item.value) not in candidates
        )
        for strategy, value in candidates:
            try:
                element = driver.find_element(locator_map[strategy], value)
                if not hasattr(element, "is_displayed") or element.is_displayed():
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _route_control_element(driver, control, locator_map: Dict[str, str]):
        priority = {"id": 0, "accessibility_id": 1, "xpath": 2, "css": 3}
        candidates = sorted(
            (
                item for item in control.locators
                if item.strategy in locator_map and item.confidence >= 0.70
            ),
            key=lambda item: (-item.confidence, priority.get(item.strategy, 10), item.value),
        )
        for locator in candidates:
            try:
                element = driver.find_element(locator_map[locator.strategy], locator.value)
                if hasattr(element, "is_enabled") and not element.is_enabled():
                    continue
                if hasattr(element, "is_displayed") and not element.is_displayed():
                    continue
                return element
            except Exception:
                continue
        return None

    def _prepare_test_screen(
        self,
        driver,
        test: QTXTestIR,
        discovery: AutopilotDiscoveryResult | None,
        package: str | None,
    ) -> list[dict[str, str]]:
        if not discovery or not discovery.screens:
            return []
        entry_step = next(
            (
                step for step in test.steps
                if step.screen_id and step.locator_strategy and step.locator_value
            ),
            next((step for step in test.steps if step.screen_id), None),
        )
        if entry_step is None:
            return []
        target = next(
            (screen for screen in discovery.screens if screen.screen_id == entry_step.screen_id),
            None,
        )
        if target is None:
            raise ProviderLifecycleUnavailable(
                "This case refers to a screen that is not present in the saved discovery map. Run discovery again."
            )

        from appium.webdriver.common.appiumby import AppiumBy

        locator_map = {
            "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
            "id": AppiumBy.ID,
            "xpath": AppiumBy.XPATH,
        }
        has_locator = bool(entry_step.locator_strategy and entry_step.locator_value)
        deadline = time.monotonic() + 10.0
        current = None
        while time.monotonic() < deadline:
            if has_locator and self._step_locator_available(driver, entry_step, locator_map):
                current = self._identify_discovered_screen(driver, discovery, package)
                if current is None or current.screen_id == target.screen_id:
                    return []
            current = self._identify_discovered_screen(driver, discovery, package)
            if current is not None:
                break
            time.sleep(0.5)

        if current is None:
            raise ProviderLifecycleUnavailable(
                "The app opened, but Autopilot could not match the current screen to the saved discovery map. "
                "No test action was taken."
            )
        if current.screen_id == target.screen_id:
            if has_locator and not self._step_locator_available(driver, entry_step, locator_map):
                raise ProviderLifecycleUnavailable(
                    f"The observed screen {target.page_label or target.screen_id} was restored, but its "
                    "saved control locator is no longer present. No test action was taken."
                )
            return []

        path = self._safe_discovery_path(discovery, current.screen_id, target.screen_id)
        if path is None:
            raise ProviderLifecycleUnavailable(
                f"No safe, observed navigation path leads from {current.page_label or current.screen_id} "
                f"to {target.page_label or target.screen_id}. The case was not attempted."
            )

        navigation: list[dict[str, str]] = []
        for transition, control in path:
            element = self._route_control_element(driver, control, locator_map)
            if element is None:
                raise ProviderLifecycleUnavailable(
                    f"The observed navigation control {control.semantic_label} is no longer available. "
                    "The case was not attempted."
                )
            element.click()
            time.sleep(0.6)
            target_screen = next(
                screen for screen in discovery.screens if screen.screen_id == transition.to_screen_id
            )
            reached = None
            step_deadline = time.monotonic() + 8.0
            while time.monotonic() < step_deadline:
                if package:
                    target_ready, target_reason, _ = validate_target_surface(
                        driver,
                        expected_package=package,
                        page_source=safe_page_source(driver),
                    )
                    if not target_ready:
                        raise ProviderLifecycleUnavailable(
                            f"Stopped while replaying observed navigation: {target_reason}"
                        )
                reached = self._identify_discovered_screen(driver, discovery, package)
                if reached is not None and reached.screen_id == target_screen.screen_id:
                    break
                time.sleep(0.5)
            if reached is None or reached.screen_id != target_screen.screen_id:
                raise ProviderLifecycleUnavailable(
                    f"Observed navigation via {control.semantic_label} did not reach "
                    f"{target_screen.page_label or target_screen.screen_id}. The case was stopped safely."
                )
            navigation.append(
                {
                    "from_screen": transition.from_screen_id,
                    "to_screen": transition.to_screen_id,
                    "control": control.semantic_label,
                }
            )
        if has_locator and not self._step_locator_available(driver, entry_step, locator_map):
            raise ProviderLifecycleUnavailable(
                f"Autopilot reached {target.page_label or target.screen_id}, but the case's observed "
                "entry control is not visible. No test action was taken."
            )
        return navigation

    def _execute_test(
        self,
        driver,
        test: QTXTestIR,
        evidence_dir: Path,
        package: str | None,
        target_kind: str = "android",
        input_values: Dict[str, str] | None = None,
        sensitive_input_keys: set[str] | None = None,
    ) -> Dict[str, Any]:
        from appium.webdriver.common.appiumby import AppiumBy

        locator_map = {
            "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
            "id": AppiumBy.ID,
            "xpath": AppiumBy.XPATH,
        }
        actions: list[dict[str, Any]] = []
        input_values = input_values or {}
        sensitive_input_keys = sensitive_input_keys or set()
        sensitive_input_touched = False
        for index, step in enumerate(test.steps, start=1):
            mechanism: str | None = None
            if step.action == "launch_app":
                if package and expected_package_state(driver, package) is not True:
                    driver.activate_app(package)
                    time.sleep(1)
            elif step.action == "inspect_ui":
                source = driver.page_source or ""
                if not source.strip():
                    platform_label = "iOS" if target_kind == "ios" else "Android"
                    raise AssertionError(f"No readable {platform_label} UI hierarchy was returned")
            elif step.action == "background_app":
                if target_kind == "ios":
                    try:
                        driver.background_app(2)
                        mechanism = "background_app"
                    except Exception as exc:
                        raise ProviderLifecycleUnavailable(
                            "iOS background/foreground lifecycle control is unavailable on this device provider."
                        ) from exc
                else:
                    mechanism = safe_background_application(driver, 2, package=package)
                time.sleep(0.5)
            elif step.action == "restore_app":
                if not package:
                    raise AssertionError("Unable to determine application package for restore")
                driver.activate_app(package)
                time.sleep(1)
                if expected_package_state(driver, package) is not True:
                    raise AssertionError("Application did not recover to foreground")
            elif step.action == "scroll":
                # Keep replay aligned with Runtime Discovery's provider-safe
                # gesture order. A missing/unsupported gesture blocks this
                # case with an actionable capability message; it must not
                # masquerade as a locator or assertion failure.
                width, height = 1080, 1920
                try:
                    size = driver.get_window_size()
                    width = max(320, int(size.get("width") or width))
                    height = max(480, int(size.get("height") or height))
                except Exception:
                    pass
                scrolled = False
                execute_script = getattr(driver, "execute_script", None)
                if callable(execute_script):
                    for command, arguments in (
                        (
                            "mobile: scrollGesture",
                            {
                                "left": 0,
                                "top": max(0, int(height * 0.12)),
                                "width": width,
                                "height": max(200, int(height * 0.78)),
                                "direction": "down",
                                "percent": 0.75,
                            },
                        ),
                        ("mobile: swipe", {"direction": "up", "percent": 0.75}),
                    ):
                        try:
                            result = execute_script(command, arguments)
                            scrolled = result is not False
                            if scrolled:
                                break
                        except Exception:
                            continue
                if not scrolled:
                    swipe = getattr(driver, "swipe", None)
                    if callable(swipe):
                        try:
                            swipe(
                                int(width * 0.5),
                                int(height * 0.82),
                                int(width * 0.5),
                                int(height * 0.22),
                                duration=700,
                            )
                            scrolled = True
                        except TypeError:
                            try:
                                swipe(
                                    int(width * 0.5),
                                    int(height * 0.82),
                                    int(width * 0.5),
                                    int(height * 0.22),
                                    700,
                                )
                                scrolled = True
                            except Exception:
                                pass
                        except Exception:
                            pass
                if not scrolled:
                    raise ProviderLifecycleUnavailable(
                        "The mobile provider does not expose a safe scroll gesture for this journey."
                    )
                time.sleep(0.8)
            elif step.action == "wait_for_state":
                # The bounded wait is an explicit IR action so a slow screen
                # is distinguishable from an unsupported provider command.
                time.sleep(min(120.0, max(0.0, float(step.timeout_ms or 1000) / 1000)))
            elif step.action in {"tap", "click", "assert_visible", "assert_text", "clear", "select"}:
                element = self._find_semantic_element(driver, step, locator_map)
                if step.action in {"tap", "click"}:
                    if not element.is_enabled():
                        raise AssertionError(f"Resolved control is disabled: {step.target}")
                    element.click()
                    time.sleep(0.9)
                    if package:
                        target_ready, target_reason, _ = validate_target_surface(
                            driver,
                            expected_package=package,
                            page_source=safe_page_source(driver),
                        )
                        if not target_ready:
                            raise ProviderLifecycleUnavailable(
                                f"Stopped after navigation left the uploaded app: {target_reason}"
                            )
                elif not element.is_displayed():
                    raise AssertionError(f"Resolved control is not visible: {step.target}")
                elif step.action == "assert_text":
                    expected = str(step.assertion or step.value or step.description or "").strip()
                    actual = str(getattr(element, "text", "") or "")
                    if expected and expected.casefold() not in actual.casefold():
                        raise AssertionError(f"Expected text was not visible for {step.target or 'the control'}")
                elif step.action == "clear":
                    clearer = getattr(element, "clear", None)
                    if callable(clearer):
                        clearer()
                    else:
                        raise ProviderLifecycleUnavailable("The provider does not expose a safe clear action for this field.")
                elif step.action == "select":
                    # Native select controls vary by platform; opening the
                    # observed control is safe, while the option selection is
                    # represented by a following tap in the grounded IR.
                    element.click()
                    time.sleep(0.4)
            elif step.action == "press":
                key = step.value or step.target
                if not key:
                    raise AssertionError("Press action has no key target")
                presser = getattr(driver, "press_keycode", None)
                if callable(presser) and str(key).isdigit():
                    presser(int(key))
                else:
                    raise ProviderLifecycleUnavailable("The provider does not expose a safe press action for this key.")
            elif step.action == "reset":
                self._reset_to_application(driver, package)
            elif step.action == "fill":
                input_key = step.input_key
                # Synthetic values are embedded only for non-sensitive
                # evidence-scoped probes.  Runtime fields (including the
                # User ID/password fills injected before sign-in) deliberately
                # have no ``step.value`` and must always resolve through the
                # encrypted, write-only input map, even when the surrounding
                # case is marked as an autonomous candidate.
                value = step.value if step.value is not None else input_values.get(input_key or "")
                if not input_key or value is None or not str(value).strip():
                    raise AssertionError(
                        f"Encrypted runtime input is unavailable for {step.target or 'the requested field'}"
                    )
                element = self._find_semantic_element(driver, step, locator_map)
                if not element.is_enabled():
                    raise AssertionError(f"Resolved input control is disabled: {step.target}")
                if hasattr(element, "clear"):
                    element.clear()
                try:
                    element.send_keys(value)
                except Exception:
                    # Provider errors occasionally echo command arguments;
                    # never propagate a password, OTP or test value into the
                    # suite result, logs or report.
                    raise AssertionError("Encrypted runtime input could not be entered") from None
                sensitive_input_touched = sensitive_input_touched or input_key in sensitive_input_keys
            elif step.action == "assert_validation_feedback":
                # Validation is deliberately evidence-led.  The runner does
                # not infer a pass from the fact that a field accepted a
                # value; it must observe an explicit invalid/error/required
                # state in the returned hierarchy.  If the product gives no
                # feedback, record a failed test so the missing affordance is
                # visible to the user instead of silently blocking the case.
                source = (safe_page_source(driver) or "").lower()
                validation_markers = (
                    'aria-invalid="true"',
                    "invalid",
                    "error",
                    "required",
                    "warning",
                    "alert",
                    "incorrect",
                    "not valid",
                    "must ",
                )
                if not any(marker in source for marker in validation_markers):
                    raise AssertionError(
                        f"No validation feedback was visible after exercising {step.target or 'the field'}"
                    )
            elif step.action == "capture_evidence":
                if sensitive_input_touched:
                    # Do not persist a screenshot or hierarchy after a
                    # password/OTP has been entered; the result still records
                    # that evidence was intentionally suppressed.
                    pass
                else:
                    screenshot = evidence_dir / f"step-{index:02d}.png"
                    source_path = evidence_dir / f"step-{index:02d}.xml"
                    driver.get_screenshot_as_file(str(screenshot))
                    # Native hierarchies may echo a typed username, token or
                    # custom-field value in ``text``/``value`` attributes.
                    # Keep the same value-redaction contract as Runtime
                    # Discovery before persisting any XML evidence.
                    from app.services.autopilot_discovery import AutopilotDiscoveryService

                    source_path.write_text(
                        AutopilotDiscoveryService._redact_page_source(driver.page_source or ""),
                        encoding="utf-8",
                    )
            else:
                raise RuntimeError(f"IR action is not permitted by the safe suite runner: {step.action}")
            action_evidence = {
                "action": step.action,
                "target": step.target,
                "screen_id": step.screen_id,
                "locator_confidence": step.locator_confidence,
            }
            if mechanism:
                action_evidence["mechanism"] = mechanism
            actions.append(action_evidence)

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
            "sensitive_input_evidence_suppressed": sensitive_input_touched,
        }

    @staticmethod
    def _find_semantic_element(driver, step: QTXIRStep, locator_map: Dict[str, str]):
        if not step.locator_strategy or not step.locator_value:
            raise AssertionError(f"Missing deterministic locator for semantic target: {step.target}")
        if step.locator_strategy not in locator_map:
            raise AssertionError(f"Unsupported locator strategy: {step.locator_strategy}")
        candidates = [(step.locator_strategy, step.locator_value)]
        candidates.extend(
            (locator.strategy, locator.value)
            for locator in step.locator_fallbacks
            if locator.strategy in locator_map
            and (locator.strategy, locator.value) not in candidates
        )
        last_error: Exception | None = None
        for candidate_index, (strategy, value) in enumerate(candidates):
            # Keep the existing settling retry for the preferred selector;
            # then try only the other selectors explicitly observed during
            # discovery. No new locator is guessed at execution time.
            default_timeout_ms = 4800
            bounded_timeout_ms = min(9600, max(2400, int(step.timeout_ms or default_timeout_ms)))
            attempts = max(4, min(16, (bounded_timeout_ms + 599) // 600)) if candidate_index == 0 else 1
            for attempt in range(attempts):
                try:
                    return driver.find_element(locator_map[strategy], value)
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts - 1:
                        time.sleep(0.6)
        if last_error is not None:
            raise last_error
        raise AssertionError(f"Unable to resolve deterministic locator for {step.target}")

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:100]

