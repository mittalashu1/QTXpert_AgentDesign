"""Safe mobile and web runtime discovery for QTXpert Autopilot.

The discovery agent intentionally uses a conservative navigation policy. It
captures screen state, semantic controls and deterministic locator candidates,
then traverses only a narrow set of reversible/navigation controls. Transactional
or destructive actions are always blocked.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotDiscoveryRequest,
    AutopilotDiscoveryResult,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.appium_compat import safe_app_identity, safe_page_source, safe_quit


_BLOCKED_TERMS = {
    "pay", "payment", "transfer", "send money", "send funds", "purchase", "buy",
    "checkout", "place order", "confirm order", "submit order", "delete", "remove",
    "close account", "terminate", "withdraw", "deposit", "invest", "trade", "sell",
    "redeem", "approve", "authorize", "otp", "one time password", "verify otp",
    "send otp", "notify customer", "submit", "confirm", "book now", "reserve now",
}
_SAFE_NAVIGATION_TERMS = {
    "menu", "more", "settings", "help", "about", "search", "skip", "back", "home",
    "login", "log in", "sign in", "register", "sign up", "forgot password",
    "forgot username", "privacy", "terms", "language", "profile",
}
_INPUT_CLASSES = {
    "android.widget.EditText",
    "android.widget.AutoCompleteTextView",
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeTextView",
}
_ACTIONABLE_CLASSES = {
    "android.widget.Button", "android.widget.ImageButton", "android.widget.TextView",
    "android.view.View", "android.widget.CheckedTextView", "android.widget.Switch",
}


class AutopilotDiscoveryService:
    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    @classmethod
    def _semantic_label(cls, attrs: Dict[str, str]) -> str:
        for key in ("content-desc", "text", "label", "name", "resource-id", "identifier"):
            value = (attrs.get(key) or "").strip()
            if value:
                if key in {"resource-id", "identifier"}:
                    value = value.rsplit("/", 1)[-1].replace("_", " ").replace("-", " ")
                return re.sub(r"\s+", " ", value).strip()[:160]
        class_name = (attrs.get("class") or "control").rsplit(".", 1)[-1]
        return class_name[:160]

    @classmethod
    def _risk(cls, label: str, attrs: Dict[str, str]) -> tuple[str, Optional[str]]:
        haystack = " ".join(
            [label, attrs.get("text", ""), attrs.get("label", ""), attrs.get("name", ""), attrs.get("content-desc", ""), attrs.get("resource-id", ""), attrs.get("identifier", "")]
        ).lower().replace("_", " ").replace("-", " ")
        for term in _BLOCKED_TERMS:
            if term in haystack:
                return "blocked", f"Blocked business/destructive action matched: {term}"
        normalized = cls._normalize(label)
        if normalized in _SAFE_NAVIGATION_TERMS:
            return "safe", None
        return "review", "Control requires semantic review before autonomous interaction"

    @classmethod
    def _locators(cls, attrs: Dict[str, str]) -> list[DiscoveryLocator]:
        locators: list[DiscoveryLocator] = []
        content_desc = (attrs.get("content-desc") or "").strip()
        resource_id = (attrs.get("resource-id") or "").strip()
        ios_accessibility = (attrs.get("identifier") or attrs.get("name") or attrs.get("label") or "").strip()
        text = (attrs.get("text") or attrs.get("label") or "").strip()
        if content_desc:
            locators.append(DiscoveryLocator(strategy="accessibility_id", value=content_desc[:500], confidence=0.99))
        elif ios_accessibility:
            locators.append(DiscoveryLocator(strategy="accessibility_id", value=ios_accessibility[:500], confidence=0.96))
        if resource_id:
            locators.append(DiscoveryLocator(strategy="id", value=resource_id[:500], confidence=0.97))
        if text and len(text) <= 120:
            escaped = text.replace('"', '\\"')
            locators.append(DiscoveryLocator(strategy="xpath", value=f'//*[@text="{escaped}"]', confidence=0.82))
        return locators

    @classmethod
    def parse_controls(cls, page_source: str) -> list[DiscoveredControl]:
        if not page_source.strip():
            return []
        try:
            root = ET.fromstring(page_source)
        except ET.ParseError:
            return []
        controls: list[DiscoveredControl] = []
        seen: set[str] = set()
        for index, node in enumerate(root.iter()):
            attrs = {str(k): str(v) for k, v in node.attrib.items()}
            class_name = attrs.get("class", "")
            ios_node = class_name.startswith("XCUIElementType") or "label" in attrs or "identifier" in attrs
            ios_actionable = class_name in {
                "XCUIElementTypeButton", "XCUIElementTypeCell", "XCUIElementTypeLink",
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
                "XCUIElementTypeSwitch", "XCUIElementTypeTab", "XCUIElementTypeImage",
            }
            clickable = attrs.get("clickable", "false").lower() == "true" or (ios_node and ios_actionable)
            enabled = attrs.get("enabled", "true").lower() not in {"false", "0"}
            input_capable = class_name in _INPUT_CLASSES or class_name in {
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
            }
            actionable = clickable or input_capable or class_name in _ACTIONABLE_CLASSES
            if not actionable:
                continue
            label = cls._semantic_label(attrs)
            locators = cls._locators(attrs)
            if not label and not locators:
                continue
            signature = "|".join([
                class_name,
                attrs.get("resource-id", ""),
                attrs.get("content-desc", ""),
                attrs.get("text", ""),
                attrs.get("bounds", ""),
            ])
            control_id = hashlib.sha1(signature.encode("utf-8", errors="ignore")).hexdigest()[:16]
            if control_id in seen:
                continue
            seen.add(control_id)
            risk, reason = cls._risk(label, attrs)
            controls.append(
                DiscoveredControl(
                    control_id=control_id,
                    semantic_label=label or f"Control {index + 1}",
                    class_name=class_name,
                    text=attrs.get("text", "")[:300],
                    content_description=attrs.get("content-desc", "")[:300],
                    resource_id=attrs.get("resource-id", "")[:500],
                    bounds=attrs.get("bounds", "")[:100],
                    clickable=clickable,
                    enabled=enabled,
                    input_capable=input_capable,
                    risk=risk,
                    risk_reason=reason,
                    locators=locators,
                )
            )
        return controls

    @staticmethod
    def fingerprint(package_name: Optional[str], activity_name: Optional[str], controls: Iterable[DiscoveredControl]) -> str:
        semantic = sorted(
            f"{c.semantic_label.lower()}|{c.resource_id.lower()}|{c.class_name.lower()}"
            for c in controls
        )
        material = "\n".join([package_name or "", activity_name or "", *semantic])
        return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _select_safe_control(controls: list[DiscoveredControl], visited: set[str]) -> Optional[DiscoveredControl]:
        candidates = [
            control for control in controls
            if control.enabled and control.clickable and control.risk == "safe"
            and control.locators and control.control_id not in visited
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-max(locator.confidence for locator in item.locators), item.semantic_label.lower()))
        return candidates[0]

    async def run(self, job_id: str, request: AutopilotDiscoveryRequest) -> AutopilotDiscoveryResult:
        job = await self.prototype.load_job(job_id)
        analysis = await self.prototype.load_analysis(job_id)
        target_kind = str(job.get("target_kind") or getattr(analysis, "target_kind", None) or "android")
        if request.target_kind != target_kind:
            # Direct API clients and older saved requests may still carry the
            # Android-shaped default. The durable job is the source of truth so
            # an IPA always gets XCUITest capabilities.
            request = request.model_copy(update={"target_kind": target_kind})
        apk_path = Path(job.get("apk_path") or "")
        if not apk_path.is_file() and not request.appium_app:
            raise RuntimeError("Uploaded APK artifact is unavailable for runtime discovery")

        app_reference = request.appium_app or str(apk_path)
        browserstack_options: Dict[str, Any] | None = None
        if request.provider == "browserstack":
            app_reference = await self.prototype._browserstack_app_url(job_id, apk_path, analysis.sha256)
            appium_url = self.settings.BROWSERSTACK_HUB_URL
            browserstack_options = {
                "userName": self.settings.BROWSERSTACK_USERNAME,
                "accessKey": self.settings.BROWSERSTACK_ACCESS_KEY,
                "projectName": self.settings.BROWSERSTACK_PROJECT_NAME,
                "buildName": f"Autopilot Discovery {analysis.app_name or analysis.package_name or job['filename']}",
                "sessionName": f"Safe Discovery {job_id[:8]}",
                "debug": True,
                "networkLogs": True,
            }
        else:
            # A BrowserStack run uses its configured hub and must not pass
            # through custom-Appium validation. Resolving the custom endpoint
            # before this branch made valid BrowserStack discovery requests
            # fail whenever a hosted custom Appium URL was intentionally
            # absent.
            appium_url = self.prototype.resolve_appium_url(request)

        started = datetime.now(timezone.utc)
        perf = time.perf_counter()
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    self._run_sync,
                    job_id,
                    appium_url,
                    app_reference,
                    request,
                    analysis.package_name,
                    analysis.main_activity,
                    browserstack_options,
                    self.settings.AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS * 1000,
                ),
                timeout=self.settings.AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS,
            )
            status = "completed" if payload["screens"] else "partial"
            error = None
        except Exception as exc:
            payload = {
                "screens": [], "transitions": [], "actions_attempted": 0,
                "stop_reason": "Discovery could not start or complete", "warnings": [],
            }
            status = "blocked" if self.prototype._looks_like_connector_problem(exc) else "failed"
            error = f"{type(exc).__name__}: {exc}"[:1200]

        finished = datetime.now(timezone.utc)
        screens: list[DiscoveredScreen] = payload["screens"]
        controls = [control for screen in screens for control in screen.controls]
        return AutopilotDiscoveryResult(
            job_id=job_id,
            status=status,
            target_kind=target_kind,
            target_url=job.get("target_url"),
            provider=request.provider,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(time.perf_counter() - perf, 2),
            device_name=request.device_name,
            observe_only=request.observe_only,
            screen_count=len(screens),
            control_count=len(controls),
            safe_control_count=sum(control.risk == "safe" for control in controls),
            blocked_control_count=sum(control.risk == "blocked" for control in controls),
            actions_attempted=int(payload["actions_attempted"]),
            stop_reason=str(payload["stop_reason"]),
            screens=screens,
            transitions=payload["transitions"],
            warnings=payload["warnings"],
            error=error,
        )

    def _run_sync(
        self,
        job_id: str,
        appium_url: str,
        app_reference: str,
        request: AutopilotDiscoveryRequest,
        package_hint: Optional[str],
        activity_hint: Optional[str],
        browserstack_options: Dict[str, Any] | None,
        install_timeout_ms: int,
        server_launch_timeout_ms: int,
        adb_exec_timeout_ms: int,
    ) -> Dict[str, Any]:
        from appium import webdriver
        from appium.webdriver.common.appiumby import AppiumBy

        is_ios = request.target_kind == "ios"
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:newCommandTimeout": 180,
        }
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

        evidence_dir = self.prototype._job_dir(job_id) / "evidence" / "discovery"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        if is_ios:
            from appium.options.ios import XCUITestOptions

            options = XCUITestOptions().load_capabilities(capabilities)
        else:
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options().load_capabilities(capabilities)
        driver = webdriver.Remote(appium_url, options=options)
        screens: list[DiscoveredScreen] = []
        transitions: list[DiscoveredTransition] = []
        seen_fingerprints: dict[str, str] = {}
        visited_controls: set[str] = set()
        warnings: list[str] = []
        actions_attempted = 0
        stop_reason = "Discovery bounds reached"

        def capture() -> tuple[DiscoveredScreen, bool]:
            index = len(screens) + 1
            page_source = safe_page_source(driver)
            controls = self.parse_controls(page_source)
            identity = safe_app_identity(
                driver,
                page_source=page_source,
                package_hint=package_hint,
                activity_hint=activity_hint,
            )
            package_name = identity["package"]
            activity_name = identity["activity"]
            fp = self.fingerprint(package_name, activity_name, controls)
            duplicate = fp in seen_fingerprints
            screen_id = seen_fingerprints.get(fp) or f"screen-{index:03d}"
            if duplicate:
                existing = next(screen for screen in screens if screen.screen_id == screen_id)
                return existing, True
            screenshot_path = evidence_dir / f"{screen_id}.png"
            source_path = evidence_dir / f"{screen_id}.xml"
            try:
                driver.get_screenshot_as_file(str(screenshot_path))
            except Exception as exc:
                warnings.append(f"Screenshot capture failed on {screen_id}: {type(exc).__name__}")
            source_path.write_text(page_source, encoding="utf-8")
            screen = DiscoveredScreen(
                screen_id=screen_id,
                fingerprint=fp,
                package_name=package_name,
                activity_name=activity_name,
                screenshot_path=str(screenshot_path) if screenshot_path.exists() else None,
                page_source_path=str(source_path),
                controls=controls,
            )
            screens.append(screen)
            seen_fingerprints[fp] = screen_id
            return screen, False

        try:
            time.sleep(2)
            current, _ = capture()
            if request.observe_only:
                stop_reason = "Observe-only discovery captured the current screen"
                return {
                    "screens": screens,
                    "transitions": transitions,
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                }

            while len(screens) < request.max_screens and actions_attempted < request.max_actions:
                control = self._select_safe_control(current.controls, visited_controls)
                if control is None:
                    stop_reason = "No additional safe navigation controls were available"
                    break
                visited_controls.add(control.control_id)
                locator = control.locators[0]
                by = {
                    "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
                    "id": AppiumBy.ID,
                    "xpath": AppiumBy.XPATH,
                }[locator.strategy]
                try:
                    element = driver.find_element(by, locator.value)
                    element.click()
                    actions_attempted += 1
                    time.sleep(1.2)
                    next_screen, duplicate = capture()
                    transitions.append(
                        DiscoveredTransition(
                            from_screen_id=current.screen_id,
                            to_screen_id=next_screen.screen_id,
                            control_id=control.control_id,
                            control_label=control.semantic_label,
                            duplicate_state=duplicate,
                        )
                    )
                    if duplicate:
                        try:
                            driver.back()
                            time.sleep(0.8)
                        except Exception:
                            pass
                        stop_reason = "Safe navigation returned to an already-known state"
                        break
                    current = next_screen
                except Exception as exc:
                    warnings.append(
                        f"Could not safely interact with {control.semantic_label}: {type(exc).__name__}: {str(exc)[:180]}"
                    )
                    if len(warnings) >= 5:
                        stop_reason = "Stopped after repeated safe-navigation interaction failures"
                        break
            else:
                if len(screens) >= request.max_screens:
                    stop_reason = f"Reached max_screens={request.max_screens}"
                elif actions_attempted >= request.max_actions:
                    stop_reason = f"Reached max_actions={request.max_actions}"

            return {
                "screens": screens,
                "transitions": transitions,
                "actions_attempted": actions_attempted,
                "stop_reason": stop_reason,
                "warnings": warnings,
            }
        finally:
            safe_quit(driver)
