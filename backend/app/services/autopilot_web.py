"""Bounded, read-only website runtime discovery for Autopilot.

The website adapter deliberately uses Playwright only for navigation, DOM
inspection and evidence capture. It may submit an explicitly identified,
approved sign-in form after the user supplies non-production credentials, but
never clicks payment, transfer, deletion or other irreversible controls.
Authenticated journeys remain setup-gated until those values are approved.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
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
    "logout", "log out", "delete", "remove", "payment", "payments", "pay", "transfer", "transfers", "send money",
    "purchase", "buy", "checkout", "submit", "confirm", "otp", "password", "reset",
)
_AUTH_SUBMIT_TERMS = (
    "sign in", "sign-in", "log in", "login", "continue to account", "continue",
    "next", "unlock", "authenticate",
)
_SAFE_INTERACTIVE_TERMS = (
    "menu", "more", "settings", "help", "about", "search", "filter", "sort",
    "back", "home", "privacy", "terms", "language", "profile", "dashboard",
    "explore", "learn", "view", "detail", "tab", "accordion", "expand", "collapse",
    "previous", "next", "open",
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
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
            return "blocked", f"Blocked business/destructive term matched: {term}"
    return "safe", None


def _redact_html(html: str) -> str:
    """Redact DOM value attributes before HTML evidence is persisted."""
    # Values are never needed to replay a locator.  Removing all value-like
    # attributes is deliberately broader than only password fields so a typed
    # username, search term or token cannot leak through a custom control.
    redacted = re.sub(
        r"(\s(?:value|aria-valuetext|data-value|data-input-value)\s*=\s*)([\"']).*?\2",
        r"\1\2\2",
        html or "",
        flags=re.I | re.S,
    )
    # Contenteditable controls keep their value as text between the opening
    # and closing tags instead of in a ``value`` attribute. Replace that text
    # as well so rich-text login/search widgets cannot leak typed input.
    redacted = re.sub(
        r"(<[^>]*\bcontenteditable\s*=\s*[\"']true[\"'][^>]*>).*?(</[^>]+>)",
        r"\1[REDACTED]\2",
        redacted,
        flags=re.I | re.S,
    )
    return redacted


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
    VIDEO_BUCKETS = frozenset({
        "functional",
        "functional_positive",
        "functional_negative",
        "uat",
    })

    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    @classmethod
    def _is_video_case(cls, test: QTXTestIR) -> bool:
        return test.bucket in cls.VIDEO_BUCKETS

    async def _browser(self, manager: Any, browser_name: str):
        browser_type = getattr(manager, browser_name, None)
        if browser_type is None:
            raise RuntimeError(f"Unsupported Playwright browser: {browser_name}")
        return await browser_type.launch(headless=True)

    @staticmethod
    def _credential_hint(control: DiscoveredControl) -> str:
        haystack = " ".join(
            [control.semantic_label, control.content_description, control.resource_id, control.class_name]
        ).lower().replace("_", " ").replace("-", " ")
        if any(term in haystack for term in ("otp", "one time", "mfa", "verification code", "passcode")):
            return "otp"
        if any(term in haystack for term in ("password", "secret", "pin", "securetextfield", "passwordtext", "passwd", "pwd")) or re.search(r"\bpass\b", haystack):
            return "password"
        return "username"

    @classmethod
    def _credential_value(
        cls,
        screen_id: str,
        control: DiscoveredControl,
        input_values: Mapping[str, str],
    ) -> Optional[str]:
        from app.services.autopilot_discovery import AutopilotDiscoveryService

        field_type = control.input_kind or "credential"
        key = AutopilotDiscoveryService.runtime_input_key(screen_id, control.control_id, field_type)
        value = input_values.get(key)
        if value is not None and str(value).strip():
            return str(value)
        hint = cls._credential_hint(control)
        value = input_values.get(f"__{hint}")
        return str(value) if value is not None and str(value).strip() else None

    @classmethod
    def _auth_submit_control(cls, controls: Iterable[DiscoveredControl]) -> Optional[DiscoveredControl]:
        controls = list(controls)
        inputs = [
            control
            for control in controls
            if control.enabled and control.input_capable and control.locators
        ]
        credentialish = any(
            control.input_kind == "credential"
            or re.search(
                r"\b(?:user\s*(?:id|name)|uid|userid|username|password|passcode|otp|mfa|login)\b",
                " ".join(
                    [
                        control.semantic_label or "",
                        control.content_description or "",
                        control.resource_id or "",
                        control.class_name or "",
                    ]
                ).lower(),
            )
            for control in inputs
        )
        candidates: list[DiscoveredControl] = []
        for control in controls:
            if not control.enabled or not control.clickable or control.input_capable or not control.locators:
                continue
            label = (control.semantic_label or "").strip().lower()
            generic_continue = label in {"continue", "next"}
            non_auth_form = any(
                any(term in " ".join(
                    [
                        item.semantic_label or "",
                        item.content_description or "",
                        item.resource_id or "",
                    ]
                ).casefold() for term in ("search", "query", "filter", "newsletter", "subscribe"))
                for item in inputs
            )
            auth_label = any(
                re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", label)
                for term in _AUTH_SUBMIT_TERMS
            )
            # A generic two-field form is ambiguous (contact/newsletter/data
            # entry). Only a Submit button with a credential-labelled input is
            # an authentication signal; otherwise wait for an explicit
            # sign-in/login control instead of guessing.
            contextual_submit = label == "submit" and credentialish
            if generic_continue and not credentialish and (len(inputs) < 2 or non_auth_form):
                auth_label = False
            if (auth_label and control.risk != "blocked") or (contextual_submit and control.risk == "blocked"):
                candidates.append(control)
        candidates.sort(key=lambda item: (-max(locator.confidence for locator in item.locators), item.semantic_label.lower()))
        return candidates[0] if candidates else None

    @staticmethod
    def _is_generic_input_label(label: str, class_name: str) -> bool:
        normalized = re.sub(r"\s+", "", (label or "").strip().lower())
        class_short = (class_name or "").rsplit(".", 1)[-1].lower().replace(" ", "")
        return (
            not normalized
            or normalized in {"input", "textarea", "select", "textfield", "searchfield", "control", class_short}
            or bool(re.fullmatch(r"(?:field|input|text|control)[_-]?\d*", normalized))
        )

    @classmethod
    def _ensure_auth_input_semantics(
        cls,
        controls: list[DiscoveredControl],
    ) -> list[DiscoveredControl]:
        """Promote conventional but unlabeled web login fields to a checkpoint.

        Some SPA forms expose only ``<input>`` elements with generated names.
        When a safe sign-in/continue control is present, treating generic
        fields as User ID and Password gives the user an actionable first
        checkpoint instead of silently crawling past authentication. Search or
        other clearly non-auth fields are left unchanged unless the form has
        two generic inputs and a generic Continue/Next submit.
        """
        inputs = [
            control
            for control in controls
            if control.enabled and control.input_capable and control.locators
        ]
        submit = cls._auth_submit_control(controls)
        if not inputs or submit is None:
            return controls
        submit_label = re.sub(r"\s+", " ", (submit.semantic_label or "").strip().lower())
        explicit_auth_submit = any(
            re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", submit_label)
            for term in _AUTH_SUBMIT_TERMS
            if term not in {"continue", "next"}
        )
        labelled_auth_input = any(
            re.search(
                r"\b(?:user\s*(?:id|name)|uid|userid|username|email|password|passcode|otp|mfa|login)\b",
                (control.semantic_label or "").lower(),
            )
            for control in inputs
        )
        if not explicit_auth_submit and not labelled_auth_input and len(inputs) < 2:
            return controls

        updated: list[DiscoveredControl] = []
        input_ids = {control.control_id for control in inputs}
        credential_positions = {
            index for index, control in enumerate(inputs) if control.input_kind == "credential"
        }
        input_position = 0
        for control in controls:
            if control.control_id not in input_ids:
                updated.append(control)
                continue
            position = input_position
            input_position += 1
            if control.input_kind == "credential":
                updated.append(control)
                continue
            label = control.semantic_label or ""
            # Do not reinterpret an explicitly named search/query field as a
            # login field. Generic generated names/classes remain eligible.
            lower_label = label.lower()
            clearly_non_auth = any(term in lower_label for term in ("search", "query", "filter"))
            if clearly_non_auth and not cls._is_generic_input_label(label, control.class_name):
                updated.append(control)
                continue
            if position == 0 and not credential_positions:
                semantic_label = "User ID / email"
            elif position == 0 and credential_positions:
                semantic_label = label
            elif position == 1 and not credential_positions:
                semantic_label = "Password"
            elif position == 1:
                semantic_label = "Password" if any(
                    cls._credential_hint(item) == "username" for item in inputs[:position]
                ) else label
            else:
                semantic_label = label
            updated.append(control.model_copy(update={"semantic_label": semantic_label, "input_kind": "credential"}))
        return updated

    @staticmethod
    def _safe_probe_control(control: DiscoveredControl) -> bool:
        """Allow only reversible UI/navigation probes beyond ordinary links."""
        if not control.enabled or not control.clickable or control.input_capable or control.risk != "safe" or not control.locators:
            return False
        label = (control.semantic_label or "").strip().lower()
        return any(term in label for term in _SAFE_INTERACTIVE_TERMS)

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
                # Static smoke evidence must follow the same redaction policy
                # as discovered pages. A login/search widget can keep typed
                # values in value, aria-valuetext or contenteditable text.
                source_path.write_text(_redact_html(html), encoding="utf-8")
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

    async def discover(
        self,
        job_id: str,
        request: AutopilotDiscoveryRequest,
        input_values: Optional[Mapping[str, str]] = None,
    ) -> AutopilotDiscoveryResult:
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
        probed_controls: set[str] = set()
        actions = 0
        stop_override: Optional[str] = None
        input_values = input_values or {}

        async with self._playwright_context() as (manager, browser):
            context = await browser.new_context(ignore_https_errors=False)
            await context.route("**/*", self._safe_route)
            page = await context.new_page()

            async def append_screen(*, status_code: Optional[int] = None, persist_evidence: bool = True):
                html = await page.content()
                title = (await page.title())[:300]
                # Normalize unlabeled/generated login fields before computing
                # the screen fingerprint. This makes authentication a
                # first-class, login-first checkpoint for web targets too.
                controls = self._ensure_auth_input_semantics(await self._controls(page))
                fingerprint = hashlib.sha256(
                    f"{page.url}|{title}|{','.join(item.control_id for item in controls)}".encode("utf-8")
                ).hexdigest()
                existing = next((item for item in screens if item.fingerprint == fingerprint), None)
                if existing is not None:
                    return existing, True
                screen_id = f"screen-{len(screens) + 1:03d}"
                screenshot_path = evidence_root / f"{screen_id}.png"
                source_path = evidence_root / f"{screen_id}.html"
                captured_screenshot = None
                if persist_evidence:
                    captured_screenshot, screenshot_warning = await _capture_screenshot(page, screenshot_path)
                    if screenshot_warning:
                        warnings.append(f"{screen_id}: {screenshot_warning}")
                    # Remove typed value attributes before the HTML reaches the
                    # repository. The immediate post-auth screen is not saved at
                    # all, so user identifiers never become evidence.
                    source_path.write_text(_redact_html(html), encoding="utf-8")
                screen = DiscoveredScreen(
                    screen_id=screen_id,
                    fingerprint=fingerprint,
                    url=page.url,
                    title=title or None,
                    screenshot_path=captured_screenshot if persist_evidence else None,
                    page_source_path=str(source_path) if persist_evidence else None,
                    controls=controls,
                )
                screens.append(screen)
                return screen, False

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
                        current, _ = await append_screen(status_code=status_code)
                        if status_code is not None and status_code >= 400:
                            warnings.append(f"{page.url} returned HTTP {status_code}")
                        if request.observe_only:
                            break

                        # Stop on the first sign-in form. The checkpoint is
                        # returned with exact field labels, before unrelated
                        # pages are explored, so the next run can continue with
                        # the same session scope and saved UAT values.
                        auth_rounds = 0
                        while True:
                            credential_controls = [
                                control for control in current.controls
                                if control.input_capable and control.input_kind == "credential"
                            ]
                            if not credential_controls:
                                break
                            auth_rounds += 1
                            if auth_rounds > 3:
                                stop_override = "Authentication has more than three sequential checkpoints; continue under supervision."
                                break
                            auth_approved = str(input_values.get("__auth_approved") or "") == "1"
                            missing_controls = [
                                control
                                for control in credential_controls
                                if self._credential_hint(control) != "otp"
                                and self._credential_value(current.screen_id, control, input_values) is None
                            ]
                            otp_controls = [
                                control
                                for control in credential_controls
                                if self._credential_hint(control) == "otp"
                            ]
                            if not auth_approved or missing_controls or otp_controls:
                                stop_override = (
                                    "Authentication checkpoint detected. Enter the non-production User ID and Password "
                                    "(and provide an approved OTP only when the flow permits it) before Autopilot continues."
                                )
                                break
                            if actions >= request.max_actions:
                                stop_override = f"Authentication values are ready, but max_actions={request.max_actions} was reached"
                                break
                            submit = self._auth_submit_control(current.controls)
                            if submit is None:
                                stop_override = "Credentials were supplied, but no safe sign-in control was found"
                                break
                            try:
                                for control in credential_controls:
                                    value = self._credential_value(current.screen_id, control, input_values)
                                    if value is None:
                                        continue
                                    locator = page.locator(control.locators[0].value)
                                    if await locator.count() != 1 or not await locator.is_visible():
                                        raise RuntimeError(f"Sign-in field is missing or hidden: {control.semantic_label}")
                                    await locator.fill(value)
                                submit_locator = page.locator(submit.locators[0].value)
                                if await submit_locator.count() != 1 or not await submit_locator.is_visible():
                                    raise RuntimeError("Safe sign-in control is missing or hidden")
                                await submit_locator.click(timeout=10000)
                                actions += 1
                                try:
                                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                                except Exception:
                                    pass
                                # Avoid persisting the DOM/screenshot immediately
                                # after typing credentials. The next stable page
                                # is captured after this checkpoint succeeds.
                                post_auth, duplicate = await append_screen(persist_evidence=False)
                                transitions.append(
                                    {
                                        "from_screen_id": current.screen_id,
                                        "to_screen_id": post_auth.screen_id,
                                        "control_id": submit.control_id,
                                        "control_label": submit.semantic_label,
                                        "action": "tap",
                                        "duplicate_state": duplicate,
                                    }
                                )
                                remaining_credentials = [
                                    control for control in post_auth.controls
                                    if control.input_capable and control.input_kind == "credential"
                                ]
                                if duplicate:
                                    stop_override = (
                                        "Sign-in returned to the same page; credentials may be invalid or the flow needs supervision."
                                    )
                                    break
                                if remaining_credentials:
                                    # User ID → password (or a similar
                                    # sequential form) remains part of the same
                                    # login checkpoint. Repeat with the same
                                    # in-memory approved values; OTP is gated.
                                    current = post_auth
                                    continue
                                current = post_auth
                                break
                            except Exception as exc:
                                warnings.append(f"Could not safely submit the approved sign-in form: {type(exc).__name__}")
                                stop_override = "Authentication could not be completed safely; review the sign-in checkpoint"
                                break
                        if stop_override:
                            break
                        if actions >= request.max_actions:
                            break

                        links = await page.locator("a[href]").evaluate_all(
                            "els => els.slice(0, 100).map(a => ({href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim()}))"
                        )
                        link_items: list[tuple[str, str]] = []
                        for link in links:
                            href = str(link.get("href") or "")
                            label = str(link.get("text") or "")
                            if not href or not _same_origin(target_url, href):
                                continue
                            risk, _ = _blocked_label(label, href)
                            if risk == "safe" and href not in visited and href not in queue:
                                link_items.append((href, label))
                        # Visit sign-in/account links before the rest of the
                        # public site so authentication is always the first
                        # user-facing checkpoint.
                        link_items.sort(key=lambda item: 0 if any(term in item[1].lower() for term in _AUTH_SUBMIT_TERMS) else 1)
                        for href, _label in link_items:
                            if actions >= request.max_actions:
                                break
                            queue.append(urldefrag(href)[0])
                            actions += 1

                        # Links do not represent the whole UI. Probe a bounded
                        # set of reversible menus, tabs, filters and accordions
                        # and return to the original URL after each probe.
                        for control in current.controls:
                            if actions >= request.max_actions or len(screens) >= request.max_screens:
                                break
                            if not self._safe_probe_control(control):
                                continue
                            probe_key = f"{current.screen_id}:{control.control_id}"
                            if probe_key in probed_controls:
                                continue
                            probed_controls.add(probe_key)
                            locator = page.locator(control.locators[0].value)
                            try:
                                if await locator.count() != 1 or not await locator.is_visible():
                                    continue
                                base_url = page.url
                                await locator.click(timeout=10000)
                                actions += 1
                                try:
                                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                                except Exception:
                                    pass
                                probe_screen, duplicate = await append_screen()
                                transitions.append(
                                    {
                                        "from_screen_id": current.screen_id,
                                        "to_screen_id": probe_screen.screen_id,
                                        "control_id": control.control_id,
                                        "control_label": control.semantic_label,
                                        "action": "tap",
                                        "duplicate_state": duplicate,
                                    }
                                )
                                if any(
                                    item.input_capable and item.input_kind == "credential"
                                    for item in probe_screen.controls
                                ):
                                    stop_override = (
                                        "Authentication checkpoint detected. Enter the non-production User ID and Password "
                                        "before Autopilot continues."
                                    )
                                    break
                                if probe_screen.url and _same_origin(target_url, probe_screen.url):
                                    normalized_probe_url = urldefrag(probe_screen.url)[0]
                                    if normalized_probe_url not in visited and normalized_probe_url not in queue:
                                        queue.append(normalized_probe_url)
                                await page.goto(
                                    base_url,
                                    wait_until="domcontentloaded",
                                    timeout=self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS * 1000,
                                )
                            except Exception as exc:
                                warnings.append(
                                    f"Could not safely probe {control.semantic_label}: {type(exc).__name__}: {str(exc)[:120]}"
                                )
                        if stop_override:
                            break
                    except Exception as exc:
                        warnings.append(f"Could not inspect {current_url}: {type(exc).__name__}: {str(exc)[:180]}")
                stop_reason = stop_override or (
                    "Observe-only discovery captured the initial page"
                    if request.observe_only
                    else f"Reached max_screens={request.max_screens}"
                    if len(screens) >= request.max_screens
                    else f"Reached max_actions={request.max_actions}"
                    if actions >= request.max_actions
                    else "No additional safe same-origin pages or controls were available"
                )
                if stop_override and stop_override not in warnings:
                    warnings.append(stop_override)
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
            input_requests=self._runtime_input_requests(screens),
            warnings=warnings,
            error=None if screens else "No website page could be inspected.",
        )

    async def safe_suite(
        self,
        job_id: str,
        request: AutopilotSuiteRequest,
        tests: list[QTXTestIR],
        input_values: Optional[Mapping[str, str]] = None,
        sensitive_input_keys: Optional[set[str]] = None,
    ) -> AutopilotSuiteResult:
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
        input_values = input_values or {}
        sensitive_input_keys = sensitive_input_keys or set()
        async with self._playwright_context() as (manager, browser):
            for test in tests:
                test_started = time.perf_counter()
                status_value = "passed"
                error = None
                safe_test_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", test.test_id)[:100]
                evidence_root = self.prototype._job_dir(job_id) / "evidence" / "web-suite"
                evidence_dir = evidence_root / safe_test_id
                evidence_dir.mkdir(parents=True, exist_ok=True)
                evidence: dict[str, Any] = {
                    "provider": "playwright",
                    "target_url": target_url,
                    "read_only": True,
                    "evidence_dir": str(evidence_dir),
                }
                video_requested = self._is_video_case(test)
                # Keep recordings for non-sensitive synthetic probes.  A case
                # that needs a user-provided value (or authentication) is
                # still privacy-protected and will not persist a video.
                sensitive_case = bool(
                    test.requires_auth
                    or any(step.action == "fill" and not step.value for step in test.steps)
                )
                if sensitive_case:
                    # Never start a recording for a journey that can contain a
                    # user-provided credential/OTP or other saved sensitive
                    # value. Functional evidence remains available for the
                    # non-sensitive continuation cases.
                    video_requested = False
                video_status: str | None = None
                context = None
                page = None
                try:
                    context_options: dict[str, Any] = {"ignore_https_errors": False}
                    if video_requested:
                        video_dir = evidence_dir / "video"
                        video_dir.mkdir(parents=True, exist_ok=True)
                        context_options.update(
                            {
                                "record_video_dir": str(video_dir),
                                "record_video_size": {
                                    "width": min(1024, self.settings.AUTOPILOT_VIDEO_WIDTH),
                                    "height": min(768, self.settings.AUTOPILOT_VIDEO_HEIGHT),
                                },
                            }
                        )
                    try:
                        context = await browser.new_context(**context_options)
                    except Exception:
                        if not video_requested:
                            raise
                        # Recording support is provider/version dependent. Fall
                        # back to the normal read-only context rather than
                        # failing a functional check solely because video is
                        # unavailable.
                        video_status = "unsupported"
                        context = await browser.new_context(ignore_https_errors=False)
                    await context.route("**/*", self._safe_route)
                    page = await context.new_page()
                    response = await page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS * 1000,
                    )
                    status_code = response.status if response is not None else None
                    evidence.update({"status_code": status_code, "url": page.url, "title": (await page.title())[:300]})
                    for step in test.steps:
                        if step.action in {"launch_app", "inspect_ui", "capture_evidence"}:
                            continue
                        if step.action not in {"tap", "assert_visible", "fill", "assert_validation_feedback"}:
                            raise AssertionError(f"Website runner cannot validate action: {step.action}")
                        if step.action == "assert_validation_feedback":
                            # Look for an explicit validation affordance rather
                            # than treating a successful DOM interaction as a
                            # pass.  Missing feedback is a useful, actionable
                            # failure for the product team.
                            validation = page.locator(
                                '[aria-invalid="true"], [role="alert"], .error, .invalid, '
                                '[data-testid*="error" i], [class*="error" i]'
                            )
                            if await validation.count() == 0:
                                body_text = (await page.locator("body").inner_text()).lower()
                                markers = ("invalid", "error", "required", "warning", "incorrect", "not valid", "must ")
                                if not any(marker in body_text for marker in markers):
                                    raise AssertionError(
                                        f"No validation feedback was visible after exercising {step.target or 'the field'}"
                                    )
                            continue
                        if step.locator_strategy != "css" or not step.locator_value:
                            raise AssertionError("A deterministic CSS locator is required for this journey")
                        element = page.locator(step.locator_value)
                        if await element.count() != 1:
                            raise AssertionError(f"Journey control is missing or ambiguous: {step.target}")
                        if not await element.is_visible():
                            raise AssertionError(f"Journey control is not visible: {step.target}")
                        if step.action == "tap":
                            await element.click(timeout=10000)
                            if not _same_origin(target_url, page.url):
                                raise AssertionError("Journey navigated outside the selected website")
                        elif step.action == "fill":
                            value = step.value or input_values.get(step.input_key or "")
                            if value is None or not str(value).strip():
                                raise AssertionError(
                                    f"No approved value is available for {step.target or 'the field'}"
                                )
                            await element.fill(str(value))
                            # Trigger client-side blur/validation without
                            # submitting the form or changing server state.
                            await element.evaluate("el => el.blur()")
                    # Every executed web case gets its own screenshot and HTML
                    # snapshot.  The API replaces these temporary paths with
                    # repository asset IDs before returning the result.
                    # A journey that typed a password, OTP or another saved
                    # sensitive value is still executed, but its post-input
                    # screenshot/DOM/video are deliberately suppressed.
                    touched_sensitive = any(
                        step.action == "fill" and step.input_key in sensitive_input_keys
                        for step in test.steps
                    )
                    if touched_sensitive:
                        evidence["sensitive_input_evidence_suppressed"] = True
                    else:
                        screenshot_path = evidence_dir / "screenshot.png"
                        page_source_path = evidence_dir / "page-source.html"
                        captured_screenshot, screenshot_warning = await _capture_screenshot(page, screenshot_path)
                        if captured_screenshot:
                            evidence["screenshot_path"] = captured_screenshot
                        if screenshot_warning:
                            evidence["screenshot_warning"] = screenshot_warning
                        page_source_path.write_text(_redact_html(await page.content()), encoding="utf-8")
                        evidence["page_source_path"] = str(page_source_path)
                    if status_code is not None and status_code >= 400:
                        raise AssertionError(f"Website returned HTTP {status_code}")
                    if test.bucket == "accessibility":
                        unnamed = await page.locator("a,button,input,select,textarea,[role=button]").evaluate_all(
                            "els => els.filter(el => !(el.getAttribute('aria-label') || el.innerText || el.getAttribute('name') || el.getAttribute('title'))).length"
                        )
                        evidence["unnamed_controls"] = int(unnamed)
                        if unnamed:
                            raise AssertionError(f"{unnamed} interactive control(s) have no accessible name")
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
                finally:
                    if context is not None:
                        try:
                            # Playwright finalizes the WebM only when its
                            # context closes. Resolve the path afterwards.
                            await context.close()
                        except Exception:
                            if video_requested and video_status is None:
                                video_status = "close_failed"
                    if video_requested and video_status != "unsupported":
                        if sensitive_case:
                            video_status = "suppressed_sensitive_input"
                        elif page is not None and getattr(page, "video", None) is not None:
                            try:
                                raw_path = await page.video.path()
                                video_path = Path(str(raw_path))
                                if video_path.is_file() and video_path.stat().st_size <= self.settings.AUTOPILOT_VIDEO_MAX_BYTES:
                                    evidence["video_path"] = str(video_path)
                                    video_status = "captured"
                                else:
                                    try:
                                        video_path.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                                    video_status = "too_large"
                            except Exception:
                                video_status = video_status or "unavailable"
                    if video_requested and video_status:
                        evidence["video_status"] = video_status
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
        elements = await page.locator('a,button,input,select,textarea,[role=button],[contenteditable="true"]').all()
        controls: list[DiscoveredControl] = []
        seen: set[str] = set()
        for index, element in enumerate(elements[:120]):
            try:
                tag = await element.evaluate("el => el.tagName.toLowerCase()")
                element_id = await element.get_attribute("id") or ""
                name = await element.get_attribute("name") or ""
                aria = await element.get_attribute("aria-label") or ""
                title = await element.get_attribute("title") or ""
                placeholder = await element.get_attribute("placeholder") or ""
                input_type = await element.get_attribute("type") or ""
                contenteditable = (await element.get_attribute("contenteditable") or "").strip().lower()
                input_capable = tag in {"input", "select", "textarea"} or contenteditable == "true"
                # Select/input values can be user data; use only labels and
                # metadata when classifying a runtime entry point.
                text = (await element.inner_text())[:200] if not input_capable else ""
                label = (aria or placeholder or text or title or name or element_id or tag).strip()[:160]
                # Password controls are often exposed without a visible label
                # (for example ``id=pass``). Promote the semantic label so the
                # checkpoint asks for a password instead of treating it as a
                # second username field. The actual DOM value is never read.
                normalized_input_type = input_type.strip().lower()
                if normalized_input_type == "password" and (
                    not label or label.strip().lower() in {"input", "password", "pass", "pwd", "passwd"}
                ):
                    label = "Password"
                elif normalized_input_type == "email" and label.strip().lower() in {"input", "email"}:
                    label = "User ID / email"
                href = await element.get_attribute("href") or ""
                signature = f"{tag}|{element_id}|{name}|{aria}|{text}|{href}"
                control_id = hashlib.sha1(signature.encode("utf-8", errors="ignore")).hexdigest()[:16]
                if control_id in seen:
                    continue
                seen.add(control_id)
                risk, reason = _blocked_label(label, href)
                if element_id:
                    locator_value = _safe_css(element_id)
                    locator_confidence = 0.95
                elif name:
                    locator_value = f"{tag}[name=\"{name.replace(chr(34), '')[:120]}\"]"
                    locator_confidence = 0.88
                elif text and tag in {"button", "a"}:
                    # A text-scoped locator lets Runtime Discovery inspect
                    # iconless menus/tabs without treating every button on the
                    # page as the same control. Ambiguous matches are still
                    # rejected at interaction time.
                    escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')[:120]
                    locator_value = f'{tag}:has-text("{escaped_text}")'
                    locator_confidence = 0.82
                else:
                    locator_value = f"{tag}"
                    locator_confidence = 0.55
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
                        input_capable=input_capable,
                        input_kind=(
                            self._runtime_input_kind(
                                tag,
                                label,
                                name,
                                element_id,
                                aria,
                                placeholder,
                                input_type,
                            )
                            if input_capable
                            else None
                        ),
                        risk=risk,
                        risk_reason=reason,
                        locators=[DiscoveryLocator(strategy="css", value=locator_value, confidence=locator_confidence)],
                    )
                )
            except Exception:
                continue
        return controls

    @staticmethod
    def _runtime_input_kind(
        tag: str,
        label: str,
        name: str,
        element_id: str,
        aria: str,
        placeholder: str,
        input_type: str,
    ) -> str:
        # An email field is common on public newsletter/contact forms and is
        # not, by itself, proof of authentication.  Treat it as ordinary test
        # data until the surrounding controls (for example a Sign in button or
        # a paired password field) provide concrete login evidence.  The
        # auth-semantic pass below promotes it when that evidence is present.
        if input_type.strip().lower() == "email":
            auth_signal = " ".join([label, name, element_id, aria, placeholder]).casefold()
            if not any(
                token in auth_signal
                for token in ("user", "username", "user id", "login", "sign in", "password")
            ):
                return "test_data"
        # Import lazily to keep the web adapter's import graph lightweight and
        # to share exactly the same credential/test-data classification as
        # mobile discovery.
        from app.services.autopilot_discovery import AutopilotDiscoveryService

        return AutopilotDiscoveryService._input_kind(
            {
                "class": tag,
                "name": name,
                "id": element_id,
                "resource-id": element_id,
                "aria-label": aria,
                "content-desc": aria,
                "hint": placeholder,
                "type": input_type,
            },
            label,
        )

    @staticmethod
    def _runtime_input_requests(screens: Iterable[DiscoveredScreen]):
        from app.services.autopilot_discovery import AutopilotDiscoveryService

        return AutopilotDiscoveryService.runtime_input_requests(screens)

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

