"""Bounded, read-only website runtime discovery for Autopilot.

The website adapter deliberately uses Playwright only for navigation, DOM
inspection and evidence capture. It never submits forms or clicks controls that
look like authentication, payment, transfer, deletion or other irreversible
actions. Authenticated journeys remain setup-gated until a future vault
connector is configured.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urldefrag, urljoin, urlparse

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotDiscoveryRequest,
    AutopilotDiscoveryResult,
    AutopilotSuiteRequest,
    AutopilotSuiteResult,
    AutopilotSuiteTestResult,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveryLocator,
    QTXTestIR,
)
from app.services.autopilot import AutopilotPrototypeService


_BLOCKED_TERMS = (
    "logout", "log out", "delete", "remove", "payment", "pay", "transfer", "send money",
    "purchase", "buy", "checkout", "submit", "confirm", "otp", "password", "reset",
)


def _same_origin(left: str, right: str) -> bool:
    a, b = urlparse(left), urlparse(right)
    return (a.scheme, a.netloc.lower()) == (b.scheme, b.netloc.lower())


def _safe_css(value: str) -> str:
    # CSS.escape is not available outside the browser. IDs consisting of the
    # common HTML identifier characters are deterministic and unambiguous;
    # everything else falls back to a bounded attribute selector.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value or ""):
        return f"#{value}"
    escaped = (value or "").replace('\\', '\\\\').replace('"', '\\"')[:180]
    return f'[id="{escaped}"]'


def _blocked_label(label: str, href: str = "") -> tuple[str, str | None]:
    haystack = f"{label} {href}".lower()
    for term in _BLOCKED_TERMS:
        if term in haystack:
            return "blocked", f"Blocked business/destructive term matched: {term}"
    return "safe", None


async def _capture_screenshot(page: Any, path: Path) -> tuple[str | None, str | None]:
    """Capture best-effort visual evidence without failing the web check.

    Full-page screenshots wait for every page font and may hang on public
    sites that keep a font request open. A screenshot is useful evidence, but
    it is not the assertion performed by a safe smoke or suite check. Keep a
    short deadline, fall back to the viewport, and report the limitation as
    evidence instead of turning a successful page load into a false failure.
    """
    try:
        await page.screenshot(path=str(path), full_page=True, timeout=8000)
        return str(path), None
    except Exception as first_error:
        try:
            await page.screenshot(path=str(path), full_page=False, timeout=5000)
            return str(path), (
                "Full-page screenshot unavailable; viewport evidence captured "
                f"({type(first_error).__name__})."
            )
        except Exception as second_error:
            return None, f"Screenshot unavailable: {type(second_error).__name__}: {str(second_error)[:180]}"


class AutopilotWebService:
    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    async def _browser(self, manager: Any, browser_name: str):
        browser_type = getattr(manager, browser_name, None)
        if browser_type is None:
            raise RuntimeError(f"Unsupported Playwright browser: {browser_name}")
        return await browser_type.launch(headless=True)

    async def smoke(self, job_id: str, request) -> dict[str, Any]:
        """Run a single non-mutating page-load smoke and capture evidence."""
        job = await self.prototype.load_job(job_id)
        target_url = request.target_url or job.get("target_url")
        if not target_url:
            raise RuntimeError("Website target URL is missing")
        target_url = self.prototype.validate_web_url(
            str(target_url), allow_private=self.settings.APP_ENV == "local"
        )
        evidence_dir = self.prototype._job_dir(job_id) / "evidence" / "web-smoke"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = evidence_dir / "launch.png"
        source_path = evidence_dir / "page-source.html"
        started = time.perf_counter()
        async with self._playwright_context() as (manager, browser):
            context = await browser.new_context(ignore_https_errors=False)
            await context.route("**/*", self._safe_route)
            page = await context.new_page()
            try:
                response = await page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS * 1000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                captured_screenshot, screenshot_warning = await _capture_screenshot(page, screenshot_path)
                html = await page.content()
                source_path.write_text(html, encoding="utf-8")
                status_code = response.status if response is not None else None
                title = await page.title()
                evidence = {
                    "url": page.url,
                    "title": title[:300],
                    "status_code": status_code,
                    "content_length": len(html),
                    "duration_seconds": round(time.perf_counter() - started, 2),
                    "provider": "playwright",
                    "read_only": True,
                }
                if screenshot_warning:
                    evidence["screenshot_warning"] = screenshot_warning
                return {
                    "status": "passed" if status_code is None or status_code < 400 else "failed",
                    "target_kind": "web",
                    "target_url": target_url,
                    "current_package": None,
                    "current_activity": None,
                    "screenshot_path": captured_screenshot,
                    "page_source_path": str(source_path),
                    "evidence": evidence,
                    "error": None if status_code is None or status_code < 400 else f"Website returned HTTP {status_code}",
                }
            finally:
                await context.close()

    async def discover(self, job_id: str, request: AutopilotDiscoveryRequest) -> AutopilotDiscoveryResult:
        job = await self.prototype.load_job(job_id)
        target_url = request.target_url or job.get("target_url")
        if not target_url:
            raise RuntimeError("Website target URL is missing")
        target_url = self.prototype.validate_web_url(
            str(target_url), allow_private=self.settings.APP_ENV == "local"
        )
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        evidence_root = self.prototype._job_dir(job_id) / "evidence" / "web-discovery"
        evidence_root.mkdir(parents=True, exist_ok=True)
        screens: list[DiscoveredScreen] = []
        transitions = []
        warnings: list[str] = []
        visited: set[str] = set()
        queue: list[str] = [target_url]
        actions = 0
        async with self._playwright_context() as (manager, browser):
            context = await browser.new_context(ignore_https_errors=False)
            await context.route("**/*", self._safe_route)
            page = await context.new_page()
            try:
                while queue and len(screens) < min(request.max_screens, self.settings.AUTOPILOT_WEB_MAX_PAGES):
                    current_url = queue.pop(0)
                    current_url = urldefrag(urljoin(target_url, current_url))[0]
                    if current_url in visited or not _same_origin(target_url, current_url):
                        continue
                    visited.add(current_url)
                    try:
                        response = await page.goto(
                            current_url,
                            wait_until="domcontentloaded",
                            timeout=self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS * 1000,
                        )
                        status_code = response.status if response is not None else None
                        html = await page.content()
                        title = (await page.title())[:300]
                        controls = await self._controls(page)
                        screen_id = f"screen-{len(screens) + 1:03d}"
                        fingerprint = hashlib.sha256(
                            f"{page.url}|{title}|{','.join(item.control_id for item in controls)}".encode("utf-8")
                        ).hexdigest()
                        screenshot_path = evidence_root / f"{screen_id}.png"
                        source_path = evidence_root / f"{screen_id}.html"
                        captured_screenshot, screenshot_warning = await _capture_screenshot(page, screenshot_path)
                        if screenshot_warning:
                            warnings.append(f"{screen_id}: {screenshot_warning}")
                        source_path.write_text(html, encoding="utf-8")
                        screens.append(
                            DiscoveredScreen(
                                screen_id=screen_id,
                                fingerprint=fingerprint,
                                url=page.url,
                                title=title or None,
                                screenshot_path=captured_screenshot,
                                page_source_path=str(source_path),
                                controls=controls,
                            )
                        )
                        if status_code is not None and status_code >= 400:
                            warnings.append(f"{page.url} returned HTTP {status_code}")
                        if request.observe_only:
                            break
                        if actions >= request.max_actions:
                            break
                        links = await page.locator("a[href]").evaluate_all(
                            "els => els.slice(0, 100).map(a => ({href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim()}))"
                        )
                        for link in links:
                            href = str(link.get("href") or "")
                            label = str(link.get("text") or "")
                            if not href or not _same_origin(target_url, href):
                                continue
                            risk, _ = _blocked_label(label, href)
                            if risk == "safe" and href not in visited and href not in queue:
                                queue.append(urldefrag(href)[0])
                                actions += 1
                                if actions >= request.max_actions:
                                    break
                    except Exception as exc:
                        warnings.append(f"Could not inspect {current_url}: {type(exc).__name__}: {str(exc)[:180]}")
                stop_reason = (
                    "Observe-only discovery captured the initial page"
                    if request.observe_only
                    else f"Reached max_screens={request.max_screens}"
                    if len(screens) >= request.max_screens
                    else f"Reached max_actions={request.max_actions}"
                    if actions >= request.max_actions
                    else "No additional safe same-origin pages were available"
                )
            finally:
                await context.close()
        finished_at = datetime.now(timezone.utc)
        status_value = "completed" if screens and not warnings else "partial" if screens else "failed"
        return AutopilotDiscoveryResult(
            job_id=job_id,
            target_kind="web",
            target_url=target_url,
            provider="playwright",
            status=status_value,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=round(time.perf_counter() - started, 2),
            device_name="Chromium (headless)",
            observe_only=request.observe_only,
            screen_count=len(screens),
            control_count=sum(len(screen.controls) for screen in screens),
            safe_control_count=sum(sum(control.risk == "safe" for control in screen.controls) for screen in screens),
            blocked_control_count=sum(sum(control.risk == "blocked" for control in screen.controls) for screen in screens),
            actions_attempted=actions,
            stop_reason=stop_reason,
            screens=screens,
            transitions=transitions,
            warnings=warnings,
            error=None if screens else "No website page could be inspected.",
        )

    async def safe_suite(self, job_id: str, request: AutopilotSuiteRequest, tests: list[QTXTestIR]) -> AutopilotSuiteResult:
        """Execute non-mutating web checks and retain per-case evidence."""
        job = await self.prototype.load_job(job_id)
        target_url = request.target_url or job.get("target_url")
        if not target_url:
            raise RuntimeError("Website target URL is missing")
        target_url = self.prototype.validate_web_url(
            str(target_url), allow_private=self.settings.APP_ENV == "local"
        )
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        results: list[AutopilotSuiteTestResult] = []
        async with self._playwright_context() as (manager, browser):
            context = await browser.new_context(ignore_https_errors=False)
            await context.route("**/*", self._safe_route)
            page = await context.new_page()
            try:
                for test in tests:
                    test_started = time.perf_counter()
                    status_value = "passed"
                    error = None
                    evidence: dict[str, Any] = {"provider": "playwright", "target_url": target_url, "read_only": True}
                    try:
                        response = await page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS * 1000,
                        )
                        status_code = response.status if response is not None else None
                        evidence.update({"status_code": status_code, "url": page.url, "title": (await page.title())[:300]})
                        if status_code is not None and status_code >= 400:
                            raise AssertionError(f"Website returned HTTP {status_code}")
                        if test.bucket == "accessibility":
                            unnamed = await page.locator("a,button,input,select,textarea,[role=button]").evaluate_all(
                                "els => els.filter(el => !(el.getAttribute('aria-label') || el.innerText || el.getAttribute('name') || el.getAttribute('title'))).length"
                            )
                            evidence["unnamed_controls"] = int(unnamed)
                            if unnamed:
                                raise AssertionError(f"{unnamed} interactive control(s) have no accessible name")
                        if test.bucket == "ui":
                            path = self.prototype._job_dir(job_id) / "evidence" / "web-suite" / f"{test.test_id}.png"
                            path.parent.mkdir(parents=True, exist_ok=True)
                            captured_screenshot, screenshot_warning = await _capture_screenshot(page, path)
                            if captured_screenshot:
                                evidence["screenshot_path"] = captured_screenshot
                            if screenshot_warning:
                                evidence["screenshot_warning"] = screenshot_warning
                        if test.bucket == "security":
                            evidence["security_headers"] = {
                                key: response.headers.get(key)
                                for key in (
                                    "strict-transport-security",
                                    "content-security-policy",
                                    "x-frame-options",
                                    "x-content-type-options",
                                    "referrer-policy",
                                    "permissions-policy",
                                )
                            }
                    except AssertionError as exc:
                        status_value, error = "failed", str(exc)[:1200]
                    except Exception as exc:
                        status_value, error = "failed", f"{type(exc).__name__}: {str(exc)[:1200]}"
                    results.append(
                        AutopilotSuiteTestResult(
                            test_id=test.test_id,
                            title=test.title,
                            status=status_value,
                            bucket=test.bucket,
                            readiness=test.readiness,
                            dependency=test.dependency,
                            duration_seconds=round(time.perf_counter() - test_started, 2),
                            error=error,
                            evidence=evidence,
                        )
                    )
            finally:
                await context.close()
        passed = sum(item.status == "passed" for item in results)
        failed = sum(item.status == "failed" for item in results)
        finished_at = datetime.now(timezone.utc)
        return AutopilotSuiteResult(
            job_id=job_id,
            target_kind="web",
            target_url=target_url,
            provider="playwright",
            status="passed" if results and failed == 0 else "partial" if passed else "failed",
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=round(time.perf_counter() - started, 2),
            device_name="Chromium (headless)",
            selected_count=len(tests),
            executed_count=len(results),
            passed_count=passed,
            failed_count=failed,
            skipped_count=0,
            deferred_count=0,
            promoted_count=0,
            bucket_counts=self._bucket_counts(tests),
            tests=results,
        )

    async def _controls(self, page: Any) -> list[DiscoveredControl]:
        elements = await page.locator("a,button,input,select,textarea,[role=button]").all()
        controls: list[DiscoveredControl] = []
        seen: set[str] = set()
        for index, element in enumerate(elements[:120]):
            try:
                tag = await element.evaluate("el => el.tagName.toLowerCase()")
                element_id = await element.get_attribute("id") or ""
                name = await element.get_attribute("name") or ""
                aria = await element.get_attribute("aria-label") or ""
                title = await element.get_attribute("title") or ""
                text = (await element.inner_text())[:200] if tag not in {"input", "textarea"} else ""
                label = (aria or text or title or name or element_id or tag).strip()[:160]
                href = await element.get_attribute("href") or ""
                signature = f"{tag}|{element_id}|{name}|{aria}|{text}|{href}"
                control_id = hashlib.sha1(signature.encode("utf-8", errors="ignore")).hexdigest()[:16]
                if control_id in seen:
                    continue
                seen.add(control_id)
                risk, reason = _blocked_label(label, href)
                locator_value = _safe_css(element_id) if element_id else f"{tag}[name=\"{name.replace(chr(34), '')[:120]}\"]" if name else f"{tag}"
                controls.append(
                    DiscoveredControl(
                        control_id=control_id,
                        semantic_label=label or f"{tag} control {index + 1}",
                        class_name=tag,
                        text=text,
                        content_description=aria,
                        resource_id=element_id,
                        clickable=tag in {"a", "button"} or await element.get_attribute("role") == "button",
                        enabled=(await element.is_enabled()),
                        input_capable=tag in {"input", "select", "textarea"},
                        risk=risk,
                        risk_reason=reason,
                        locators=[DiscoveryLocator(strategy="css", value=locator_value, confidence=0.95 if element_id else 0.72)],
                    )
                )
            except Exception:
                continue
        return controls

    async def _safe_route(self, route: Any) -> None:
        """Abort navigation/resource requests to private hosts.

        Playwright follows redirects and page JavaScript can request arbitrary
        URLs. The same URL policy used by the HTTP analyzer is therefore also
        applied at the browser network boundary.
        """
        request_url = str(route.request.url)
        if request_url.startswith(("http://", "https://")):
            try:
                self.prototype.validate_web_url(
                    request_url,
                    allow_private=self.settings.APP_ENV == "local",
                )
            except ValueError:
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    @staticmethod
    def _bucket_counts(tests: Iterable[QTXTestIR]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for test in tests:
            counts[test.bucket] = counts.get(test.bucket, 0) + 1
        return counts

    class _playwright_context:
        def __init__(self):
            self.manager = None
            self.browser = None

        async def __aenter__(self):
            from playwright.async_api import async_playwright

            self.manager = await async_playwright().start()
            self.browser = await self.manager.chromium.launch(headless=True)
            return self.manager, self.browser

        async def __aexit__(self, exc_type, exc, tb):
            if self.browser is not None:
                await self.browser.close()
            if self.manager is not None:
                await self.manager.stop()

