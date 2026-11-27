"""Safe mobile and web runtime discovery for QTXpert Autopilot.

The discovery agent intentionally uses a conservative navigation policy. It
captures screen state, semantic controls and deterministic locator candidates,
then traverses only a narrow set of reversible/navigation controls. Transactional
or destructive actions are always blocked.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotDiscoveryRequest,
    AutopilotDiscoveryResult,
    AutopilotInputRequest,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
    RuntimePromptBranchRef,
    RuntimePromptChoice,
    RuntimePromptObservation,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.appium_compat import (
    AndroidDeviceDisconnected,
    activate_verified_target_surface,
    enter_observed_text,
    known_native_prompt_kind,
    native_prompt_fingerprint,
    observed_app_identity,
    safe_app_identity,
    safe_current_activity,
    safe_page_source,
    safe_navigate_back,
    safe_quit,
    validate_target_surface,
)
from app.services.local_autopilot import LocalAndroidTarget, LocalAutopilotTransport, LocalDeviceUnavailable
from app.services.autopilot_instructions import (
    auth_binding_key, field_identity, is_transit, matches_module, scope_allows_navigation,
)
from app.services.autopilot_labels import input_probe_guidance, observed_journey_label, observed_page_label


_TRANSACTION_NAVIGATION_TERMS = {
    # Exact page/module labels only. Multi-step and submit buttons stay blocked.
    "pay", "payment", "payments", "transfer", "transfers", "send money", "send funds",
    "deposit", "deposits", "withdraw", "withdrawal", "withdrawals", "invest", "investment",
    "investments", "trade", "trading", "sell", "buy", "redeem", "beneficiary", "beneficiaries",
    "bill pay", "bill payments", "top up", "top-up", "add money", "card payment", "cash transfer",
}
_BLOCKED_TERMS = {
    "pay", "payment", "payments", "transfer", "transfers", "send money", "send funds", "purchase", "buy",
    "checkout", "place order", "confirm order", "submit order", "delete", "remove",
    "close account", "terminate", "withdraw", "deposit", "invest", "trade", "sell",
    "redeem", "approve", "authorize", "otp", "one time password", "verify otp",
    "send otp", "notify customer", "submit", "confirm", "book now", "reserve now",
}
_SAFE_NAVIGATION_TERMS = {
    "menu", "more", "settings", "help", "about", "search", "skip", "back", "home",
    "dismiss", "scrim",
    "login", "log in", "sign in", "register", "sign up", "forgot password",
    "continue", "next", "unlock", "authenticate",
    "forgot username", "privacy", "terms", "language", "profile",
    "explore", "explore as a guest", "learn more", "view details", "dashboard",
    # Read-only module/section labels commonly used by banking, retail and
    # SaaS applications.  Risk is still checked for destructive action words
    # before a control is traversed; these labels only make navigation pages
    # discoverable when the product exposes them as standalone menu items.
    "accounts", "account overview", "cards", "portfolio", "investments",
    "transactions", "activity", "rewards", "offers", "benefits", "support", "bullion",
    "notifications", "documents", "services", "products", "overview",
    "insights", "security", "faq", "contact", "locations", "branches",
}
_SAFE_NAVIGATION_PATTERNS = (
    re.compile(r"^(?:view details|learn more|help|about|privacy|terms)$", re.I),
    re.compile(r"^(?:open|view|go to|show)\s+(?:account|accounts|cards|portfolio|investments|transactions|activity|rewards|offers|benefits|support|notifications|documents|services|products|overview|insights|security)$", re.I),
)
_TAB_POSITION = re.compile(r"\s+tab\s+\d+\s+of\s+\d+$", re.I)
_SUBMISSION_LABEL = re.compile(
    r"^(?:send|share|invite|call|dial|submit|confirm|authori[sz]e|approve|"
    r"delete|remove|erase|reset|sign out|log\s*out)\b",
    re.I,
)
_PASSWORD_CHANGE_FIELD = re.compile(
    r"\b(?:current|old|new|confirm|repeat|retype)\s+(?:new\s+)?password\b",
    re.I,
)
_AUTH_SUBMIT_TERMS = (
    "sign in", "sign-in", "log in", "login", "continue to account", "continue",
    "next", "unlock", "authenticate",
)
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
_SCROLLABLE_CLASSES = {
    "android.widget.ScrollView",
    "android.widget.HorizontalScrollView",
    "androidx.recyclerview.widget.RecyclerView",
    "androidx.viewpager.widget.ViewPager",
    "XCUIElementTypeScrollView",
    "XCUIElementTypeCollectionView",
    "XCUIElementTypeTable",
}
_GENERIC_INPUT_LABELS = {
    "edittext", "autocompletetextview", "textfield", "securetextfield",
    "searchfield", "textview", "control", "input",
}
_GENERIC_STATIC_LABELS = {
    "view", "imageview", "button", "control", "checkedtextview", "switch", "*",
    # Layout/container nodes are structural accessibility-tree noise, not
    # field labels. Keeping them out of the sibling-label window prevents an
    # unlabeled login field from being named after its parent container.
    "framelayout", "linearlayout", "relativelayout", "constraintlayout",
    "scrollview", "horizontalscrollview", "viewgroup", "container", "root",
}

# Android/iOS providers can return their own chrome, launcher, permission
# controller or help overlay when an app failed to launch.  Those nodes must
# never become product journeys or functional cases.
_SYSTEM_SURFACE_MARKERS = (
    "url bar",
    "address bar",
    "omnibox",
    "chrome",
    "pixel phone",
    "phone help center",
    "android system",
    "com.google.android.gms",
    "com.google.android.location.settings",
    "location settings checker activity",
    "navigationbarbackground",
    "statusbar",
    "notification shade",
    "springboard",
    "xctest",
    "appium settings",
    "com.google.android.apps.nexuslauncher",
    "com.android.launcher3",
    "com.sec.android.app.launcher",
    "com.miui.home",
    "search apps, web and more",
    "search on play store",
    "pixel launcher",
    "app suggestions",
)


class _UnexpectedTargetSurface(RuntimeError):
    """A safe navigation action left the uploaded application's surface."""


class AutopilotDiscoveryService:
    def __init__(self, settings: Settings, prototype: AutopilotPrototypeService):
        self.settings = settings
        self.prototype = prototype

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    @classmethod
    def _runtime_prompt_kind(cls, driver: Any, page_source: str, target_kind: str = "android") -> Optional[str]:
        """Recognize native prompts and explicit yes/no checkpoints on mobile."""
        platform = str(target_kind or "").casefold()
        if platform not in {"android", "ios"}:
            return None
        kind = known_native_prompt_kind(driver, page_source, target_kind)
        if kind:
            return kind
        try:
            root = ET.fromstring(page_source or "")
        except ET.ParseError:
            return None
        decisions: set[str] = set()
        for node in root.iter():
            attrs = {str(key): str(value) for key, value in node.attrib.items()}
            class_name = str(attrs.get("class") or attrs.get("type") or node.tag).casefold()
            actionable = (
                attrs.get("clickable", "false").casefold() == "true"
                or class_name.endswith("button")
            )
            label = cls._normalize(cls._semantic_label(attrs))
            if actionable and label:
                decision = cls._prompt_choice_decision(label, exact=True)
                if decision:
                    decisions.add(decision)
        # An explicit affirmative and negative choice is itself a branch
        # checkpoint, even when a cross-platform UI toolkit omits dialog roles
        # from its accessibility hierarchy.
        return "app_confirmation" if {"allow", "deny"}.issubset(decisions) else None

    @classmethod
    def _runtime_prompt_fingerprint(
        cls,
        driver: Any,
        page_source: str,
        target_kind: str = "android",
    ) -> Optional[str]:
        """Return a stable opaque identity for native and app confirmation prompts."""
        kind = cls._runtime_prompt_kind(driver, page_source, target_kind)
        if not kind:
            return None
        native_id = native_prompt_fingerprint(driver, page_source, target_kind)
        if native_id:
            return native_id
        choice_keys: list[str] = []
        visible_context: list[str] = []
        try:
            root = ET.fromstring(page_source or "")
            for node in root.iter():
                attrs = {str(key): str(value) for key, value in node.attrib.items()}
                label = cls._normalize(cls._semantic_label(attrs))
                class_name = str(attrs.get("class") or attrs.get("type") or node.tag).casefold()
                actionable = (
                    attrs.get("clickable", "false").casefold() == "true"
                    or class_name.endswith("button")
                )
                decision = cls._prompt_choice_decision(label, exact=True) if actionable and label else None
                key = re.sub(r"[^a-z0-9]+", "-", label).strip("-") if decision else ""
                if key and key not in choice_keys:
                    choice_keys.append(key[:48])
                elif label and not decision:
                    # Hash the visible prompt copy so separate yes/no dialogs
                    # in the same activity remain distinct without persisting
                    # their text in the discovery graph.
                    visible_context.append(label[:160])
        except ET.ParseError:
            pass
        return hashlib.sha1(
            f"{kind}|{safe_current_activity(driver)}|{'|'.join(choice_keys)}|{'|'.join(sorted(set(visible_context)))}".encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()[:16]

    @staticmethod
    def _external_prompt_surface(
        driver: Any,
        page_source: str,
        *,
        target_kind: str,
        expected_package: Optional[str],
        prompt_kind: Optional[str],
        decision: Optional[str],
    ) -> Optional[dict[str, str]]:
        """Recognize a prompt branch that intentionally opens another surface."""
        platform = str(target_kind or "").casefold()
        if platform == "ios":
            try:
                root = ET.fromstring(page_source or "")
            except ET.ParseError:
                return None
            active_app_name = None
            for node in root.iter():
                attrs = {str(key).casefold(): str(value) for key, value in node.attrib.items()}
                element_type = attrs.get("type", attrs.get("class", "")).casefold()
                if "xcuielementtypeapplication" in element_type:
                    active_app_name = attrs.get("name") or attrs.get("label")
                    break
            context = " ".join([str(active_app_name or ""), page_source or ""]).casefold()
            if active_app_name and "settings" in active_app_name.casefold() and "location" in context:
                return {
                    "kind": "system_settings",
                    "label": "iOS Location settings",
                    "package": active_app_name,
                    "activity": safe_current_activity(driver),
                }
            return None
        if platform != "android":
            return None
        identity = observed_app_identity(driver, page_source=page_source)
        expected = str(expected_package or "").casefold()
        system_packages = {
            "android",
            "com.android.systemui",
            "com.android.permissioncontroller",
            "com.google.android.permissioncontroller",
            "com.android.packageinstaller",
            "com.android.intentresolver",
            "com.google.android.gms",
            "io.appium.settings",
            "io.appium.uiautomator2.server",
            "io.appium.uiautomator2.server.test",
            "com.google.android.apps.nexuslauncher",
            "com.android.launcher3",
            "com.sec.android.app.launcher",
            "com.miui.home",
        }
        packages = [str(item or "").strip() for item in identity.get("hierarchy_packages", [])]
        actual_package = next(
            (
                item for item in packages
                if item and (not expected or item.casefold() != expected)
                and item.casefold() not in system_packages
            ),
            None,
        )
        if not actual_package:
            return None
        activity = safe_current_activity(driver)
        context = " ".join([actual_package, activity, page_source or ""]).casefold()
        if ("settings" in actual_package.casefold() or "settings" in activity.casefold()) and "location" in context:
            return {
                "kind": "system_settings",
                "label": "Android Location settings",
                "package": actual_package,
                "activity": activity,
            }
        if prompt_kind == "app_confirmation" and decision == "allow":
            return {
                "kind": "external_app",
                "label": f"External app {actual_package}",
                "package": actual_package,
                "activity": activity,
            }
        return None

    @classmethod
    def _runtime_prompt_observation(
        cls,
        driver: Any,
        page_source: str,
        evidence_dir: Path,
        target_kind: str = "android",
        *,
        persist_evidence: bool = True,
    ) -> Optional[RuntimePromptObservation]:
        """Capture a native or explicit mobile yes/no prompt as a branch artifact.

        Prompt controls bypass parse_controls so system UI is never mistaken
        for product navigation. Keep only observed option labels and locators.
        """
        kind = cls._runtime_prompt_kind(driver, page_source, target_kind)
        if not kind:
            return None
        try:
            root = ET.fromstring(page_source)
        except ET.ParseError:
            root = None

        choices: list[RuntimePromptChoice] = []
        seen: set[str] = set()
        if root is not None:
            for node in root.iter():
                attrs = {str(key): str(value) for key, value in node.attrib.items()}
                class_name = str(attrs.get("class") or attrs.get("type") or node.tag)
                actionable = (
                    attrs.get("clickable", "false").casefold() == "true"
                    or class_name.casefold() in {"android.widget.button", "xcuielementtypebutton"}
                )
                label = cls._semantic_label(attrs)
                normalized = cls._normalize(label)
                if not actionable or not normalized or normalized in seen:
                    continue
                decision = cls._prompt_choice_decision(normalized, exact=kind == "app_confirmation")
                if decision is None:
                    continue
                locators = cls._locators(attrs)
                if not locators:
                    continue
                seen.add(normalized)
                key = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48] or "choice"
                choices.append(
                    RuntimePromptChoice(
                        key=key,
                        label=label[:120],
                        decision=decision,
                        locators=locators,
                    )
                )

        prompt_id = cls._runtime_prompt_fingerprint(driver, page_source, target_kind) or hashlib.sha1(
            f"{kind}|{safe_current_activity(driver)}|{'|'.join(choice.key for choice in choices)}".encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()[:16]
        screenshot_path = evidence_dir / f"prompt-{prompt_id}.png" if persist_evidence else None
        source_path = evidence_dir / f"prompt-{prompt_id}.xml" if persist_evidence else None
        if persist_evidence:
            try:
                driver.get_screenshot_as_file(str(screenshot_path))
            except Exception:
                screenshot_path = None
            try:
                source_path.write_text(cls._redact_page_source(page_source), encoding="utf-8")
            except Exception:
                source_path = None
        return RuntimePromptObservation(
            prompt_id=prompt_id,
            kind=kind,
            surface=(
                "ios_system" if target_kind == "ios" and kind == "runtime_permission"
                else "application" if kind == "app_confirmation" or target_kind == "ios"
                else "android_system"
            ),
            title={
                "location_settings": "Location settings prompt",
                "runtime_permission": f"{'iOS' if target_kind == 'ios' else 'Android'} permission prompt",
                "app_confirmation": "Application confirmation prompt",
            }.get(kind, "Android system prompt"),
            screenshot_path=str(screenshot_path) if screenshot_path and screenshot_path.exists() else None,
            page_source_path=str(source_path) if source_path else None,
            choices=choices,
            observation_ref=f"runtime-prompt:{prompt_id}",
        )

    @classmethod
    def _prompt_choice_decision(cls, normalized_label: str, *, exact: bool = False) -> Optional[str]:
        allow = (
            "allow", "yes", "ok", "okay", "turn on", "enable", "while using", "only this time",
            "always allow", "proceed",
        )
        deny = (
            "deny", "no", "not now", "no thanks", "don't allow", "don’t allow",
            "never allow", "cancel", "decline", "do not proceed", "not proceed",
        )
        if exact:
            label = normalized_label.strip(" .!?…").replace("’", "'")
            if label in deny:
                return "deny"
            return "allow" if label in allow else None
        # Decline labels can contain an allow token ("Don't allow"). Test
        # them first so a denial is never generated as a grant branch.
        if any(token in normalized_label for token in deny):
            return "deny"
        if any(token in normalized_label for token in allow):
            return "allow"
        return None

    @classmethod
    def _choose_system_prompt_branch(
        cls,
        driver: Any,
        choices: list[RuntimePromptChoice],
        appium_by: Any,
        *,
        prompt_kind: Optional[str] = None,
        allow_app_confirmation: bool = False,
    ) -> tuple[Optional[str], bool]:
        """Choose a discovery branch that reveals the next useful app checkpoint.

        Grant an observed Android runtime permission first so any follow-up
        location-settings checkpoint can be discovered. App confirmations use
        the affirmative route only for a server-verified isolated UAT crawl;
        generated cases retain every observed allow and deny option.
        """
        normalized_kind = str(prompt_kind or "").casefold()
        preferred_decision = (
            "allow"
            if normalized_kind == "runtime_permission"
            or normalized_kind == "app_confirmation" and allow_app_confirmation
            else "deny"
        )
        choice = next((item for item in choices if item.decision == preferred_decision), None)
        if choice is None and preferred_decision == "allow":
            choice = next((item for item in choices if item.decision == "deny"), None)
        if choice is None:
            return None, False
        locator_map = {
            "accessibility_id": appium_by.ACCESSIBILITY_ID,
            "id": appium_by.ID,
            "xpath": appium_by.XPATH,
        }
        for locator in sorted(choice.locators, key=lambda item: -item.confidence):
            by = locator_map.get(locator.strategy)
            if by is None:
                continue
            try:
                element = driver.find_element(by, locator.value)
                if not element.is_enabled():
                    continue
                element.click()
                return choice.key, True
            except Exception:
                continue
        return choice.key, False

    @classmethod
    def _semantic_label(cls, attrs: Dict[str, str]) -> str:
        # Hints/labels identify an input without copying a value typed into it.
        # Text remains a fallback for buttons and static controls.
        input_like = (attrs.get("class") or "") in _INPUT_CLASSES or (attrs.get("class") or "").startswith("XCUIElementTypeText")
        input_text = (attrs.get("text") or "").strip()
        input_label_words = (
            "user", "username", "email", "password", "passcode", "search", "query", "account",
            "amount", "address", "date", "code", "reference", "phone", "otp",
        )
        looks_like_label = (
            input_like
            and 1 < len(input_text) <= 80
            and not any(char in input_text for char in ("@", "=", "\n", "\r"))
            and any(re.search(rf"\b{re.escape(word)}\b", input_text.lower()) for word in input_label_words)
        )
        keys = (
            ("content-desc", "hint", "label", "name", "text", "resource-id", "identifier")
            if input_like and looks_like_label
            else ("content-desc", "hint", "label", "name", "resource-id", "identifier")
            if input_like
            else ("content-desc", "text", "label", "name", "resource-id", "identifier")
        )
        for key in keys:
            value = (attrs.get(key) or "").strip()
            if value:
                if key in {"resource-id", "identifier"}:
                    value = value.rsplit("/", 1)[-1].replace("_", " ").replace("-", " ")
                return re.sub(r"\s+", " ", value).strip()[:160]
        class_name = (attrs.get("class") or "control").rsplit(".", 1)[-1]
        return class_name[:160]

    @classmethod
    def _input_context_label(cls, labels: Iterable[str]) -> Optional[str]:
        """Return the nearest meaningful label rendered before an input.

        Android and iOS accessibility trees commonly render a field label as a
        sibling node rather than exposing it as the input's hint.  Keeping a
        short, local label window lets us classify ``User ID``/``Password``
        fields without reading or storing the field value.
        """
        for value in reversed(list(labels)[-8:]):
            candidate = re.sub(r"\s+", " ", (value or "").strip())
            normalized = cls._normalize(candidate).replace(" ", "")
            if not candidate or normalized in _GENERIC_STATIC_LABELS or not re.search(r"[a-zA-Z]", candidate):
                continue
            return candidate[:160]
        return None

    @classmethod
    def _is_generic_input_label(cls, label: str, class_name: str) -> bool:
        normalized = cls._normalize(label).replace(" ", "")
        class_short = (class_name or "").rsplit(".", 1)[-1].lower().replace(" ", "")
        return (
            normalized in _GENERIC_INPUT_LABELS
            or normalized == class_short
            or bool(re.fullmatch(r"(?:field|input|text|control)[_-]?\d*", normalized))
        )

    @classmethod
    def _is_system_control(cls, attrs: Mapping[str, str], label: str) -> bool:
        """Return true for provider/system UI, never for a product control."""
        haystack = " ".join(
            [
                label,
                attrs.get("text", ""),
                attrs.get("content-desc", ""),
                attrs.get("resource-id", ""),
                attrs.get("package", ""),
                attrs.get("class", ""),
                attrs.get("name", ""),
            ]
        ).casefold().replace("_", " ").replace("-", " ")
        return any(marker in haystack for marker in _SYSTEM_SURFACE_MARKERS)

    @classmethod
    def _input_kind(cls, attrs: Dict[str, str], label: str) -> str:
        """Classify an input by purpose without inspecting its value."""
        input_type = " ".join(
            [str(attrs.get("type") or ""), str(attrs.get("inputType") or "")]
        ).lower()
        if "email" in input_type:
            # Public newsletter/contact forms commonly contain a lone email
            # field. Email syntax alone is not authentication evidence; a
            # nearby password/user label or an auth submit control will promote
            # it during the contextual form pass.
            auth_signal = " ".join(
                [label, attrs.get("hint", ""), attrs.get("resource-id", ""), attrs.get("content-desc", ""), attrs.get("identifier", "")]
            ).casefold()
            if not any(
                token in auth_signal
                for token in ("user", "username", "user id", "login", "sign in", "password")
            ):
                return "test_data"
        haystack = " ".join(
            [
                label,
                attrs.get("hint", ""),
                attrs.get("resource-id", ""),
                attrs.get("content-desc", ""),
                attrs.get("identifier", ""),
                attrs.get("inputType", ""),
                attrs.get("type", ""),
                attrs.get("class", ""),
            ]
        ).lower().replace("_", " ").replace("-", " ")
        if re.search(r"\b(?:user\s*(?:id|name)|uid|userid)\b", haystack) or any(term in haystack for term in ("password", "passcode", "secret", "securetextfield", "passwordtext", "username", "user name", "user id", "userid", "email", "login", "otp", "one time", "mfa")):
            return "credential"
        if any(term in haystack for term in ("search", "query", "account", "customer", "amount", "address", "date", "code", "reference", "id")):
            return "test_data"
        return "text"

    @classmethod
    def _input_hint(cls, attrs: Dict[str, str], label: str) -> str:
        """Provide a UI hint without changing the conservative input kind."""
        haystack = " ".join(
            [label, attrs.get("hint", ""), attrs.get("resource-id", ""), attrs.get("content-desc", ""), attrs.get("identifier", "")]
        ).lower().replace("_", " ").replace("-", " ")
        if any(term in haystack for term in ("password", "passcode", "secret", "securetextfield", "passwordtext")):
            return "password"
        if any(term in haystack for term in ("otp", "one time", "mfa", "verification code")):
            return "otp"
        if re.search(r"\b(?:user\s*(?:id|name)|uid|userid)\b", haystack) or any(term in haystack for term in ("username", "user name", "user id", "userid", "email", "login")):
            return "username"
        return "text"

    @classmethod
    def runtime_input_key(cls, screen_id: str, control_id: str, field_type: str) -> str:
        """Return the stable, non-secret key for one discovered input.

        The key is deliberately derived from the screen/control identity and
        field kind rather than the value typed by a user.  The checkpoint,
        compiler and runner all use this helper so a saved encrypted value is
        mapped to the same field after a refresh or a resumed discovery.
        """
        raw_key = f"{screen_id}:{control_id}:{field_type or 'text'}"
        return f"runtime_{hashlib.sha1(raw_key.encode('utf-8', errors='ignore')).hexdigest()[:14]}"

    @classmethod
    def runtime_input_requests(cls, screens: Iterable[DiscoveredScreen]) -> list[AutopilotInputRequest]:
        """Build field-level checkpoint questions from discovered UI.

        Runtime discovery never fills a field or returns its value. Ordinary
        non-sensitive fields are marked as bounded synthetic candidates so the
        first pass can continue autonomously; the user can still override,
        save an encrypted non-production value, generate a different value,
        or skip the dependent case. Credentials and OTPs remain pending.
        """
        requests: list[AutopilotInputRequest] = []
        seen: set[str] = set()
        for screen in screens:
            separate_form = cls._is_password_change_form(screen.controls) or (
                not screen.url and not cls._credential_controls(screen)
                and any(
                    control.enabled and control.clickable
                    and cls._normalize(control.semantic_label) in {"proceed", "update", "save", "reset password"}
                    for control in screen.controls
                )
            )
            for control in screen.controls:
                if not control.input_capable:
                    continue
                field_type = control.input_kind or "text"
                key = cls.runtime_input_key(screen.screen_id, control.control_id, field_type)
                if key in seen:
                    continue
                seen.add(key)
                sensitive = field_type == "credential"
                credential = sensitive and not separate_form
                category = "credential" if credential else "test_data"
                display_label = control.semantic_label or f"{field_type} field"
                input_hint = cls._input_hint({}, display_label)
                normalized_label = re.sub(r"[_-]+", " ", display_label).strip()
                normalized_label = re.sub(r"\s+", " ", normalized_label)
                if credential and input_hint == "username":
                    # Keep the stable "username" wording in the human label
                    # for API/client compatibility while making the requested
                    # value explicit for non-technical users.
                    friendly_label = "Username · User ID / email"
                elif credential and input_hint == "password":
                    friendly_label = "Password"
                elif credential and input_hint == "otp":
                    friendly_label = "One-time verification code"
                else:
                    friendly_label = normalized_label[:120].title() or "Text field"
                label = (
                    f"Sign-in · {friendly_label}"
                    if credential
                    else f"Test data · {friendly_label}"
                )[:240]
                lower_label = friendly_label.lower()
                if credential and input_hint == "username":
                    question = "What UAT user ID or email should Autopilot enter?"
                    placeholder = "e.g., qa.investor@example.test"
                elif credential and input_hint == "password":
                    question = "What password belongs to this UAT account?"
                    placeholder = "Enter the non-production account password"
                elif credential and input_hint == "otp":
                    question = "What approved non-production one-time code should be used?"
                    placeholder = "e.g., 123456 (only when your test flow permits OTP)"
                elif sensitive:
                    question = f"What dedicated UAT value should this test use for {friendly_label}?"
                    placeholder = "Enter a dedicated value for this test journey"
                elif any(term in lower_label for term in ("address", "street", "city", "country", "postal", "zip")):
                    question = f"What synthetic {friendly_label.lower()} should the test enter?"
                    placeholder = "e.g., 12 Example Street, Dubai"
                elif any(term in lower_label for term in ("email", "phone", "mobile")):
                    question = f"What synthetic {friendly_label.lower()} should the test enter?"
                    placeholder = "e.g., qtxpert+test@example.test"
                elif any(term in lower_label for term in ("amount", "number", "quantity", "code", "reference", "date")):
                    question = f"What synthetic {friendly_label.lower()} should the test enter?"
                    placeholder = "Use the expected non-production format for this field"
                else:
                    question = f"What synthetic value should the test enter in the {friendly_label.lower()} field?"
                    placeholder = "Enter a non-production value, or choose Generate random"
                reason = (
                    "This live sign-in field may require a non-production credential. Enter it for this run, save it encrypted for reuse, or skip it. "
                    "Autopilot never returns the value or writes it to logs."
                    if credential
                    else "This sensitive field belongs to a separate test journey and needs its own dedicated UAT value."
                    if sensitive
                    else "Autopilot will use a bounded synthetic value for this non-sensitive field by default. Override it with a non-production value, save one encrypted for reuse, generate a different value, or skip the dependent check."
                )
                format_hint = (
                    "Password values are encrypted immediately and never included in context, reports or logs."
                    if sensitive
                    else "The first pass uses a deterministic, non-secret synthetic value matching this field. Any override is encrypted before persistence."
                )
                locator = control.locators[0].value if control.locators else None
                # Public, non-sensitive fields should not turn the first pass
                # into a questionnaire.  The compiler has a bounded,
                # deterministic synthetic-data strategy for these controls,
                # so mark them as an automatic random candidate.  Credentials
                # and OTPs remain pending and are the only fields that can
                # pause the first authenticated journey.
                autonomous_status = "pending" if sensitive else "random"
                requests.append(
                    AutopilotInputRequest(
                        key=key,
                        label=label,
                        category=category,
                        reason=reason,
                        required_for=[f"{screen.screen_id}: {display_label}"],
                        sensitive=sensitive,
                        status=autonomous_status,
                        reference_present=not sensitive,
                        source="runtime",
                        screen_id=screen.screen_id,
                        control_id=control.control_id,
                        field_type=field_type,
                        input_hint=input_hint,  # type: ignore[arg-type]
                        locator=locator,
                        question=question,
                        placeholder=placeholder,
                        format_hint=format_hint,
                        journey=screen.journey or observed_journey_label(screen),
                        page_label=screen.page_label or observed_page_label(screen),
                        page_url=screen.url,
                        field_label=normalized_label[:120].title() or "Text field",
                        screenshot_asset_id=screen.screenshot_asset_id,
                        page_source_asset_id=screen.page_source_asset_id,
                        probe_guidance=input_probe_guidance(normalized_label, field_type),
                    )
                )
        return requests

    @staticmethod
    def _startup_surface_diagnostic(driver: Any, expected_package: Optional[str]) -> Optional[str]:
        """Return a coarse launch diagnosis without persisting raw device logs."""
        package = str(expected_package or "").strip().casefold()
        if not package:
            return None
        try:
            entries = driver.get_log("logcat")
        except Exception:
            # Device providers may disable log access; splash classification
            # remains valid without optional diagnostics.
            return None

        app_messages: list[str] = []
        for entry in (entries or [])[-400:]:
            if not isinstance(entry, Mapping):
                continue
            message = str(entry.get("message") or "")
            if package in message.casefold():
                app_messages.append(message.casefold())
        joined = " ".join(app_messages)
        if not joined:
            return None
        if re.search(r"(?:fatal exception|fatal signal|uncaught exception|process\s+.+?\s+has died)", joined):
            return "Startup diagnostics: the target app reported a launch crash."
        if re.search(
            r"(?:unknownhostexception|sockettimeoutexception|connection refused|sslhandshakeexception|"
            r"handshakeexception|connection reset|failed to connect)",
            joined,
        ):
            return "Startup diagnostics: the target app could not reach a required service."
        if re.search(r"(?:missingpluginexception|fluttererror|flutter initialization)", joined):
            return "Startup diagnostics: Flutter reported an initialization error."
        return None

    @classmethod
    def _has_blocking_connectivity_dialog(cls, screen: DiscoveredScreen) -> bool:
        actions = [
            control for control in screen.controls
            if control.enabled and (control.clickable or control.input_capable)
        ]
        return (
            any(cls._normalize(control.semantic_label) == "no internet connection" for control in screen.controls)
            and bool(actions)
            and all(
                not control.input_capable
                and cls._normalize(control.semantic_label) in {"ok", "okay", "dismiss", "retry", "try again"}
                for control in actions
            )
        )

    @classmethod
    def _looks_like_loading_screen(cls, screen: DiscoveredScreen) -> bool:
        """Identify splash/blank or sparse initial surfaces without a safe entry point."""
        marker_text = " ".join(
            [
                screen.activity_name or "",
                screen.title or "",
                *(control.semantic_label for control in screen.controls),
                *(control.class_name for control in screen.controls),
            ]
        ).lower()
        if any(
            term in marker_text
            for term in ("splash", "loading", "progressbar", "launchscreen", "please wait", "skeleton", "shimmer")
        ):
            return True
        generic_labels = {
            "view", "imageview", "textview", "unknown", "layout", "framelayout",
            "linearlayout", "relativelayout", "constraintlayout", "scrollview",
            "horizontalscrollview", "scrollable content", "viewgroup", "flutterview",
            "fluttertextureview", "surfaceview",
        }
        generic_root_classes = generic_labels | {"decorview", "fluttercontainer"}

        def has_meaningful_entry(control: DiscoveredControl) -> bool:
            label = re.sub(r"[\s_-]+", " ", str(control.semantic_label or "").lower()).strip()
            class_short = str(control.class_name or "").rsplit(".", 1)[-1].casefold()
            safe_auth_entry = cls._is_auth_entry_control(label) and control.risk == "safe"
            # Flutter/Appium may tag a splash root as an enabled or even
            # input-capable View. That implementation flag is not evidence
            # of an end-user field; generic container nodes never open a path.
            is_generic_container = (
                label in generic_labels
                or not label and class_short in generic_root_classes
            ) and not safe_auth_entry
            if not control.enabled:
                return False
            if is_generic_container:
                # Flutter/Appium can mark a splash root as scrollable and
                # provide a locator. A generic root is not a journey; only
                # a real input, safe action, or meaningful labeled content counts.
                return False
            real_input = control.input_capable
            # A clearly labeled Flutter login entry can be actionable even when
            # Appium omits clickable=true on its text node. Its observed,
            # deterministic locator keeps this exception narrowly scoped.
            safe_action = (control.clickable or safe_auth_entry) and bool(control.locators) and control.risk == "safe"
            scroll_surface = control.scrollable and bool(control.locators)
            meaningful_semantic_content = bool(
                label and label not in generic_labels and class_short in generic_root_classes
            )
            return real_input or safe_action or scroll_surface or meaningful_semantic_content

        # Do not label a sparse, ungrounded splash/landing surface as a
        # completed crawl just because its root View has a locator or an
        # Appium interaction flag. Credential fields, safe actions, and
        # scrollable content remain valid evidence-backed entry points.
        return not any(
            has_meaningful_entry(control) for control in screen.controls
        )

    @classmethod
    def select_entry_screen(cls, screens: Iterable[DiscoveredScreen]) -> DiscoveredScreen | None:
        """Choose the first settled, interactive screen as the journey root."""
        candidates = list(screens or [])
        return next(
            (screen for screen in candidates if not cls._looks_like_loading_screen(screen)),
            candidates[0] if candidates else None,
        )

    @classmethod
    def _risk(cls, label: str, attrs: Dict[str, str]) -> tuple[str, Optional[str]]:
        haystack = " ".join(
            [label, attrs.get("text", ""), attrs.get("label", ""), attrs.get("name", ""), attrs.get("content-desc", ""), attrs.get("resource-id", ""), attrs.get("identifier", "")]
        ).lower().replace("_", " ").replace("-", " ")
        normalized = cls._normalize(label)
        normalized = _TAB_POSITION.sub("", normalized).strip()
        # Section tabs such as Investments remain ordinary read-only navigation.
        # Exact transaction entry labels are review-only and traversed only when
        # the user asks Autopilot to map transaction journeys.
        if normalized in _SAFE_NAVIGATION_TERMS or any(pattern.search(normalized) for pattern in _SAFE_NAVIGATION_PATTERNS):
            return "safe", None
        if cls._is_transaction_navigation_entry(normalized):
            return "review", "Transaction module entry; map this screen only, never submit a transaction."
        for term in _BLOCKED_TERMS:
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
                return "blocked", f"Blocked business/destructive action matched: {term}"
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
    def _ensure_auth_input_semantics(
        cls,
        controls: list[DiscoveredControl],
    ) -> list[DiscoveredControl]:
        """Infer username/password semantics for a conventional sign-in form.

        Native hierarchies are not required to expose a hint or content
        description for every EditText.  When a screen has a safe sign-in
        control and at least two enabled inputs, treating the first unknown
        field as the user ID and the second as the password is a bounded,
        explainable fallback.  We never inspect the current value and never
        apply this heuristic without a sign-in submit control.
        """
        inputs = [
            control
            for control in controls
            if control.enabled and control.input_capable and control.locators
        ]
        # A staged login button is commonly disabled until a field is filled.
        # Its presence can ground field semantics, but it is not executable
        # until a fresh, post-fill hierarchy reports it as enabled.
        submit = cls._auth_submit_control(controls, include_disabled=True)
        if not inputs or submit is None or cls._is_password_change_form(inputs):
            return controls
        submit_label = cls._normalize(submit.semantic_label)
        explicit_auth_submit = any(
            re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", submit_label)
            for term in _AUTH_SUBMIT_TERMS
            if term not in {"continue", "next"}
        )
        input_haystack = " ".join(
            " ".join(
                [
                    control.semantic_label or "",
                    control.content_description or "",
                    control.resource_id or "",
                    control.class_name or "",
                ]
            )
            for control in inputs
        ).lower().replace("_", " ").replace("-", " ")
        labelled_auth_input = bool(
            re.search(r"\b(?:user\s*(?:id|name)|uid|userid|username|email|password|passcode|otp|mfa|login)\b", input_haystack)
        )
        # A generic Continue/Next is accepted as a login submit only when the
        # form exposes at least two fields. This prevents a search box with a
        # generic Continue CTA from being turned into a credential checkpoint.
        if not explicit_auth_submit and not labelled_auth_input and len(inputs) < 2:
            return controls
        input_positions = {control.control_id: index for index, control in enumerate(inputs)}
        updated: list[DiscoveredControl] = []
        for control in controls:
            if control.control_id not in input_positions:
                updated.append(control)
                continue
            if control.input_kind == "credential":
                position = input_positions[control.control_id]
                label = control.semantic_label or ""
                normalized = cls._normalize(label).replace(" ", "")
                if position == 0 and normalized in {"user", "userid", "uid", "username"}:
                    label = "User ID / email"
                elif position == 1 and normalized in {"password", "passcode", "pwd"}:
                    label = "Password"
                updated.append(control.model_copy(update={"semantic_label": label}))
                continue
            position = input_positions[control.control_id]
            label = control.semantic_label or ""
            # Preserve a meaningful product label; replace only generic class
            # names such as EditText/TextField so the checkpoint is readable.
            if cls._is_generic_input_label(label, control.class_name):
                label = "User ID / email" if position == 0 else "Password" if position == 1 else label
            elif position == 0 and cls._normalize(label).replace(" ", "") in {"user", "userid", "uid"}:
                # Resource IDs such as ``user``/``uid`` are implementation
                # names, not a useful end-user prompt label.
                label = "User ID / email"
            elif position == 1 and cls._normalize(label).replace(" ", "") in {"password", "passcode", "pwd"}:
                # Native resource IDs are commonly lower-case even though the
                # checkpoint is presented as a customer-facing question.
                label = "Password"
            updated.append(control.model_copy(update={"semantic_label": label, "input_kind": "credential"}))
        return updated

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
        recent_static_labels: list[str] = []
        class_positions: dict[str, int] = {}
        for index, node in enumerate(root.iter()):
            attrs = {str(k): str(v) for k, v in node.attrib.items()}
            class_name = attrs.get("class", "")
            class_positions[class_name] = class_positions.get(class_name, 0) + 1
            ios_node = class_name.startswith("XCUIElementType") or "label" in attrs or "identifier" in attrs
            ios_actionable = class_name in {
                "XCUIElementTypeButton", "XCUIElementTypeCell", "XCUIElementTypeLink",
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
                "XCUIElementTypeSwitch", "XCUIElementTypeTab", "XCUIElementTypeImage",
            }
            clickable = attrs.get("clickable", "false").lower() == "true" or (ios_node and ios_actionable)
            enabled = attrs.get("enabled", "true").lower() not in {"false", "0"}
            scrollable = attrs.get("scrollable", "false").lower() in {"true", "1"} or class_name in _SCROLLABLE_CLASSES
            input_capable = class_name in _INPUT_CLASSES or class_name in {
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
            }
            actionable = clickable or input_capable or scrollable or class_name in _ACTIONABLE_CLASSES
            raw_label = cls._semantic_label(attrs)
            if cls._is_system_control(attrs, raw_label):
                continue
            # Field labels are often separate, non-clickable sibling nodes.
            # Retain only a short local window of meaningful labels; never
            # retain text from an input widget because it could be user data.
            if (
                not input_capable
                and not clickable
                and raw_label
                and cls._normalize(raw_label).replace(" ", "") not in _GENERIC_STATIC_LABELS
                and re.search(r"[a-zA-Z]", raw_label)
            ):
                recent_static_labels.append(raw_label)
                recent_static_labels = recent_static_labels[-8:]
            if not actionable:
                continue
            label = raw_label
            nearby_label = cls._input_context_label(recent_static_labels) if input_capable else None
            if input_capable and nearby_label and cls._is_generic_input_label(label, class_name):
                label = nearby_label
            if scrollable and (
                cls._is_generic_input_label(label, class_name)
                or cls._normalize(label).replace(" ", "") in {"content", "list", "recycler", "scroll"}
            ):
                label = "Scrollable content"
            kind_attrs = {**attrs}
            if nearby_label:
                kind_attrs["hint"] = " ".join(filter(None, [attrs.get("hint", ""), nearby_label]))
            input_kind = cls._input_kind(kind_attrs, " ".join(filter(None, [label, nearby_label or ""]))) if input_capable else None
            # Do not create a text XPath from a value in an input widget.
            locator_attrs = {**attrs, "text": ""} if input_capable else attrs
            locators = cls._locators(locator_attrs)
            if (input_capable or scrollable) and not locators and re.fullmatch(r"[A-Za-z0-9_.]+", class_name):
                locators = [DiscoveryLocator(
                    strategy="xpath", value=f'(//*[@class="{class_name}"])[{class_positions[class_name]}]', confidence=0.95,
                )]
            if not label and not locators:
                continue
            signature = "|".join([
                class_name,
                attrs.get("resource-id", ""),
                attrs.get("content-desc", ""),
                "" if input_capable else attrs.get("text", ""),
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
                    # Input values are never returned as discovery metadata.
                    text="" if input_capable else attrs.get("text", "")[:300],
                    content_description=attrs.get("content-desc", "")[:300],
                    resource_id=attrs.get("resource-id", "")[:500],
                    bounds=attrs.get("bounds", "")[:100],
                    clickable=clickable,
                    enabled=enabled,
                    selected=attrs.get("selected", "false").lower() in {"true", "1"},
                    scrollable=scrollable,
                    input_capable=input_capable,
                    input_kind=input_kind,
                    risk=risk,
                    risk_reason=reason,
                    locators=locators,
                )
            )
        return controls

    @classmethod
    def _active_tab_labels(cls, controls: Iterable[DiscoveredControl]) -> tuple[str, ...]:
        labels = (cls._normalize(item.semantic_label) for item in controls if item.selected)
        return tuple(sorted(label for label in labels if _TAB_POSITION.search(label)))

    @classmethod
    def _wait_for_tab_selection(cls, driver: Any, label: str, *, timeout_seconds: float = 8.0) -> bool:
        expected = cls._normalize(label)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            controls = cls.parse_controls(safe_page_source(driver))
            if expected in cls._active_tab_labels(controls):
                return True
            time.sleep(0.3)
        return False

    @classmethod
    def fingerprint(
        cls, package_name: Optional[str], activity_name: Optional[str], controls: Iterable[DiscoveredControl],
    ) -> str:
        controls = list(controls)
        semantic = sorted(
            f"{c.semantic_label.lower()}|{c.resource_id.lower()}|{c.class_name.lower()}"
            for c in controls
        )
        material = "\n".join([package_name or "", activity_name or "", *semantic, *cls._active_tab_labels(controls)])
        return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()

    @classmethod
    def _screen_similarity(
        cls,
        left: DiscoveredScreen,
        right_package: Optional[str],
        right_activity: Optional[str],
        right_controls: Iterable[DiscoveredControl],
        *,
        require_matching_viewport: bool = False,
    ) -> float:
        """Compare two observed screens without trusting volatile text.

        Mobile providers often return a new fingerprint for the same login
        surface when a carousel, promotional number, or loading label changes.
        Treating that as a new page creates duplicate roots (for example
        ``screen-001`` and ``screen-002``) and makes the suite try to navigate
        backwards from the login form to an unreachable duplicate.  This
        comparison deliberately keeps package/activity and input shape as hard
        boundaries, while normalising numbers in labels so volatile copy does
        not split one screen into multiple replay roots.
        """
        if (left.package_name or "") != (right_package or ""):
            return 0.0
        if (left.activity_name or "") != (right_activity or ""):
            return 0.0
        right_controls = list(right_controls)
        left_tabs = cls._active_tab_labels(left.controls)
        right_tabs = cls._active_tab_labels(right_controls)
        if left_tabs and right_tabs and left_tabs != right_tabs:
            return 0.0

        def signature(control: DiscoveredControl) -> tuple[str, str, str, str]:
            label = re.sub(r"\d+", "<n>", cls._normalize(control.semantic_label or ""))
            resource = re.sub(r"\d+", "<n>", cls._normalize(control.resource_id or ""))
            return (
                control.class_name or "",
                resource,
                label,
                control.input_kind or "",
            )

        left_items = {signature(item) for item in left.controls if item.enabled}
        right_items = {signature(item) for item in right_controls if item.enabled}
        if require_matching_viewport:
            left_targets = {
                signature(item) for item in left.controls if item.enabled and (item.clickable or item.input_capable)
            }
            right_targets = {
                signature(item) for item in right_controls if item.enabled and (item.clickable or item.input_capable)
            }
            if left_targets != right_targets:
                return 0.0
        if not left_items or not right_items:
            return 0.0
        left_inputs = sorted(item[3] for item in left_items if item[3])
        right_inputs = sorted(item[3] for item in right_items if item[3])
        # Never collapse a public landing surface into a credential form (or
        # two different credential steps) merely because the surrounding copy
        # looks alike.
        if left_inputs != right_inputs:
            return 0.0
        return len(left_items & right_items) / len(left_items | right_items)

    @classmethod
    def _merge_screen_controls(
        cls,
        existing: DiscoveredScreen,
        controls: Iterable[DiscoveredControl],
    ) -> None:
        """Keep the richer control set when a near-duplicate is observed."""
        merged: dict[tuple[str, str, str], DiscoveredControl] = {}
        for control in [*existing.controls, *list(controls)]:
            key = (
                control.class_name or "",
                re.sub(r"\d+", "<n>", cls._normalize(control.resource_id or "")),
                re.sub(r"\d+", "<n>", cls._normalize(control.semantic_label or "")),
            )
            prior = merged.get(key)
            if prior is None:
                merged[key] = control
            else:
                # Enabled/clickable state belongs to the latest frame. Keeping
                # the old frame with equally good locators freezes Continue
                # as disabled even after valid input has enabled it.
                merged[key] = control.model_copy(update={
                    "control_id": prior.control_id,
                    "locators": control.locators or prior.locators,
                })
        existing.controls = list(merged.values())

    @staticmethod
    def _is_auth_entry_control(label: str) -> bool:
        normalized = re.sub(r"[\s_-]+", " ", str(label or "").lower()).strip()
        return bool(re.search(r"\b(?:log in|login|sign in|authenticate)\b", normalized))

    @classmethod
    def _is_session_timeout(cls, screen: DiscoveredScreen) -> bool:
        return cls._is_session_timeout_controls(screen.controls)

    @classmethod
    def _is_session_timeout_controls(cls, controls: list[DiscoveredControl]) -> bool:
        return (
            not cls._active_tab_labels(controls)
            and any(cls._normalize(control.semantic_label) == "session timeout" for control in controls)
            and any(control.enabled and control.clickable and cls._is_auth_entry_control(control.semantic_label)
                    for control in controls)
        )

    @classmethod
    def _is_transaction_navigation_entry(cls, label: str) -> bool:
        normalized = cls._normalize(label)
        normalized = _TAB_POSITION.sub("", normalized).strip()
        return normalized in _TRANSACTION_NAVIGATION_TERMS

    @classmethod
    def _is_transaction_progress_control(cls, label: str) -> bool:
        # Discovery can map a transaction form but never advance a pre-filled
        # form into a commit/review step. Such steps belong to explicit UAT run.
        normalized = cls._normalize(label)
        return normalized in {"continue", "next", "proceed", "done", "finish"}

    @classmethod
    def _is_named_uat_navigation_control(cls, control: DiscoveredControl) -> bool:
        label = cls._normalize(control.semantic_label)
        return (
            control.risk == "review"
            and bool(label)
            and label not in {"view", "image", "imageview", "button", "icon", "container"}
            and not _SUBMISSION_LABEL.match(label)
            and any(locator.confidence >= 0.90 for locator in control.locators)
        )

    @classmethod
    def _eligible_navigation_controls(
        cls,
        controls: list[DiscoveredControl],
        visited: set[str],
        *,
        include_transaction_journeys: bool = False,
        transaction_context: bool = False,
        explore_named_uat_controls: bool = False,
    ) -> list[DiscoveredControl]:
        return [
            control for control in controls
            if control.enabled
            and (control.clickable or cls._is_auth_entry_control(control.semantic_label))
            and not control.input_capable
            and (
                control.risk == "safe"
                or include_transaction_journeys
                and control.risk == "review"
                and cls._is_transaction_navigation_entry(control.semantic_label)
                or explore_named_uat_controls
                and cls._is_named_uat_navigation_control(control)
            )
            and not (transaction_context and cls._is_transaction_progress_control(control.semantic_label))
            and control.locators and control.control_id not in visited
            and cls._safe_locator_confidence(control)
        ]

    @classmethod
    def _select_safe_control(
        cls,
        controls: list[DiscoveredControl],
        visited: set[str],
        *,
        include_transaction_journeys: bool = False,
        transaction_context: bool = False,
        explore_named_uat_controls: bool = False,
        observed_tabs: Iterable[str] = (),
    ) -> Optional[DiscoveredControl]:
        candidates = cls._eligible_navigation_controls(
            controls, visited, include_transaction_journeys=include_transaction_journeys,
            transaction_context=transaction_context, explore_named_uat_controls=explore_named_uat_controls,
        )
        if not candidates:
            return None
        visited_tabs = set(observed_tabs)

        def navigation_priority(control: DiscoveredControl) -> int:
            if not explore_named_uat_controls:
                return 0
            label = cls._normalize(control.semantic_label)
            if include_transaction_journeys and cls._is_transaction_navigation_entry(label):
                return 0
            if _TAB_POSITION.search(label):
                return 3 if control.selected or label in visited_tabs else 1
            return 2

        # At the app entry screen, observe a real sign-in gate before any
        # guest/demo route; confidence remains the tie-breaker within each group.
        candidates.sort(key=lambda item: (
            0 if cls._is_auth_entry_control(item.semantic_label) else 1,
            0 if cls._normalize(item.semantic_label) == "scrim" else 1,
            navigation_priority(item),
            1 if explore_named_uat_controls and item.risk != "safe" else 0,
            -max(locator.confidence for locator in item.locators),
            item.semantic_label.lower(),
        ))
        # Tour overlays can expose the underlying tabs in the hierarchy.
        # Open the app by choosing the observed Skip/Next pair's Skip action.
        first = candidates[0]
        if (
            not cls._is_auth_entry_control(first.semantic_label)
            and cls._normalize(first.semantic_label) != "scrim"
            and any(cls._normalize(control.semantic_label) == "next" for control in candidates)
        ):
            skip = next(
                (control for control in candidates if cls._normalize(control.semantic_label) == "skip"),
                None,
            )
            if skip is not None:
                return skip
        return first

    @classmethod
    def _safe_locator_confidence(cls, control: DiscoveredControl) -> bool:
        """Allow explicit login navigation to be reached with a text locator.

        A native login CTA often exposes only visible text, which produces a
        deliberately lower-confidence XPath locator than an accessibility ID
        or resource ID.  Requiring the normal ``0.90`` threshold in that case
        leaves discovery parked on the landing screen and never lets it
        observe the actual username/password fields.  Lower the threshold only
        for an explicit authentication entry point; generic ``Continue`` and
        ordinary product links still require the stronger locator.
        """
        confidence = max(locator.confidence for locator in control.locators)
        if confidence >= 0.90:
            return True
        if confidence < 0.80:
            return False
        label = cls._normalize(control.semantic_label).replace("-", " ")
        return bool(re.fullmatch(r"(?:login|log\s+in|sign\s+in|unlock|authenticate|continue\s+to\s+account)", label))

    @staticmethod
    def _scroll_directions(screen: DiscoveredScreen) -> list[str]:
        """Return bounded forward directions for scrollable controls on a screen.

        Keep the historical vertical probe for screens whose accessibility
        tree does not expose a scroll container. When a native horizontal
        container is observed, explore it explicitly instead of sending a
        vertical gesture that cannot reveal its content.
        """
        scrollable = [control for control in screen.controls if control.scrollable]
        if not scrollable:
            return ["down"]

        directions: list[str] = []
        if any("horizontal" not in control.class_name.lower() for control in scrollable):
            directions.append("down")
        if any("horizontal" in control.class_name.lower() for control in scrollable):
            directions.append("right")
        return directions or ["down"]

    @staticmethod
    def _scroll_forward(
        driver: Any,
        direction: str = "down",
        *,
        controls: Iterable[DiscoveredControl] = (),
    ) -> bool | None:
        """Scroll the current native surface using provider-safe gestures.

        Appium providers differ on which mobile extension they expose. Try the
        Android UiAutomator2 scroll gesture first, then the portable swipe
        extension and finally the legacy client method. An unsupported method
        returns None. False means the gesture ran and reached the end of
        the scrollable area.
        """
        direction = "right" if direction in {"right", "horizontal"} else "down"
        swipe_direction = "left" if direction == "right" else "up"
        width, height = 1080, 1920
        try:
            size = driver.get_window_size()
            width = max(320, int(size.get("width") or width))
            height = max(480, int(size.get("height") or height))
        except Exception:
            pass
        rectangles = []
        for control in controls:
            horizontal = "horizontal" in control.class_name.lower()
            if not control.scrollable or horizontal != (direction == "right"):
                continue
            match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", control.bounds)
            if match is None:
                continue
            left, top, right, bottom = map(int, match.groups())
            right, bottom = min(width, right), min(height, bottom)
            if right - left >= 32 and bottom - top >= 32:
                rectangles.append((left, top, right - left, bottom - top))
        execute_script = getattr(driver, "execute_script", None)
        if callable(execute_script):
            if rectangles:
                left, top, area_width, area_height = max(rectangles, key=lambda rect: rect[2] * rect[3])
                gesture_bounds = {"left": left, "top": top, "width": area_width, "height": area_height}
            elif direction == "right":
                gesture_bounds = {
                    "left": max(0, int(width * 0.12)),
                    "top": 0,
                    "width": max(200, int(width * 0.78)),
                    "height": height,
                }
            else:
                gesture_bounds = {
                    "left": 0,
                    "top": max(0, int(height * 0.12)),
                    "width": width,
                    "height": max(200, int(height * 0.78)),
                }
            for command, arguments in (
                (
                    "mobile: scrollGesture",
                    {**gesture_bounds, "direction": direction, "percent": 0.75},
                ),
                ("mobile: swipe", {"direction": swipe_direction, "percent": 0.75}),
            ):
                try:
                    result = execute_script(command, arguments)
                    return result is not False
                except Exception:
                    continue
        swipe = getattr(driver, "swipe", None)
        if callable(swipe):
            if direction == "right":
                start_x, end_x = int(width * 0.82), int(width * 0.22)
                start_y = end_y = int(height * 0.5)
            else:
                start_x = end_x = int(width * 0.5)
                start_y, end_y = int(height * 0.82), int(height * 0.22)
            try:
                swipe(start_x, start_y, end_x, end_y, duration=700)
                return True
            except TypeError:
                try:
                    swipe(start_x, start_y, end_x, end_y, 700)
                    return True
                except Exception:
                    pass
            except Exception:
                pass
        return None

    @classmethod
    def _credential_hint(cls, control: DiscoveredControl) -> str:
        """Classify a credential control without reading its current value."""
        haystack = " ".join(
            [control.semantic_label, control.content_description, control.resource_id, control.class_name, control.input_type or ""]
        ).lower().replace("_", " ").replace("-", " ")
        if any(term in haystack for term in ("otp", "one time", "mfa", "verification code", "passcode")):
            return "otp"
        if any(term in haystack for term in ("password", "secret", "pin", "securetextfield", "passwordtext", "passwd", "pwd")) or re.search(r"\bpass\b", haystack):
            return "password"
        return "username"

    @classmethod
    def _credential_controls(cls, screen: DiscoveredScreen) -> list[DiscoveredControl]:
        controls = [
            control
            for control in screen.controls
            if control.enabled and control.input_capable and control.input_kind == "credential"
        ]
        if cls._is_password_change_form(controls):
            return []
        # A credential-shaped field can also occur on a recovery, profile,
        # or transaction form. Only a sign-in submit or an observed OTP
        # checkpoint makes it part of the authentication handoff.
        if controls and (
            any(cls._credential_hint(control) == "otp" for control in controls)
            or cls._auth_submit_control(screen.controls, include_disabled=True) is not None
        ):
            return controls
        return []

    @classmethod
    def _is_password_change_form(cls, controls: Iterable[DiscoveredControl]) -> bool:
        for control in controls:
            for label in (control.semantic_label, control.content_description, control.resource_id):
                words = re.sub(r"([a-z])([A-Z])", r"\1 \2", label or "")
                if _PASSWORD_CHANGE_FIELD.search(re.sub(r"[_-]+", " ", words)):
                    return True
        return False

    @classmethod
    def _authentication_checkpoint_reason(
        cls,
        screen: DiscoveredScreen,
        input_values: Mapping[str, str],
    ) -> Optional[str]:
        """Return the user-facing gate reason when an observed form needs input."""
        credential_controls = cls._credential_controls(screen)
        if not credential_controls:
            return None
        approved = str(input_values.get("__auth_approved") or "") == "1"
        missing_controls = [
            control
            for control in credential_controls
            if cls._credential_hint(control) != "otp"
            and cls._credential_value(screen.screen_id, control, input_values) is None
        ]
        missing_otp = any(
            cls._credential_hint(control) == "otp"
            and cls._credential_value(screen.screen_id, control, input_values) is None
            for control in credential_controls
        )
        if approved and not missing_controls and not missing_otp:
            return None
        if missing_otp and not missing_controls:
            return (
                "OTP checkpoint detected. This sign-in branch needs a user-provided verification code; "
                "Autopilot will leave this branch incomplete and continue other reachable journeys."
            )
        missing = ", ".join(dict.fromkeys(control.semantic_label for control in missing_controls))
        return (
            f"Authentication checkpoint detected. Provide the observed sign-in input needed to continue: {missing}."
            if missing else "Authentication checkpoint detected. Approve use of the saved sign-in inputs to continue."
        )

    @classmethod
    def _credential_value(
        cls,
        screen_id: str,
        control: DiscoveredControl,
        input_values: Mapping[str, str],
    ) -> Optional[str]:
        field_type = control.input_kind or "credential"
        key = cls.runtime_input_key(screen_id, control.control_id, field_type)
        value = input_values.get(key)
        if value is not None and str(value).strip():
            return str(value)
        hint = cls._credential_hint(control)
        if hint == "otp":
            # A challenge code belongs to the observed field on this job.
            return None
        identity = field_identity(control.semantic_label)
        value = input_values.get(auth_binding_key(control.semantic_label))
        if value is not None and str(value).strip():
            return str(value)
        if identity not in {hint, "", "secure text field", "secure textfield"}:
            return None
        value = input_values.get(f"__{hint}")
        return str(value) if value is not None and str(value).strip() else None

    @classmethod
    def _auth_submit_control(
        cls, controls: Iterable[DiscoveredControl], *, include_disabled: bool = False,
    ) -> Optional[DiscoveredControl]:
        controls = list(controls)
        inputs = [
            control
            for control in controls
            if control.input_capable and control.locators
            and (control.enabled or control.input_kind == "credential")
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
            # Flutter can expose an enabled semantic Button with clickable=false
            # even though the normal WebDriver click activates it. The native
            # button role is sufficient to attempt that normal click, but only
            # after the observed form/label below identifies authentication.
            # Disabled controls remain discovery-only; no coordinate/force click
            # or general navigation policy is relaxed here.
            semantic_button = control.class_name in {"android.widget.Button", "XCUIElementTypeButton"}
            if (
                (not control.enabled and not include_disabled)
                or (not control.clickable and not semantic_button)
                or control.input_capable or not control.locators
            ):
                continue
            label = cls._normalize(control.semantic_label)
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
            # Some native forms expose a literal ``Submit`` button instead of
            # ``Sign in``. Treat that exact label as authentication only when
            # a surrounding input carries a credential signal. A generic
            # two-field form is ambiguous (contact/newsletter/data entry), so
            # it must not become a guessed login checkpoint.
            contextual_submit = label == "submit" and credentialish
            if generic_continue and not credentialish and (len(inputs) < 2 or non_auth_form):
                auth_label = False
            if (auth_label and control.risk != "blocked") or (contextual_submit and control.risk == "blocked"):
                candidates.append(control)
        def submit_priority(item: DiscoveredControl) -> tuple[Any, ...]:
            class_name = str(item.class_name or "").casefold()
            native_button = class_name in {"android.widget.button", "xcuielementtypebutton"}
            # Prefer an explicit native button role over a text/view node sharing
            # the same label. Among same-role candidates, prefer observed native
            # clickability, then enabled state, before locator confidence.
            return (
                -int(native_button),
                -int(item.clickable),
                -int(item.enabled),
                -max(locator.confidence for locator in item.locators),
            )

        candidates.sort(key=lambda item: (*submit_priority(item), item.semantic_label.casefold(), item.control_id))
        if len(candidates) > 1:
            first, second = candidates[:2]
            if (
                cls._normalize(first.semantic_label) == cls._normalize(second.semantic_label)
                and submit_priority(first) == submit_priority(second)
            ):
                return None
        return candidates[0] if candidates else None

    @classmethod
    def _refresh_auth_submit(
        cls, driver: Any, screen: DiscoveredScreen,
        package_hint: Optional[str], activity_hint: Optional[str],
    ) -> Optional[DiscoveredControl]:
        """Observe a newly enabled login submit without recording filled fields.

        Flutter and native staged forms re-render/enable Continue after entry.
        The pre-fill snapshot cannot decide whether submission is possible.
        Keyboard dismissal is best-effort; never use Back, which may leave the
        form. Every retry is grounded in the uploaded app's fresh hierarchy.
        """
        try:
            driver.hide_keyboard()
        except Exception:
            pass
        for attempt in range(21):
            source = safe_page_source(driver)
            controls = cls.parse_controls(cls._redact_page_source(source))
            # Flutter may expose the empty field's label only as ``text``.
            # Redacting the post-fill value then removes that label too. Carry
            # forward only the already-observed credential purpose through an
            # unchanged deterministic locator; never infer it from typed text.
            for control in controls:
                if not control.input_capable:
                    continue
                current_locators = {(item.strategy, item.value) for item in control.locators}
                prior = [
                    item for item in screen.controls
                    if item.input_capable and item.input_kind == "credential"
                    and item.class_name == control.class_name
                    and current_locators.intersection((loc.strategy, loc.value) for loc in item.locators)
                ]
                if len(prior) == 1:
                    control.input_kind = "credential"
                    control.semantic_label = prior[0].semantic_label
            controls = cls._ensure_auth_input_semantics(controls)
            target_ok, reason, _ = validate_target_surface(
                driver, expected_package=package_hint, expected_activity=activity_hint,
                page_source=source, control_labels=[control.semantic_label for control in controls],
            )
            if not target_ok:
                raise _UnexpectedTargetSurface(reason)
            screen.controls = controls
            submit = cls._auth_submit_control(controls)
            if submit is not None:
                return submit
            if attempt < 20:
                time.sleep(0.5)
        return None

    @staticmethod
    def _find_discovered_element(driver: Any, control: DiscoveredControl, appium_by: Any) -> Any:
        """Resolve one observed control without confusing duplicate labels.

        Flutter/native views can expose the same label for a heading and an
        action while reporting clickable=False on the semantic action. Prefer
        an observed actionable native match for actions; if the locator remains
        ambiguous, try the next observed locator rather than guessing.
        """
        locator_map = {
            "accessibility_id": appium_by.ACCESSIBILITY_ID,
            "id": appium_by.ID,
            "xpath": appium_by.XPATH,
        }
        candidates = sorted(control.locators, key=lambda locator: -locator.confidence)
        last_error: Optional[Exception] = None

        def attribute(element: Any, name: str) -> str:
            try:
                return str(element.get_attribute(name) or "").strip()
            except Exception:
                return ""

        for locator in candidates[:3]:
            strategy = locator_map.get(locator.strategy)
            if strategy is None:
                continue
            try:
                find_elements = getattr(driver, "find_elements", None)
                if callable(find_elements):
                    matches = list(find_elements(strategy, locator.value) or [])
                    if len(matches) > 1:
                        expected_class = str(control.class_name or "").strip()
                        expected_resource = str(control.resource_id or "").strip()

                        if expected_class:
                            exact_class = [
                                element for element in matches
                                if attribute(element, "class") == expected_class
                                or attribute(element, "type") == expected_class
                            ]
                            if exact_class:
                                matches = exact_class

                        if expected_resource:
                            exact_resource = [
                                element for element in matches
                                if attribute(element, "resource-id") == expected_resource
                                or attribute(element, "resourceId") == expected_resource
                            ]
                            if exact_resource:
                                matches = exact_resource

                        if control.enabled:
                            enabled = [
                                element for element in matches
                                if attribute(element, "enabled").casefold() == "true"
                            ]
                            if enabled:
                                matches = enabled

                        # The semantic map can under-report Flutter actionability.
                        # For non-input controls, use the native clickable flag to
                        # distinguish the actual action from a duplicate heading.
                        if control.clickable or not control.input_capable:
                            clickable = [
                                element for element in matches
                                if attribute(element, "clickable").casefold() == "true"
                            ]
                            if clickable:
                                matches = clickable

                        if len(matches) > 1 and control.bounds:
                            same_bounds = [element for element in matches if attribute(element, "bounds") == control.bounds]
                            if len(same_bounds) == 1:
                                matches = same_bounds

                        if len(matches) == 1:
                            return matches[0]
                        last_error = LookupError(
                            f"Observed locator is ambiguous for {control.semantic_label}"
                        )
                        continue
                    if len(matches) == 1:
                        match = matches[0]
                        expected_class = str(control.class_name or "").strip()
                        actual_class = attribute(match, "class") or attribute(match, "type")
                        if expected_class and actual_class and actual_class != expected_class:
                            last_error = LookupError(
                                f"Observed locator resolved to the wrong control type for {control.semantic_label}"
                            )
                            continue
                        return match
                return driver.find_element(strategy, locator.value)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise LookupError(f"No supported observed locator exists for {control.semantic_label}")

    @staticmethod
    def _redact_page_source(page_source: str) -> str:
        """Remove values from persisted mobile XML while retaining UI evidence."""
        try:
            root = ET.fromstring(page_source)
            for node in root.iter():
                class_name = str(node.attrib.get("class") or node.attrib.get("type") or node.tag)
                if class_name in _INPUT_CLASSES or class_name in {
                    "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
                }:
                    for key in ("text", "value", "valueText", "password", "accessibilityValue"):
                        if key in node.attrib:
                            node.attrib[key] = ""
            return ET.tostring(root, encoding="unicode")
        except ET.ParseError:
            # A malformed provider hierarchy is not allowed to block discovery;
            # avoid copying the raw source when it cannot be safely redacted.
            return "<hierarchy><node class=\"redacted\" /></hierarchy>"

    @classmethod
    def _auth_feedback_code(cls, page_source: str) -> Optional[str]:
        """Classify sign-in feedback without retaining UI copy or credentials.

        Validation text is usually a non-clickable Flutter sibling, so it is
        absent from ``parse_controls`` and from the screen fingerprint. Only a
        fixed category leaves this method; the raw hierarchy is discarded.
        """
        try:
            root = ET.fromstring(cls._redact_page_source(page_source))
        except ET.ParseError:
            return None
        labels = []
        for node in root.iter():
            if node.attrib.get("class") in _INPUT_CLASSES or node.attrib.get("class") in {
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
            }:
                continue
            labels.extend(str(node.attrib.get(key) or "").casefold() for key in (
                "text", "content-desc", "label", "name", "value",
            ))
        text = " ".join(labels)
        if re.search(r"\b(?:locked|too many (?:login |sign[ -]?in )?(?:attempts|tries)|temporarily suspended|temporarily blocked)\b", text):
            return "account_locked"
        if re.search(r"\b(?:incorrect|invalid|wrong|unrecognized|not recognised|not recognized)\b", text) and re.search(
            r"\b(?:password|credential|user|account|login|sign.?in|email)\b", text,
        ):
            return "credential_rejected"
        if re.search(r"\b(?:otp|one.time password|verification code|captcha|two.factor|mfa)\b", text):
            return "additional_verification"
        if re.search(
            r"\b(?:network error|connection error|server error|service unavailable|timed out|timeout"
            r"|unexpected technical error|no internet connection)\b",
            text,
        ):
            return "service_unavailable"
        return None

    @staticmethod
    def _auth_feedback_reason(code: str) -> str:
        return {
            "account_locked": "The app reports that the UAT account is locked; no further sign-in was attempted.",
            "credential_rejected": "The app rejected the saved UAT sign-in details; no further sign-in was attempted.",
            "additional_verification": "The app requested another verification step; Autopilot did not guess or bypass it.",
            "service_unavailable": "The app reported a network or service error after sign-in; no further sign-in was attempted.",
        }[code]

    @classmethod
    def _saved_navigation_routes(
        cls,
        screens: Mapping[str, DiscoveredScreen],
        transitions: Iterable[DiscoveredTransition],
    ) -> dict[str, list[DiscoveredTransition]]:
        """Find recorded navigation that can be used to reach unfinished screens."""
        routes: dict[str, list[DiscoveredTransition]] = defaultdict(list)
        destinations: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for edge in transitions:
            destinations[(edge.from_screen_id, edge.action, edge.control_id)].add(edge.to_screen_id)
        for edge in transitions:
            source = screens.get(edge.from_screen_id)
            destination = screens.get(edge.to_screen_id)
            if (
                source is None or destination is None or source.screen_id == destination.screen_id
                or edge.prompt_path or cls._credential_controls(source) or cls._credential_controls(destination)
                or cls._is_session_timeout(source) or cls._is_session_timeout(destination)
            ):
                continue
            if len(destinations[(edge.from_screen_id, edge.action, edge.control_id)]) != 1:
                continue
            if edge.action == "tap":
                control = next((item for item in source.controls if item.control_id == edge.control_id), None)
                if (
                    control is None or control.risk != "safe" or not control.clickable
                    or not cls._eligible_navigation_controls([control], set(), transaction_context=True)
                    or cls._is_auth_entry_control(control.semantic_label)
                    or _SUBMISSION_LABEL.match(cls._normalize(control.semantic_label))
                ):
                    continue
            routes[source.screen_id].append(edge)
        return routes

    async def run(
        self,
        job_id: str,
        request: AutopilotDiscoveryRequest,
        input_values: Optional[Mapping[str, str]] = None,
        *,
        previous_discovery: Optional[AutopilotDiscoveryResult] = None,
        local_target: Optional[LocalAndroidTarget] = None,
    ) -> AutopilotDiscoveryResult:
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

        started = datetime.now(timezone.utc)
        perf = time.perf_counter()
        app_reference = request.appium_app or str(apk_path)
        browserstack_options: Dict[str, Any] | None = None
        device_farm_service = None
        device_farm_session = None
        checkpoint_message: Optional[str] = None
        transport = None
        try:
            if request.provider == "local_runner":
                if local_target is None:
                    raise LocalDeviceUnavailable("Select a paired Android runner and repository APK.")
                transport = await LocalAutopilotTransport.open(self.settings, local_target)
                appium_url = transport
                app_reference = ""
            elif request.provider == "browserstack":
                # Keep the upload/provider handshake inside the guarded
                # discovery path. A provider quota or credential failure is
                # an actionable blocked run, not an unhandled 500/network
                # error, and the UI can then tell the user how to proceed.
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
            elif request.provider == "devicefarm":
                device_farm_service, device_farm_session = await self.prototype._start_device_farm_session(
                    job_id,
                    request,
                    apk_path,
                    analysis.sha256,
                    session_name=f"QTXpert Discovery {job_id[:8]}",
                )
                appium_url = device_farm_session.appium_url
                app_reference = device_farm_session.app_arn
            else:
                # BrowserStack uses its own configured hub. Custom-Appium
                # validation must not run for that provider.
                appium_url = self.prototype.resolve_appium_url(request)
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
                    input_values or {},
                    **({"previous_discovery": previous_discovery} if previous_discovery is not None else {}),
                ),
                timeout=self.settings.AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS,
            )
            checkpoint_stop = bool(payload.get("authentication_blocked")) or str(payload.get("stop_reason") or "").lower().startswith(
                (
                    "authentication", "sign-in", "credentials", "saved credentials",
                    "the observed sign-in", "the app rejected", "the app reports",
                    "the app reported", "otp checkpoint",
                )
            )
            target_ready = payload.get("target_ready")
            interactive_surface_ready = payload.get("interactive_surface_ready")
            launch_wait_exhausted = interactive_surface_ready is False and target_ready is not False
            checkpoint_message = payload.get("checkpoint_message")
            if launch_wait_exhausted and not checkpoint_message:
                checkpoint_message = (
                    "The expected app was verified, but only a non-interactive launch or sparse screen appeared after bounded waits. "
                    "Check whether the UAT build finished starting or is waiting on an app/device setup step. "
                    "Resolve the startup state, then retry discovery. "
                    "No functional journeys were inferred."
                )
            provider_interruption = payload.get("provider_interruption")
            navigation_interrupted = str(payload.get("stop_reason") or "").startswith(("Stopped ", "Discovery stopped "))
            status = (
                "blocked"
                if target_ready is False
                else "partial" if provider_interruption or checkpoint_stop or launch_wait_exhausted or navigation_interrupted
                else "completed" if payload["screens"]
                else "partial"
            )
            error = provider_interruption or (payload.get("target_identity_reason") if target_ready is False else None)
        except Exception as exc:
            payload = {
                "screens": [], "transitions": [], "actions_attempted": 0,
                "stop_reason": "Discovery could not start or complete", "warnings": [],
                "target_ready": False,
                "interactive_surface_ready": False,
                "target_identity_reason": f"{type(exc).__name__}: {exc}"[:1200],
            }
            status = "blocked" if isinstance(exc, LocalDeviceUnavailable) or self.prototype._looks_like_connector_problem(exc) else "failed"
            error = payload["target_identity_reason"]
        finally:
            if transport is not None:
                await transport.close()
            await self.prototype._stop_device_farm_session(device_farm_service, device_farm_session)

        finished = datetime.now(timezone.utc)
        screens: list[DiscoveredScreen] = payload["screens"]
        controls = [control for screen in screens for control in screen.controls]
        bounded = str(payload.get("stop_reason") or "").lower()
        reached_budget = any(token in bounded for token in ("max_screens", "max_actions", "bounds reached", "discovery time budget"))
        can_continue = reached_budget
        if target_kind == "android":
            remaining = int(payload.get("unvisited_edge_count") or 0)
            routes_ran_out = bool(payload.get("frontier_unreachable"))
            retryable_frontier = routes_ran_out and remaining > 0 and (
                previous_discovery is None
                or len(screens) > previous_discovery.screen_count
                or remaining < previous_discovery.unvisited_edge_count
            )
            can_continue = bool(
                not request.observe_only and screens and payload.get("target_ready") is True
                and (reached_budget or payload.get("provider_interruption") or retryable_frontier)
            )
            if (can_continue or routes_ran_out) and status == "completed":
                status = "partial"
        cursor = (
            hashlib.sha256(
                f"{job_id}|{finished.isoformat()}|{request.continuation_token or ''}".encode()
            ).hexdigest()[:32]
            if can_continue
            else None
        )
        transitions = payload["transitions"]
        verified_otp_fields = payload.get("verified_otp_fields") or []
        if previous_discovery is not None:
            unique_transitions = {}
            for edge in transitions:
                key = (
                    edge.from_screen_id, edge.to_screen_id, edge.action, edge.control_id,
                    tuple((branch.prompt_id, branch.choice_key) for branch in edge.prompt_path),
                )
                unique_transitions.setdefault(key, edge)
            transitions = list(unique_transitions.values())
        return AutopilotDiscoveryResult(
            job_id=job_id,
            status=status,
            target_kind=target_kind,
            target_url=job.get("target_url"),
            provider=request.provider,
            local_runner_id=request.local_runner_id,
            verified_otp_fields=verified_otp_fields,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(time.perf_counter() - perf, 2),
            device_name=request.device_name,
            observe_only=request.observe_only,
            full_uat_exploration=bool(payload.get("full_uat_exploration")),
            screen_count=len(screens),
            control_count=len(controls),
            safe_control_count=sum(control.risk == "safe" for control in controls),
            blocked_control_count=sum(control.risk == "blocked" for control in controls),
            actions_attempted=int(payload["actions_attempted"]),
            stop_reason=str(payload["stop_reason"]),
            target_ready=payload.get("target_ready"),
            interactive_surface_ready=payload.get("interactive_surface_ready"),
            authenticated_surface_observed=payload.get("authenticated_surface_observed"),
            checkpoint_message=checkpoint_message,
            target_identity=payload.get("target_identity"),
            target_activity=payload.get("target_activity"),
            target_identity_reason=payload.get("target_identity_reason"),
            screens=screens,
            transitions=transitions,
            runtime_prompts=payload.get("runtime_prompts") or [],
            entry_prompt_path=payload.get("entry_prompt_path") or [],
            input_requests=[
                item for item in self.runtime_input_requests(screens)
                if item.key not in verified_otp_fields
            ],
            warnings=payload["warnings"],
            error=error,
            exploration_cursor=cursor,
            can_continue=can_continue,
            visited_screen_count=len(screens),
            unvisited_edge_count=int(payload.get("unvisited_edge_count", 0)),
        )

    def _run_sync(
        self,
        job_id: str,
        appium_url: str | LocalAutopilotTransport,
        app_reference: str,
        request: AutopilotDiscoveryRequest,
        package_hint: Optional[str],
        activity_hint: Optional[str],
        browserstack_options: Dict[str, Any] | None,
        install_timeout_ms: int,
        server_launch_timeout_ms: int,
        adb_exec_timeout_ms: int,
        input_values: Optional[Mapping[str, str]] = None,
        *,
        previous_discovery: Optional[AutopilotDiscoveryResult] = None,
    ) -> Dict[str, Any]:
        from appium import webdriver
        from appium.webdriver.client_config import AppiumClientConfig
        from appium.webdriver.common.appiumby import AppiumBy

        is_ios = request.target_kind == "ios"
        is_device_farm = request.provider == "devicefarm"
        timeout_seconds = getattr(self.settings, "AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS", None)
        # Leave time to close the driver and return the saved map before the
        # outer request timeout. The walker stops at an action boundary.
        crawl_deadline = (
            time.monotonic() + max(1, timeout_seconds - 30)
            if request.target_kind == "android" and timeout_seconds else float("inf")
        )
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:noReset": request.no_reset or bool(
                request.provider == "local_runner" and previous_discovery
                and previous_discovery.target_ready is True
            ),
            "appium:newCommandTimeout": 180,
        }
        if request.provider == "local_runner" and not request.observe_only:
            # Retain the live app between crawl passes while the paired runner
            # releases its Appium connection for other project work.
            capabilities["appium:dontStopAppOnReset"] = True
        # AWS installs the APK when opening its remote-access session. Its
        # upload ARN is not a valid appium:app URL; retain the installed app.
        if not is_device_farm:
            capabilities["appium:app"] = app_reference
        if package_hint:
            # Supplying recovered manifest identity makes cloud launch
            # deterministic and gives target validation a stable expectation.
            capabilities["appium:appPackage"] = package_hint
        if activity_hint:
            capabilities["appium:appActivity"] = activity_hint
        if is_ios:
            capabilities.update(
                {
                    "appium:wdaLaunchTimeout": server_launch_timeout_ms,
                    "appium:wdaConnectionTimeout": adb_exec_timeout_ms,
                    "appium:useNewWDA": False,
                }
            )
        elif is_device_farm:
            # Discovery must observe permission dialogs as branch points.
            capabilities["appium:autoGrantPermissions"] = False
        else:
            capabilities.update(
                {
                    "appium:autoGrantPermissions": False,
                    "appium:androidInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
                    "appium:adbExecTimeout": adb_exec_timeout_ms,
                    "appium:appWaitDuration": adb_exec_timeout_ms,
                }
            )
        if request.platform_version and not is_device_farm:
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
        local_connection = appium_url.connection() if isinstance(appium_url, LocalAutopilotTransport) else None
        client_config = AppiumClientConfig(remote_server_addr=appium_url) if local_connection is None else None
        # Bound each HTTP request so a stale Device Farm session cannot hold
        # the discovery worker indefinitely. This complements server-side
        # appium:newCommandTimeout.
        if client_config is not None:
            client_config.timeout = max(30, min(180, int(adb_exec_timeout_ms / 1000)))
        appium_started = time.monotonic()
        try:
            driver = webdriver.Remote(
                local_connection or appium_url,
                options=options,
                client_config=client_config,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "autopilot_stage=appium_session_create outcome=error flow=discovery elapsed_ms=%s error_type=%s",
                max(0, round((time.monotonic() - appium_started) * 1000)),
                type(exc).__name__[:80],
            )
            raise
        logging.getLogger(__name__).info(
            "autopilot_stage=appium_session_create outcome=success flow=discovery elapsed_ms=%s",
            max(0, round((time.monotonic() - appium_started) * 1000)),
        )
        screens = [screen.model_copy(deep=True) for screen in previous_discovery.screens] if previous_discovery else []
        saved_screens = {screen.screen_id: screen for screen in screens}
        saved_transitions = previous_discovery.transitions if previous_discovery else []
        transitions = list(saved_transitions)
        seen_fingerprints = {screen.fingerprint: screen.screen_id for screen in screens}
        runtime_prompts = [prompt.model_copy(deep=True) for prompt in previous_discovery.runtime_prompts] if previous_discovery else []
        entry_prompt_path = list(previous_discovery.entry_prompt_path) if previous_discovery else []
        last_capture_prompt_path: list[RuntimePromptBranchRef] = []
        pending_prompt_outcomes: list[tuple[RuntimePromptObservation, str]] = []
        pending_prompt_links: list[tuple[RuntimePromptObservation, str]] = []
        visited_edges = set()
        renewed_backtracks: set[tuple[str, str]] = set()
        transaction_screen_ids: set[str] = set()
        scroll_rounds: dict[tuple[str, str], int] = {}
        unavailable_routes: set[tuple[str, str, str]] = set()
        for edge in saved_transitions:
            source = saved_screens.get(edge.from_screen_id)
            destination = saved_screens.get(edge.to_screen_id)
            if source is None or destination is None:
                continue
            if edge.action == "tap" and not (
                self._is_auth_entry_control(edge.control_label) and self._credential_controls(destination)
            ):
                visited_edges.add((source.screen_id, edge.control_id))
            if edge.action == "scroll":
                direction = "right" if edge.control_label.casefold() == "scroll right" else "down"
                scroll_rounds[(source.screen_id, direction)] = 3
            if edge.action in {"tap", "scroll"} and (
                source.screen_id in transaction_screen_ids
                or edge.action == "tap" and request.include_transaction_journeys
                and self._is_transaction_navigation_entry(edge.control_label)
            ):
                transaction_screen_ids.add(destination.screen_id)
        warnings: list[str] = []
        actions_attempted = 0
        verified_otp_fields = set(previous_discovery.verified_otp_fields) if previous_discovery else set()
        next_screen_number = 1 + max(
            (int(screen_id.removeprefix("screen-")) for screen_id in saved_screens
             if screen_id.removeprefix("screen-").isdigit()),
            default=0,
        )
        screen_limit = len(saved_screens) + request.max_screens
        stop_reason = "Discovery bounds reached"
        frontier_unreachable = False
        launch_surface_incomplete = False
        authenticated_surface_observed = False
        explore_named_uat_controls = False
        target_ready: Optional[bool] = None
        target_identity: Optional[str] = None
        target_activity: Optional[str] = None
        target_identity_reason: Optional[str] = None
        recovered_auth_surfaces: set[tuple[str, str]] = set()

        def read_discovery_source() -> str:
            return safe_page_source(driver, detect_android_disconnect=request.provider in {"appium", "local_runner"} and not is_ios)

        def discard_startup_observations(keep: Optional[DiscoveredScreen] = None) -> None:
            screens[:] = list(saved_screens.values())
            if keep is not None and keep.screen_id not in saved_screens:
                screens.append(keep)
            seen_fingerprints.clear()
            seen_fingerprints.update({screen.fingerprint: screen.screen_id for screen in screens})

        def scoped_controls(screen: DiscoveredScreen) -> list[DiscoveredControl]:
            if not request.scope_modules:
                return screen.controls
            return [control for control in screen.controls if scope_allows_navigation(
                request.scope_modules, control.semantic_label, inside=screen.in_requested_scope,
            )]

        def pending_controls(screen: DiscoveredScreen, visited: set[str]) -> list[DiscoveredControl]:
            return self._eligible_navigation_controls(
                scoped_controls(screen), visited,
                include_transaction_journeys=request.include_transaction_journeys,
                transaction_context=screen.screen_id in transaction_screen_ids,
                explore_named_uat_controls=explore_named_uat_controls,
            )

        def next_saved_hop(origin: DiscoveredScreen) -> Optional[DiscoveredTransition]:
            route_screens = {screen.screen_id: screen for screen in screens}
            routes = self._saved_navigation_routes(route_screens, transitions)
            visited_by_screen: dict[str, set[str]] = defaultdict(set)
            for screen_id, control_id in visited_edges:
                visited_by_screen[screen_id].add(control_id)
            queue: deque[tuple[str, Optional[DiscoveredTransition]]] = deque([(origin.screen_id, None)])
            seen = {origin.screen_id}
            while queue:
                screen_id, first_hop = queue.popleft()
                for edge in routes.get(screen_id, []):
                    key = (edge.from_screen_id, edge.control_id, edge.to_screen_id)
                    if key in unavailable_routes or edge.to_screen_id in seen:
                        continue
                    destination = route_screens[edge.to_screen_id]
                    hop = first_hop or edge
                    if pending_controls(destination, visited_by_screen[edge.to_screen_id]) or any(
                        scroll_rounds.get((edge.to_screen_id, direction), 0) < 3
                        for direction in self._scroll_directions(destination)
                    ):
                        return hop
                    seen.add(edge.to_screen_id)
                    queue.append((edge.to_screen_id, hop))
            return None

        def remaining_control_count() -> int:
            visited_by_screen: dict[str, set[str]] = defaultdict(set)
            for screen_id, control_id in visited_edges:
                visited_by_screen[screen_id].add(control_id)
            for transition in transitions:
                if transition.action == "tap":
                    visited_by_screen[transition.from_screen_id].add(transition.control_id)
            return sum(len(pending_controls(screen, visited_by_screen[screen.screen_id])) for screen in screens)

        def capture(
            *,
            persist_evidence: bool = True,
            require_target: bool = False,
            source_screen: Optional[DiscoveredScreen] = None,
            trigger_control: Optional[DiscoveredControl] = None,
            trigger_control_id: Optional[str] = None,
        ) -> tuple[DiscoveredScreen, bool]:
            nonlocal actions_attempted, last_capture_prompt_path, next_screen_number
            last_capture_prompt_path = []
            first_prompt_in_capture = True
            prompt_source_screen_id = source_screen.screen_id if source_screen else None
            prompt_trigger_control_id = (
                trigger_control.control_id if trigger_control else trigger_control_id
            )
            page_source = read_discovery_source()
            for _prompt_index in range(8):
                prompt = self._runtime_prompt_observation(
                    driver,
                    page_source,
                    evidence_dir,
                    request.target_kind,
                    persist_evidence=persist_evidence,
                )
                if prompt is None:
                    break
                if first_prompt_in_capture and (prompt_source_screen_id or prompt_trigger_control_id):
                    prompt = prompt.model_copy(update={
                        "source_screen_id": prompt_source_screen_id,
                        "trigger_control_id": prompt_trigger_control_id,
                    })
                initial_prompt_id = prompt.prompt_id
                existing_prompt_index = next(
                    (i for i, item in enumerate(runtime_prompts) if item.prompt_id == prompt.prompt_id),
                    None,
                )
                if existing_prompt_index is None:
                    runtime_prompts.append(prompt)
                elif (
                    first_prompt_in_capture
                    and not runtime_prompts[existing_prompt_index].source_screen_id
                    and prompt_source_screen_id
                ):
                    runtime_prompts[existing_prompt_index] = runtime_prompts[existing_prompt_index].model_copy(
                        update={
                            "source_screen_id": prompt_source_screen_id,
                            "trigger_control_id": prompt_trigger_control_id,
                        }
                    )
                    prompt = runtime_prompts[existing_prompt_index]
                first_prompt_in_capture = False
                if pending_prompt_links:
                    for source_prompt, choice_key in pending_prompt_links:
                        source_prompt.choices = [
                            choice.model_copy(update={"resulting_prompt_id": prompt.prompt_id})
                            if choice.key == choice_key and choice.outcome_status == "observed"
                            else choice
                            for choice in source_prompt.choices
                        ]
                    pending_prompt_links.clear()
                if request.observe_only:
                    break
                from_sign_in = bool(
                    source_screen and trigger_control
                    and self._credential_controls(source_screen)
                    and self._is_auth_entry_control(trigger_control.semantic_label)
                )
                selected_key, clicked = self._choose_system_prompt_branch(
                    driver,
                    prompt.choices,
                    AppiumBy,
                    prompt_kind=prompt.kind,
                    allow_app_confirmation=(
                        request.full_uat_exploration
                        and request.confirm_isolated_uat
                        and self.settings.full_uat_target_is_allowed(request.target_kind, target_identity, package_hint)
                        and (from_sign_in or source_screen is None or source_screen.screen_id not in transaction_screen_ids)
                    ),
                )
                if selected_key and clicked:
                    actions_attempted += 1
                elif prompt.choices:
                    warnings.append(
                        f"Could not activate an observed choice for the {prompt.kind.replace('_', ' ')} prompt; "
                        "the prompt was retained for branch execution."
                    )
                try:
                    # Use Back only when no observed branch choice was available;
                    # recovery is not reported as an observed prompt outcome.
                    if not (selected_key and clicked):
                        driver.back()
                except Exception:
                    pass
                prompt_deadline = time.monotonic() + 8.0
                decline_returned_to_app = False
                followup_prompt_kind: Optional[str] = None
                while time.monotonic() < prompt_deadline:
                    page_source = read_discovery_source()
                    active_prompt_kind = self._runtime_prompt_kind(driver, page_source, request.target_kind)
                    if active_prompt_kind:
                        active_prompt_id = self._runtime_prompt_fingerprint(
                            driver,
                            page_source,
                            request.target_kind,
                        )
                        if active_prompt_kind != prompt.kind or (
                            active_prompt_id and initial_prompt_id and active_prompt_id != initial_prompt_id
                        ):
                            followup_prompt_kind = active_prompt_kind
                            break
                    else:
                        decline_returned_to_app, _, _ = validate_target_surface(
                            driver,
                            expected_package=package_hint,
                            expected_activity=activity_hint,
                            page_source=page_source,
                        )
                        if decline_returned_to_app:
                            break
                    time.sleep(0.25)
                if selected_key:
                    prompt.choices = [
                        choice.model_copy(
                            update={
                                "outcome_status": "observed"
                                if clicked and (decline_returned_to_app or followup_prompt_kind)
                                else "unavailable"
                            }
                        )
                        if choice.key == selected_key
                        else choice
                        for choice in prompt.choices
                    ]
                    if clicked and decline_returned_to_app:
                        pending_prompt_outcomes.append((prompt, selected_key))
                        last_capture_prompt_path.append(
                            RuntimePromptBranchRef(prompt_id=prompt.prompt_id, choice_key=selected_key)
                        )
                    elif clicked and followup_prompt_kind:
                        pending_prompt_links.append((prompt, selected_key))
                        last_capture_prompt_path.append(
                            RuntimePromptBranchRef(prompt_id=prompt.prompt_id, choice_key=selected_key)
                        )
                if followup_prompt_kind:
                    # A different observed native prompt is a valid outcome of
                    # this branch. Capture it on the next loop iteration and
                    # continue through its own safe decline branch.
                    page_source = safe_page_source(driver)
                    prompt_source_screen_id = None
                    prompt_trigger_control_id = None
                    continue
                returned_to_app = decline_returned_to_app
                if not returned_to_app:
                    # A native prompt can remain foreground after a choice.
                    # Dismiss only a recognized Android system prompt, then
                    # verify the uploaded app before resuming; recovery is not
                    # evidence of the selected branch's outcome.
                    prompt_kind = self._runtime_prompt_kind(
                        driver,
                        safe_page_source(driver),
                        request.target_kind,
                    )
                    if prompt_kind and str(request.target_kind or "").casefold() == "android":
                        try:
                            safe_navigate_back(driver, target_kind="android")
                        except Exception:
                            pass
                        else:
                            recovery_deadline = time.monotonic() + 5.0
                            while time.monotonic() < recovery_deadline:
                                recovery_source = safe_page_source(driver)
                                if self._runtime_prompt_kind(
                                    driver,
                                    recovery_source,
                                    request.target_kind,
                                ) is None:
                                    returned_to_app, _, _ = validate_target_surface(
                                        driver,
                                        expected_package=package_hint,
                                        expected_activity=activity_hint,
                                        page_source=recovery_source,
                                    )
                                    if returned_to_app:
                                        break
                                time.sleep(0.25)
                    if not returned_to_app:
                        try:
                            returned_to_app, _, _ = activate_verified_target_surface(
                                driver,
                                package_hint,
                                expected_activity=activity_hint,
                                timeout_seconds=10.0,
                                poll_interval=0.5,
                                page_source=safe_page_source(driver),
                            )
                        except Exception:
                            returned_to_app = False
                    if not returned_to_app:
                        warnings.append(
                            f"The {prompt.kind.replace('_', ' ')} prompt did not return to the uploaded app after safe recovery."
                        )
                        break
                page_source = safe_page_source(driver)
            controls = self._ensure_auth_input_semantics(self.parse_controls(page_source))
            if require_target:
                target_ok, reason, _ = validate_target_surface(
                    driver,
                    expected_package=package_hint,
                    expected_activity=activity_hint,
                    page_source=page_source,
                    control_labels=[control.semantic_label for control in controls],
                )
                if (
                    not target_ok and not is_ios and package_hint
                    and "Google Play Services UI is active." in reason
                    and source_screen and trigger_control and self._credential_controls(source_screen)
                ):
                    recovery_key = (source_screen.screen_id, trigger_control.control_id)
                    if recovery_key not in recovered_auth_surfaces:
                        recovered_auth_surfaces.add(recovery_key)
                        restored, _, _ = activate_verified_target_surface(
                            driver, package_hint, timeout_seconds=5.0, page_source=page_source,
                        )
                        if restored:
                            page_source = read_discovery_source()
                            controls = self._ensure_auth_input_semantics(self.parse_controls(page_source))
                            target_ok, reason, _ = validate_target_surface(
                                driver, expected_package=package_hint, expected_activity=activity_hint,
                                page_source=page_source, control_labels=[control.semantic_label for control in controls],
                            )
                            if target_ok:
                                warnings.append("Autopilot restored the uploaded app after a Google Play Services interruption.")
                if not target_ok:
                    raise _UnexpectedTargetSurface(reason)
            identity = safe_app_identity(
                driver,
                page_source=page_source,
                package_hint=package_hint,
                activity_hint=activity_hint,
            )
            package_name = identity["package"]
            activity_name = identity["activity"]
            active_tabs = self._active_tab_labels(controls)
            heading = next((
                control.semantic_label for control in controls
                if not control.clickable and not control.input_capable and control.semantic_label
                and control.class_name in {"android.widget.TextView", "XCUIElementTypeStaticText"}
            ), "") if request.scope_modules and not active_tabs else ""
            heading_module = next((module for module in request.scope_modules if matches_module([module], heading)), None)
            issue = "The app displayed a technical or service error." if any(
                re.search(r"\b(?:unexpected technical error|system error|service unavailable|network error|no internet connection)\b",
                          control.semantic_label, re.I)
                for control in controls
            ) else None
            scoped_from_parent = bool(
                source_screen and source_screen.in_requested_scope and not active_tabs
                and (trigger_control is None or not is_transit(trigger_control.semantic_label))
            )
            fp = self.fingerprint(package_name, activity_name, controls)
            scoped_from_entry = bool(
                source_screen and trigger_control and fp != source_screen.fingerprint
                and matches_module(request.scope_modules, trigger_control.semantic_label)
            )
            in_scope = bool(request.scope_modules and (
                matches_module(request.scope_modules, *active_tabs) if active_tabs
                else bool(heading_module) or scoped_from_parent or scoped_from_entry
            ))
            duplicate_screen_id = seen_fingerprints.get(fp)
            if duplicate_screen_id is None:
                near_duplicate = next(
                    (
                        existing
                        for existing in screens
                        if self._screen_similarity(
                            existing,
                            package_name,
                            activity_name,
                            controls,
                            require_matching_viewport=bool(
                                trigger_control_id and trigger_control_id.startswith("__scroll__")
                            ),
                        ) >= 0.78
                    ),
                    None,
                )
                duplicate_screen_id = near_duplicate.screen_id if near_duplicate else None
            duplicate = duplicate_screen_id is not None
            screen_number = next_screen_number
            screen_id = duplicate_screen_id or f"screen-{screen_number:03d}"
            if duplicate:
                existing = next(screen for screen in screens if screen.screen_id == screen_id)
                existing.in_requested_scope = existing.in_requested_scope or in_scope
                if heading_module:
                    existing.page_label, existing.journey = heading, heading_module
                if issue and issue not in existing.observed_issues:
                    existing.observed_issues.append(issue)
                # Keep one canonical replay root for a volatile-but-equivalent
                # state while retaining the union of safe controls observed on
                # both provider frames.
                self._merge_screen_controls(existing, controls)
                # The post-login capture is intentionally non-persistent to
                # avoid writing typed credentials into evidence. Once the
                # credentials have been submitted, persist the resulting
                # authenticated screen (and any later duplicate) with the
                # same redaction policy so journey cases have usable proof.
                if pending_prompt_outcomes:
                    for prompt, choice_key in pending_prompt_outcomes:
                        prompt.choices = [
                            choice.model_copy(update={"resulting_screen_id": screen_id})
                            if choice.key == choice_key and choice.outcome_status == "observed"
                            else choice
                            for choice in prompt.choices
                        ]
                    pending_prompt_outcomes.clear()
                if persist_evidence and not (
                    existing.screenshot_path or existing.page_source_path
                    or existing.screenshot_asset_id or existing.page_source_asset_id
                ):
                    screenshot_path = evidence_dir / f"{screen_id}.png"
                    source_path = evidence_dir / f"{screen_id}.xml"
                    try:
                        driver.get_screenshot_as_file(str(screenshot_path))
                    except Exception as exc:
                        warnings.append(f"Screenshot capture failed on {screen_id}: {type(exc).__name__}")
                    source_path.write_text(self._redact_page_source(page_source), encoding="utf-8")
                    existing.screenshot_path = str(screenshot_path) if screenshot_path.exists() else None
                    existing.page_source_path = str(source_path)
                return existing, True
            next_screen_number += 1
            screenshot_path = evidence_dir / f"{screen_id}.png"
            source_path = evidence_dir / f"{screen_id}.xml"
            if persist_evidence:
                try:
                    driver.get_screenshot_as_file(str(screenshot_path))
                except Exception as exc:
                    warnings.append(f"Screenshot capture failed on {screen_id}: {type(exc).__name__}")
                source_path.write_text(self._redact_page_source(page_source), encoding="utf-8")
            screen = DiscoveredScreen(
                screen_id=screen_id,
                in_requested_scope=in_scope,
                observed_issues=[issue] if issue else [],
                fingerprint=fp,
                package_name=package_name,
                activity_name=activity_name,
                journey=heading_module or observed_journey_label(
                    DiscoveredScreen(
                        screen_id=screen_id,
                        fingerprint=fp,
                        package_name=package_name,
                        activity_name=activity_name,
                        controls=controls,
                    ),
                    screen_number,
                ),
                page_label=(heading if heading_module else None) or observed_page_label(
                    DiscoveredScreen(
                        screen_id=screen_id,
                        fingerprint=fp,
                        package_name=package_name,
                        activity_name=activity_name,
                        controls=controls,
                    ),
                    screen_number,
                ),
                screenshot_path=str(screenshot_path) if persist_evidence and screenshot_path.exists() else None,
                page_source_path=str(source_path) if persist_evidence else None,
                controls=controls,
            )
            if request.scope_modules and not active_tabs:
                screen.in_requested_scope = in_scope or matches_module(
                    request.scope_modules, screen.page_label, screen.title, screen.journey,
                )
            screens.append(screen)
            seen_fingerprints[fp] = screen_id
            if pending_prompt_outcomes:
                for prompt, choice_key in pending_prompt_outcomes:
                    prompt.choices = [
                        choice.model_copy(update={"resulting_screen_id": screen_id})
                        if choice.key == choice_key and choice.outcome_status == "observed"
                        else choice
                        for choice in prompt.choices
                    ]
                pending_prompt_outcomes.clear()
            return screen, False

        try:
            # Appium sessions can report the launch/splash hierarchy before
            # the first real screen is ready. Settle it with a bounded retry
            # instead of treating the splash as the complete app map.
            initial_wait = max(1, min(5, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_SECONDS", 15))))
            retry_wait = max(1, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_SECONDS", 15)))
            retry_limit = max(0, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_RETRIES", 6)))
            max_settle_seconds = initial_wait + retry_wait * retry_limit
            logging.getLogger(__name__).info(
                "autopilot_stage=app_launch_settle_config initial_wait_seconds=%s "
                "retry_wait_seconds=%s retry_limit=%s max_wait_seconds=%s",
                initial_wait,
                retry_wait,
                retry_limit,
                max_settle_seconds,
            )
            time.sleep(initial_wait)
            # Keep launch/splash surfaces in memory until target identity has
            # been checked. If the provider left Android Home foreground, it
            # must never be persisted as an InvestNation product screen.
            current, _ = capture(persist_evidence=False)
            entry_prompt_path = list(last_capture_prompt_path)
            retries = 0
            while self._looks_like_loading_screen(current) and retries < retry_limit:
                retries += 1
                time.sleep(retry_wait)
                candidate, duplicate = capture(persist_evidence=False)
                if last_capture_prompt_path:
                    entry_prompt_path = list(last_capture_prompt_path)
                current_score = sum(1 for item in current.controls if item.enabled and (item.clickable or item.input_capable))
                candidate_score = sum(1 for item in candidate.controls if item.enabled and (item.clickable or item.input_capable))
                if not duplicate or candidate_score >= current_score:
                    current = candidate
            if self._looks_like_loading_screen(current):
                launch_surface_incomplete = True
                warnings.append(
                    f"Initial app screen remained non-interactive after {retries} bounded settle attempt(s), with no safe entry point; "
                    "the launch state was retained as evidence and no controls were auto-clicked."
                )
                stop_reason = (
                    "App remained on a non-interactive launch screen or sparse surface after bounded settling; "
                    "no safe entry point was available, so login and workflows were not inferred."
                )
            elif not saved_screens and current is not screens[0]:
                # The replay root must be the settled app, not its splash.
                screens.remove(current)
                screens.insert(0, current)
            # A successful WebDriver handshake does not prove that the
            # uploaded application is foreground.  Validate the observed
            # package/surface before interpreting any controls as product UI.
            # This catches the exact degraded state where BrowserStack returns
            # only ``navigationBarBackground`` and prevents a false completed
            # discovery with zero functional journeys.
            target_ready, target_identity_reason, identity = validate_target_surface(
                driver,
                expected_package=package_hint,
                expected_activity=activity_hint,
                page_source=read_discovery_source(),
                control_labels=[control.semantic_label for control in current.controls],
            )
            target_identity = identity.get("package")
            target_activity = identity.get("activity")
            if not target_ready and package_hint:
                # A hosted Appium command may report that an activity launch
                # succeeded while leaving the launcher/system app foreground.
                # Try the observed activity and package activation in order,
                # verifying the actual UI package after each attempt.
                try:
                    discard_startup_observations()
                    retry_ready, retry_reason, retry_identity = activate_verified_target_surface(
                        driver,
                        package_hint,
                        expected_activity=activity_hint,
                        timeout_seconds=15.0,
                        poll_interval=0.5,
                        page_source=read_discovery_source(),
                    )
                    if retry_ready:
                        candidate, _ = capture(persist_evidence=False)
                        candidate_ready, candidate_reason, candidate_identity = validate_target_surface(
                            driver,
                            expected_package=package_hint,
                            expected_activity=activity_hint,
                            page_source=read_discovery_source(),
                            control_labels=[control.semantic_label for control in candidate.controls],
                        )
                        if candidate_ready:
                            current = candidate
                            target_ready = True
                            target_identity_reason = candidate_reason or retry_reason
                            target_identity = candidate_identity.get("package") or retry_identity.get("package")
                            target_activity = candidate_identity.get("activity") or retry_identity.get("activity")
                            if launch_surface_incomplete and not self._looks_like_loading_screen(candidate):
                                # Recovery reached an interactive, verified app
                                # screen. Do not leave the earlier splash/system
                                # surface flag gating the entire crawl.
                                launch_surface_incomplete = False
                                stop_reason = "Discovery bounds reached"
                                warnings = [
                                    warning for warning in warnings
                                    if not warning.startswith("Initial app screen remained non-interactive")
                                ]
                                warnings.append(
                                    "The verified app moved past its startup surface during recovery; discovery resumed."
                                )
                        else:
                            target_identity_reason = candidate_reason
                            discard_startup_observations()
                    else:
                        target_identity_reason = retry_reason
                        target_identity = retry_identity.get("package")
                        target_activity = retry_identity.get("activity")
                        discard_startup_observations()
                except AndroidDeviceDisconnected:
                    raise
                except Exception as exc:
                    discard_startup_observations()
                    warnings.append(
                        f"Explicit target activation retry was unavailable: {type(exc).__name__}"
                    )
            if not target_ready:
                warnings.append(target_identity_reason)
                return {
                    "screens": [],
                    "transitions": [],
                    "runtime_prompts": runtime_prompts,
                    "entry_prompt_path": entry_prompt_path,
                    "actions_attempted": actions_attempted,
                    "stop_reason": target_identity_reason,
                    "warnings": warnings,
                    "target_ready": False,
                    "interactive_surface_ready": False,
                    "target_identity": target_identity,
                    "target_activity": target_activity,
                    "target_identity_reason": target_identity_reason,
                }
            explore_named_uat_controls = (
                request.full_uat_exploration
                and request.confirm_isolated_uat
                and self.settings.full_uat_target_is_allowed(request.target_kind, target_identity, package_hint)
            )
            # Persist only the now-verified target root. This also upgrades an
            # identical in-memory candidate if the session needed activation.
            current, _ = capture(persist_evidence=True, require_target=True)
            if launch_surface_incomplete and not self._looks_like_loading_screen(current):
                # The final package-verified capture can observe controls that
                # appeared just after the last bounded settle sample. Recheck
                # that exact frame before returning the earlier splash result;
                # otherwise a slow Flutter start can leave a usable login or
                # dashboard surface stranded behind a stale partial status.
                launch_surface_incomplete = False
                stop_reason = "Discovery recovered from startup surface"
                warnings = [
                    warning for warning in warnings
                    if not warning.startswith("Initial app screen remained non-interactive")
                ]
                warnings.append(
                    "The verified app became interactive in the final startup capture; discovery resumed."
                )
                discard_startup_observations(current)
            connectivity_blocked = self._has_blocking_connectivity_dialog(current)
            if launch_surface_incomplete or connectivity_blocked:
                if connectivity_blocked:
                    stop_reason = "The app reported No Internet Connection before it opened an interactive surface."
                    checkpoint_message = (
                        "The app reported No Internet Connection. Check that the test device can reach the app's "
                        "UAT services, then retry discovery."
                    )
                else:
                    diagnostic = self._startup_surface_diagnostic(driver, package_hint)
                    if diagnostic:
                        warnings.append(diagnostic)
                        stop_reason = f"{stop_reason} {diagnostic}"
                    checkpoint_message = (
                        "The expected app was verified, but only a non-interactive launch or sparse screen appeared after bounded waits. "
                        "Check whether the UAT build finished starting or is waiting on an app/device setup step. "
                        "Resolve the startup state, then retry discovery. "
                        "No functional journeys were inferred."
                    )
                # Keep the launch-state diagnosis authoritative. A verified package with no readable controls is not a completed app crawl.
                return {
                    "screens": screens,
                    "transitions": [],
                    "runtime_prompts": runtime_prompts,
                    "entry_prompt_path": entry_prompt_path,
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                    "authentication_blocked": False,
                    "target_ready": target_ready,
                    "interactive_surface_ready": False,
                    "checkpoint_message": checkpoint_message,
                    "target_identity": target_identity,
                    "target_activity": target_activity,
                    "target_identity_reason": target_identity_reason,
                }
            if request.observe_only:
                stop_reason = (
                    "Observe-only discovery captured an incomplete launch screen; no login or workflows were inferred"
                    if launch_surface_incomplete
                    else "Observe-only discovery captured the current screen"
                )
                return {
                    "screens": screens,
                    "transitions": transitions,
                    "runtime_prompts": runtime_prompts,
                    "entry_prompt_path": entry_prompt_path,
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                    "target_ready": target_ready,
                    "interactive_surface_ready": not launch_surface_incomplete,
                    "target_identity": target_identity,
                    "target_activity": target_activity,
                    "target_identity_reason": target_identity_reason,
                }

            # Authentication is the first user checkpoint.  Never walk past a
            # login hierarchy or fabricate a credential; when the caller has
            # already supplied approved, decrypted values we fill them only in
            # the live session and suppress the immediate evidence snapshot.
            input_values = input_values or {}
            authentication_blocked = False
            successful_authentications = 0
            timeout_recovery_epochs: dict[str, int] = {}
            stack: list[DiscoveredScreen] = []
            unresolved_authentication: dict[str, str] = {}
            used_otp_fields: set[str] = set()

            def process_authentication(
                screen: DiscoveredScreen,
            ) -> tuple[DiscoveredScreen, bool, Optional[str]]:
                nonlocal actions_attempted, authenticated_surface_observed, successful_authentications
                auth_rounds = 0
                while screen is not None:
                    credential_controls = self._credential_controls(screen)
                    if not credential_controls:
                        has_dismissal = any(
                            control.enabled and control.clickable
                            and self._normalize(control.semantic_label) in {"ok", "okay", "dismiss", "close"}
                            for control in screen.controls
                        )
                        if has_dismissal and self._auth_feedback_code(read_discovery_source()) == "credential_rejected":
                            reason = self._auth_feedback_reason("credential_rejected")
                            if reason not in screen.observed_issues:
                                screen.observed_issues.append(reason)
                            return screen, True, reason
                        return screen, False, None
                    otp_keys = {
                        self.runtime_input_key(screen.screen_id, item.control_id, item.input_kind or "credential")
                        for item in credential_controls if self._credential_hint(item) == "otp"
                    }
                    if otp_keys & used_otp_fields:
                        return screen, True, "OTP checkpoint detected. Request a new code for this challenge."
                    auth_rounds += 1
                    if auth_rounds > 3:
                        return (
                            screen,
                            True,
                            "Authentication has more than three sequential checkpoints; continue under supervision.",
                        )
                    checkpoint_reason = self._authentication_checkpoint_reason(screen, input_values)
                    if checkpoint_reason:
                        return screen, True, checkpoint_reason
                    if actions_attempted >= request.max_actions:
                        return (
                            screen,
                            True,
                            f"Authentication values are ready, but max_actions={request.max_actions} was reached",
                        )
                    try:
                        entry_confirmations: list[bool] = []
                        for control in credential_controls:
                            value = self._credential_value(screen.screen_id, control, input_values)
                            if value is None:
                                continue
                            element = self._find_discovered_element(driver, control, AppiumBy)
                            confirmed = enter_observed_text(
                                driver, element, value,
                                target_kind="ios" if is_ios else "android",
                                verify_text=self._credential_hint(control) == "username",
                                # Secure Flutter fields cannot be read back.
                                # Target the observed element first: Android's
                                # generic keyboard extension may silently
                                # alter punctuation while still enabling Login.
                                prefer_element_entry=self._credential_hint(control) == "password",
                            )
                            if confirmed is not None:
                                entry_confirmations.append(confirmed)
                        submit = self._refresh_auth_submit(driver, screen, package_hint, activity_hint)
                        if submit is None and not is_ios:
                            # Secure fields intentionally cannot be read back.
                            # If the observed submit remains disabled, retry
                            # only the same password field through ordinary
                            # element entry; this does not submit a login or
                            # expose its value in evidence/diagnostics.
                            password_control = next(
                                (item for item in credential_controls if self._credential_hint(item) == "password"),
                                None,
                            )
                            if password_control is not None:
                                password_value = self._credential_value(
                                    screen.screen_id, password_control, input_values,
                                )
                                if password_value is not None:
                                    password_element = self._find_discovered_element(
                                        driver, password_control, AppiumBy,
                                    )
                                    enter_observed_text(
                                        driver, password_element, password_value,
                                        target_kind="android", verify_text=False,
                                        # The element path did not enable the
                                        # observed submit. Retry the alternate
                                        # keyboard path exactly once, replacing
                                        # the same field rather than appending.
                                        prefer_element_entry=False,
                                    )
                                    submit = self._refresh_auth_submit(
                                        driver, screen, package_hint, activity_hint,
                                    )
                        if submit is None:
                            observed_submit = self._auth_submit_control(screen.controls, include_disabled=True)
                            submit_buttons = [
                                item for item in screen.controls
                                if item.class_name in {"android.widget.Button", "XCUIElementTypeButton"}
                                and self._normalize(item.semantic_label) in _AUTH_SUBMIT_TERMS
                            ]
                            warnings.append(
                                "Sign-in diagnostics: "
                                f"observed_fields={len(credential_controls)}, "
                                f"user_id_entry_confirmed={all(entry_confirmations) if entry_confirmations else 'unavailable'}, "
                                f"submit_buttons={len(submit_buttons)}, "
                                f"submit_enabled={sum(item.enabled for item in submit_buttons)}, "
                                f"submit_clickable={sum(item.clickable for item in submit_buttons)}. "
                                "No input values were recorded."
                            )
                            logging.getLogger(__name__).info("%s", warnings[-1])
                            return screen, True, (
                                "The observed sign-in button did not become enabled after entering the saved credentials. "
                                "Authentication was not submitted; review the app's sign-in field validation."
                                if observed_submit is not None and not observed_submit.enabled
                                else "Saved credentials were entered, but no enabled observed sign-in action was available."
                            )
                        if actions_attempted >= request.max_actions:
                            return (
                                screen,
                                True,
                                f"Authentication values are ready, but max_actions={request.max_actions} was reached",
                            )
                        submit_element = self._find_discovered_element(driver, submit, AppiumBy)
                        used_otp_fields.update(otp_keys)
                        pre_submit_source = safe_page_source(driver)
                        pre_submit_feedback = self._auth_feedback_code(pre_submit_source)
                        submit_element.click()
                        actions_attempted += 1
                        transition_prompt_path: list[RuntimePromptBranchRef] = []
                        # A changed fingerprint may be a transient Flutter
                        # skeleton, not the authenticated landing. Observe a
                        # bounded series of credential-safe frames and wait
                        # for a usable surface before treating login as done.
                        next_screen, duplicate = screen, True
                        transient_loading_screen_ids: set[str] = set()
                        password_stage = any(
                            self._credential_hint(control) == "password"
                            for control in credential_controls
                        )
                        # Give a submitted password more time for the UAT
                        # backend to respond before considering a second tap.
                        for observation in range(18 if password_stage else 8):
                            time.sleep(1.0 if observation else 1.5)
                            next_screen, duplicate = capture(
                                persist_evidence=False,
                                require_target=True,
                                source_screen=screen,
                                trigger_control=submit,
                            )
                            if last_capture_prompt_path:
                                transition_prompt_path = list(last_capture_prompt_path)
                            if self._looks_like_loading_screen(next_screen):
                                transient_loading_screen_ids.add(next_screen.screen_id)
                                continue
                            if next_screen.screen_id != screen.screen_id:
                                break
                        # A validation message is often static text and does
                        # not change the actionable-control fingerprint. Never
                        # turn an explicit rejection into a second login tap.
                        post_native_source = safe_page_source(driver)
                        feedback_code = self._auth_feedback_code(post_native_source)
                        if feedback_code and (
                            feedback_code != pre_submit_feedback
                            or feedback_code in {"credential_rejected", "account_locked", "service_unavailable"}
                        ):
                            warnings.append(f"Sign-in feedback category: {feedback_code}. No credential values were recorded.")
                            return screen, True, self._auth_feedback_reason(feedback_code)
                        same_form = next_screen.screen_id == screen.screen_id
                        if not same_form and self._credential_controls(next_screen):
                            prior_hints = {self._credential_hint(item) for item in credential_controls}
                            next_hints = {
                                self._credential_hint(item)
                                for item in self._credential_controls(next_screen)
                            }
                            if prior_hints == next_hints:
                                warnings.append(
                                    "Sign-in UI changed but still requested the same credential stage; "
                                    "no credential values or page text were recorded."
                                )
                                return screen, True, (
                                    "The app changed its sign-in display but still requests the same credentials. "
                                    "Review the app's visible validation or service response before retrying."
                                )
                        # Flutter/Android can ignore WebDriver's native click
                        # even when the semantic button advertises clickable.
                        # Retry once if the same actionable form remains after
                        # the bounded wait. Unrelated hierarchy changes such as
                        # rotating promotional copy do not identify a new form.
                        username_stage = any(
                            self._credential_hint(control) == "username"
                            for control in credential_controls
                        )
                        gesture_attempted = False
                        current_submit = self._auth_submit_control(next_screen.controls) if same_form else None
                        if (
                            same_form and not otp_keys and (username_stage or password_stage)
                            and not feedback_code
                            and not self._runtime_prompt_kind(driver, post_native_source, request.target_kind)
                            and submit.enabled and not is_ios
                            and current_submit is not None
                            and current_submit.control_id == submit.control_id
                            and current_submit.enabled
                            and actions_attempted < request.max_actions
                        ):
                            try:
                                refreshed_element = self._find_discovered_element(driver, current_submit, AppiumBy)
                                if not getattr(refreshed_element, "id", None):
                                    raise LookupError("No observed element identifier for gesture")
                                gesture_attempted = True
                                driver.execute_script("mobile: clickGesture", {"elementId": refreshed_element.id})
                                actions_attempted += 1
                                for observation in range(18 if password_stage else 8):
                                    time.sleep(1.0 if observation else 1.5)
                                    next_screen, duplicate = capture(
                                        persist_evidence=False,
                                        require_target=True,
                                        source_screen=screen,
                                        trigger_control=submit,
                                    )
                                    if last_capture_prompt_path:
                                        transition_prompt_path = list(last_capture_prompt_path)
                                    if self._looks_like_loading_screen(next_screen):
                                        transient_loading_screen_ids.add(next_screen.screen_id)
                                        continue
                                    if next_screen.screen_id != screen.screen_id:
                                        break
                            except Exception as gesture_error:
                                warnings.append(
                                    "Observed sign-in gesture was unavailable: "
                                    f"{type(gesture_error).__name__}. No credential values were recorded."
                                )
                        # After the rapid poll, reuse the app-launch settle
                        # budget for slow authenticated shells. This covers
                        # apps that replace the login form with a generic
                        # ImageView/HorizontalScrollView skeleton first.
                        if self._looks_like_loading_screen(next_screen):
                            for _settle_retry in range(retry_limit):
                                time.sleep(retry_wait)
                                candidate, candidate_duplicate = capture(
                                    persist_evidence=False,
                                    require_target=True,
                                    source_screen=screen,
                                    trigger_control=submit,
                                )
                                if last_capture_prompt_path:
                                    transition_prompt_path = list(last_capture_prompt_path)
                                next_screen = candidate
                                duplicate = candidate_duplicate
                                if self._looks_like_loading_screen(candidate):
                                    transient_loading_screen_ids.add(candidate.screen_id)
                                    continue
                                break
                            post_native_source = safe_page_source(driver)
                            feedback_code = self._auth_feedback_code(post_native_source)
                            if feedback_code and (
                                feedback_code != pre_submit_feedback
                                or feedback_code in {"credential_rejected", "account_locked", "service_unavailable"}
                            ):
                                warnings.append(
                                    f"Sign-in feedback category: {feedback_code}. No credential values were recorded."
                                )
                                return screen, True, self._auth_feedback_reason(feedback_code)
                        if self._looks_like_loading_screen(next_screen):
                            # Exclude placeholders from the product map and
                            # generated functional cases while retaining the
                            # observed failure in the discovery warnings.
                            transient_loading_screen_ids.add(next_screen.screen_id)
                            for transient_id in transient_loading_screen_ids:
                                if transient_id in saved_screens:
                                    continue
                                transient_screen = next(
                                    (item for item in screens if item.screen_id == transient_id),
                                    None,
                                )
                                if transient_screen is not None and self._looks_like_loading_screen(transient_screen):
                                    screens.remove(transient_screen)
                                    if seen_fingerprints.get(transient_screen.fingerprint) == transient_id:
                                        seen_fingerprints.pop(transient_screen.fingerprint, None)
                            warnings.append(
                                "Sign-in was submitted, but the app remained on a generic loading/skeleton surface "
                                "after bounded settling. No authenticated landing or tabs were verified."
                            )
                            return (
                                screen,
                                True,
                                "Sign-in did not reach a usable post-login screen after bounded settling; "
                                "the authenticated journey remains incomplete.",
                            )
                        next_has_sensitive_inputs = bool(self._credential_controls(next_screen))
                        evidence_interruption = None
                        if not duplicate and not next_has_sensitive_inputs:
                            try:
                                next_screen, _ = capture(
                                    persist_evidence=True,
                                    require_target=True,
                                    source_screen=screen,
                                    trigger_control=submit,
                                )
                                if last_capture_prompt_path:
                                    transition_prompt_path = list(last_capture_prompt_path)
                            except _UnexpectedTargetSurface as exc:
                                # The first verified target observation still
                                # proves the landing. Retain it and report the
                                # foreground interruption separately.
                                evidence_interruption = str(exc)
                        for transient_id in transient_loading_screen_ids:
                            if transient_id == next_screen.screen_id or transient_id in saved_screens:
                                continue
                            transient_screen = next(
                                (item for item in screens if item.screen_id == transient_id),
                                None,
                            )
                            if transient_screen is not None and self._looks_like_loading_screen(transient_screen):
                                screens.remove(transient_screen)
                                if seen_fingerprints.get(transient_screen.fingerprint) == transient_id:
                                    seen_fingerprints.pop(transient_screen.fingerprint, None)
                        transitions.append(
                            DiscoveredTransition(
                                from_screen_id=screen.screen_id,
                                to_screen_id=next_screen.screen_id,
                                control_id=submit.control_id,
                                control_label=submit.semantic_label,
                                duplicate_state=duplicate,
                                prompt_path=transition_prompt_path,
                            )
                        )
                        if self._is_session_timeout(next_screen):
                            return next_screen, True, "The app expired the session immediately after sign-in."
                        same_form = next_screen.screen_id == screen.screen_id
                        if not same_form and not next_has_sensitive_inputs and not self._looks_like_loading_screen(next_screen):
                            verified_otp_fields.update(otp_keys)
                            authenticated_surface_observed = True
                            successful_authentications += 1
                        if evidence_interruption:
                            return next_screen, True, f"Sign-in reached the app, then its foreground was interrupted: {evidence_interruption}"
                        if same_form:
                            final_source = safe_page_source(driver)
                            feedback_code = self._auth_feedback_code(final_source)
                            if feedback_code and (
                                feedback_code != pre_submit_feedback
                                or feedback_code in {"credential_rejected", "account_locked", "service_unavailable"}
                            ):
                                warnings.append(f"Sign-in feedback category: {feedback_code}. No credential values were recorded.")
                                return screen, True, self._auth_feedback_reason(feedback_code)
                            warnings.append(
                                "Sign-in interaction diagnostics: "
                                f"stage={'password' if password_stage else 'username'}, "
                                f"semantic_clickable={submit.clickable}, "
                                f"native_source_changed={post_native_source != pre_submit_source}, "
                                f"gesture_attempted={gesture_attempted}, "
                                f"final_source_changed={final_source != pre_submit_source}. "
                                "No credential values or page text were recorded."
                            )
                            logging.getLogger(__name__).info("%s", warnings[-1])
                            return (
                                screen,
                                True,
                                "The observed sign-in form stayed unchanged after bounded submission, with no recognized validation message. "
                                "Whether the cause is the input, app service, or device interaction remains unverified.",
                            )
                        screen = next_screen
                    except AndroidDeviceDisconnected:
                        raise
                    except _UnexpectedTargetSurface as exc:
                        return (
                            screen,
                            True,
                            f"Sign-in left the uploaded app surface and was stopped safely: {exc}",
                        )
                    except Exception as exc:
                        warnings.append(
                            f"Could not safely submit the approved sign-in form: {type(exc).__name__}"
                        )
                        return (
                            screen,
                            True,
                            "Authentication could not be completed safely; review the sign-in checkpoint",
                        )
                return screen, False, None

            def recover_from_authentication_checkpoint(
                screen: DiscoveredScreen,
                blocked: bool,
                reason: Optional[str],
            ) -> tuple[DiscoveredScreen, bool, Optional[str], bool]:
                """Return from an unresolved authentication branch to a known parent."""
                reason_text = str(reason or "").casefold()
                otp_checkpoint = reason_text.startswith("otp checkpoint")
                if not blocked or not reason:
                    return screen, blocked, reason, False
                unresolved_authentication[screen.screen_id] = reason
                for control in self._credential_controls(screen):
                    if self._credential_hint(control) == "otp":
                        verified_otp_fields.discard(self.runtime_input_key(
                            screen.screen_id, control.control_id, control.input_kind or "credential",
                        ))
                if not stack or "max_actions=" in reason_text:
                    return screen, blocked, reason, False
                if reason_text.startswith("authentication checkpoint") and not any(
                    pending_controls(
                        ancestor, {control_id for screen_id, control_id in visited_edges if screen_id == ancestor.screen_id},
                    )
                    for ancestor in stack
                ):
                    return screen, blocked, reason, False
                ancestor_ids = [item.screen_id for item in stack]
                for _ in range(min(6, max(1, len(screens) + 1))):
                    try:
                        safe_navigate_back(driver, target_kind=request.target_kind)
                        time.sleep(0.6)
                        recovered, _ = capture(persist_evidence=False, require_target=True)
                    except AndroidDeviceDisconnected:
                        raise
                    except Exception as exc:
                        warnings.append(
                            f"Authentication branch recovery could not return to an observed app screen: {type(exc).__name__}."
                        )
                        return screen, True, reason, False
                    if recovered.screen_id in ancestor_ids:
                        ancestor_index = ancestor_ids.index(recovered.screen_id)
                        stack[:] = stack[:ancestor_index]
                        if otp_checkpoint:
                            warnings.append(
                                "The observed sign-in path requested an OTP. That branch remains incomplete; "
                                "discovery returned to an observed parent screen and continued other app journeys."
                            )
                        else:
                            warnings.append(
                                "A sign-in branch needs input or review. Discovery returned to an observed parent "
                                "and continued other safe journeys."
                            )
                        return recovered, False, reason, True
                warnings.append(
                    "The authentication branch was not retried because no previously observed parent screen could be restored."
                )
                return screen, True, reason, False

            current, authentication_blocked, authentication_reason = process_authentication(current)
            current, authentication_blocked, authentication_reason, _ = recover_from_authentication_checkpoint(
                current, authentication_blocked, authentication_reason,
            )
            if authentication_reason:
                stop_reason = authentication_reason

            frontier_restart_attempted = False
            # A bounded depth-first traversal explores sibling navigation controls
            # instead of following one path and stopping at the first leaf. Every
            # edge is attempted at most once per observed screen; all backtracking
            # is reversible and destructive controls remain excluded by risk.
            if not authentication_blocked and current is not None and not launch_surface_incomplete:
                while (
                    len(screens) < screen_limit and actions_attempted < request.max_actions
                    and time.monotonic() < crawl_deadline
                ):
                    visited_for_screen = {
                        control_id for screen_id, control_id in visited_edges if screen_id == current.screen_id
                    }
                    expired_session = self._is_session_timeout(current)
                    if expired_session and successful_authentications > timeout_recovery_epochs.get(current.screen_id, 0):
                        # A new successful session makes the same observed Login
                        # entry usable again when that session subsequently expires.
                        visited_for_screen.difference_update(
                            control.control_id for control in current.controls
                            if self._is_auth_entry_control(control.semantic_label)
                        )
                    control = self._select_safe_control(
                        scoped_controls(current),
                        visited_for_screen,
                        include_transaction_journeys=request.include_transaction_journeys,
                        transaction_context=current.screen_id in transaction_screen_ids,
                        explore_named_uat_controls=explore_named_uat_controls,
                        observed_tabs={label for screen in screens for label in self._active_tab_labels(screen.controls)},
                    )
                    if control is None:
                        # A large portion of mobile navigation is hidden below
                        # the first viewport. Give each observed screen a
                        # bounded opportunity to reveal additional controls
                        # before backtracking to its parent. The scroll itself
                        # is recorded in the graph so generated cases replay
                        # the same route.
                        direction = next(
                            (
                                candidate
                                for candidate in self._scroll_directions(current)
                                if scroll_rounds.get((current.screen_id, candidate), 0) < 3
                            ),
                            None,
                        )
                        if direction is not None and actions_attempted < request.max_actions:
                            round_key = (current.screen_id, direction)
                            rounds = scroll_rounds.get(round_key, 0)
                            can_scroll_more = self._scroll_forward(driver, direction=direction, controls=current.controls)
                            if can_scroll_more is None:
                                scroll_rounds[round_key] = 3
                                continue
                            scroll_rounds[round_key] = rounds + 1 if can_scroll_more else 3
                            actions_attempted += 1
                            try:
                                next_screen, duplicate = capture(
                                    require_target=True,
                                    source_screen=current,
                                    trigger_control_id=f"__scroll__{direction}__{rounds + 1}",
                                )
                            except _UnexpectedTargetSurface as exc:
                                warnings.append(
                                    f"Stopped before counting a screen outside the uploaded app after scrolling: {exc}"
                                )
                                stop_reason = "Discovery stopped at the uploaded-app boundary."
                                break
                            if current.screen_id in transaction_screen_ids:
                                transaction_screen_ids.add(next_screen.screen_id)
                            transitions.append(
                                DiscoveredTransition(
                                    from_screen_id=current.screen_id,
                                    to_screen_id=next_screen.screen_id,
                                    control_id=f"__scroll__{direction}__{rounds + 1}",
                                    control_label=f"Scroll {direction}",
                                    action="scroll",
                                    duplicate_state=duplicate,
                                    prompt_path=list(last_capture_prompt_path),
                                )
                            )
                            if not can_scroll_more:
                                scroll_rounds[(next_screen.screen_id, direction)] = 3
                            current = next_screen
                            continue
                        if not stack:
                            saved_hop = next_saved_hop(current) if not is_ios else None
                            if saved_hop is None:
                                unvisited = remaining_control_count()
                                terminator = getattr(driver, "terminate_app", None)
                                if (
                                    unvisited and package_hint and not is_ios
                                    and request.provider in {"appium", "local_runner"}
                                    and not frontier_restart_attempted and callable(terminator)
                                    and not self._active_tab_labels(current.controls)
                                    and not self._credential_controls(current) and not expired_session
                                    and self._auth_feedback_code(read_discovery_source()) == "service_unavailable"
                                ):
                                    # A service-error leaf can swallow Back. Restart the same
                                    # app once, keeping the map, visited edges and app data.
                                    frontier_restart_attempted = True
                                    actions_attempted += 1
                                    try:
                                        terminator(package_hint)
                                        time.sleep(0.5)
                                        reopened, reason, _ = activate_verified_target_surface(
                                            driver, package_hint, expected_activity=activity_hint,
                                            force_launch=True, preserve_known_system_prompt=True,
                                        )
                                        if not reopened:
                                            raise _UnexpectedTargetSurface(reason)
                                        recovered, _ = capture(persist_evidence=False, require_target=True)
                                        settle_deadline = min(crawl_deadline, time.monotonic() + 12)
                                        while self._looks_like_loading_screen(recovered) and time.monotonic() < settle_deadline:
                                            time.sleep(0.8)
                                            recovered, _ = capture(persist_evidence=False, require_target=True)
                                        if self._looks_like_loading_screen(recovered) or recovered.screen_id == current.screen_id:
                                            raise _UnexpectedTargetSurface("No interactive recovery screen was observed.")
                                        recovered, _ = capture(require_target=True)
                                    except AndroidDeviceDisconnected:
                                        raise
                                    except Exception as exc:
                                        warnings.append(f"Could not reopen the uploaded app after its service error ({type(exc).__name__}).")
                                    else:
                                        warnings.append("Reopened the uploaded app after its service error and resumed discovery.")
                                        current, authentication_blocked, authentication_reason = process_authentication(recovered)
                                        if authentication_blocked:
                                            stop_reason = authentication_reason or "Stopped at the authentication checkpoint after reopening the app."
                                            break
                                        continue
                                if not is_ios and unvisited:
                                    frontier_unreachable = True
                                    stop_reason = f"Discovery stopped with {unvisited} controls beyond the routes it could reopen."
                                else:
                                    stop_reason = "No additional safe navigation controls were available"
                                break
                            route_key = (saved_hop.from_screen_id, saved_hop.control_id, saved_hop.to_screen_id)
                            actions_before_replay = actions_attempted
                            try:
                                route_control = None
                                if saved_hop.action == "tap":
                                    route_control = next(item for item in current.controls if item.control_id == saved_hop.control_id)
                                    if route_control.risk != "safe" or not self._eligible_navigation_controls(
                                        [route_control], set(), transaction_context=True,
                                    ):
                                        raise LookupError("The observed route control is unavailable.")
                                    route_element = self._find_discovered_element(driver, route_control, AppiumBy)
                                    actions_attempted += 1
                                    route_element.click()
                                    if _TAB_POSITION.search(self._normalize(route_control.semantic_label)):
                                        self._wait_for_tab_selection(driver, route_control.semantic_label)
                                    else:
                                        time.sleep(1.2)
                                elif saved_hop.action == "scroll":
                                    direction = "right" if saved_hop.control_label.casefold() == "scroll right" else "down"
                                    actions_attempted += 1
                                    if self._scroll_forward(driver, direction=direction, controls=current.controls) is None:
                                        raise LookupError("The recorded scroll gesture is unavailable.")
                                else:
                                    actions_attempted += 1
                                    safe_navigate_back(driver, target_kind=request.target_kind)
                                    time.sleep(0.8)
                                reached, duplicate = capture(
                                    require_target=True,
                                    source_screen=current,
                                    trigger_control=route_control,
                                    trigger_control_id=saved_hop.control_id,
                                )
                            except AndroidDeviceDisconnected:
                                raise
                            except _UnexpectedTargetSurface:
                                stop_reason = "Discovery stopped because replaying a recorded route left the uploaded app."
                                break
                            except Exception as exc:
                                unavailable_routes.add(route_key)
                                warnings.append(f"Could not reopen a recorded route ({type(exc).__name__}).")
                                if actions_attempted > actions_before_replay:
                                    stop_reason = "Discovery stopped because the next app screen could not be verified after navigation."
                                    break
                                continue
                            if reached.screen_id != saved_hop.to_screen_id or last_capture_prompt_path:
                                unavailable_routes.add(route_key)
                                transitions.append(saved_hop.model_copy(update={
                                    "to_screen_id": reached.screen_id,
                                    "duplicate_state": duplicate,
                                    "prompt_path": list(last_capture_prompt_path),
                                }))
                            current, authentication_blocked, authentication_reason = process_authentication(reached)
                            if authentication_blocked:
                                stop_reason = authentication_reason or "Stopped at an authentication checkpoint on a recorded route."
                                break
                            continue
                        parent = stack.pop()
                        try:
                            safe_navigate_back(driver, target_kind=request.target_kind)
                            time.sleep(0.8)
                            recovered, recovered_duplicate = capture(
                                persist_evidence=False,
                                require_target=True,
                            )
                            transitions.append(
                                DiscoveredTransition(
                                    from_screen_id=current.screen_id,
                                    to_screen_id=recovered.screen_id,
                                    control_id="__back__",
                                    control_label="Back",
                                    action="back",
                                    duplicate_state=recovered_duplicate,
                                )
                            )
                            current = recovered
                        except AndroidDeviceDisconnected:
                            raise
                        except Exception as exc:
                            warnings.append(f"Could not backtrack safely: {type(exc).__name__}: {str(exc)[:180]}")
                            recovery_path = (current.screen_id, parent.screen_id)
                            if recovery_path in renewed_backtracks:
                                stop_reason = "Stopped because safe backtracking was unavailable"
                                break
                            renewed_backtracks.add(recovery_path)
                            try:
                                reopened, reason, _ = activate_verified_target_surface(
                                    driver,
                                    package_hint,
                                    expected_activity=activity_hint,
                                    page_source=read_discovery_source(),
                                    force_launch=True,
                                    preserve_known_system_prompt=True,
                                )
                                if not reopened:
                                    raise _UnexpectedTargetSurface(reason)
                                recovered, _ = capture(require_target=True)
                            except AndroidDeviceDisconnected:
                                raise
                            except Exception as recovery_error:
                                warnings.append(f"Could not reopen the uploaded app: {type(recovery_error).__name__}.")
                                stop_reason = "Stopped because safe backtracking was unavailable"
                                break
                            stack.clear()
                            warnings.append("Reopened the uploaded app after backtracking and resumed discovery.")
                            current, authentication_blocked, authentication_reason = process_authentication(recovered)
                            if authentication_blocked:
                                stop_reason = authentication_reason or "Stopped at the authentication checkpoint after reopening the app"
                                break
                        continue
                    visited_edges.add((current.screen_id, control.control_id))
                    if expired_session and self._is_auth_entry_control(control.semantic_label):
                        timeout_recovery_epochs[current.screen_id] = successful_authentications
                    try:
                        element = self._find_discovered_element(driver, control, AppiumBy)
                        element.click()
                        actions_attempted += 1
                        if _TAB_POSITION.search(self._normalize(control.semantic_label)):
                            self._wait_for_tab_selection(driver, control.semantic_label)
                        else:
                            time.sleep(1.2)
                        next_screen, duplicate = capture(
                            require_target=True,
                            source_screen=current,
                            trigger_control=control,
                        )
                        if (
                            current.screen_id in transaction_screen_ids
                            or request.include_transaction_journeys
                            and self._is_transaction_navigation_entry(control.semantic_label)
                        ):
                            transaction_screen_ids.add(next_screen.screen_id)
                        transitions.append(
                            DiscoveredTransition(
                                from_screen_id=current.screen_id,
                                to_screen_id=next_screen.screen_id,
                                control_id=control.control_id,
                                control_label=control.semantic_label,
                                duplicate_state=duplicate,
                                prompt_path=list(last_capture_prompt_path),
                            )
                        )
                        if duplicate and (
                            current.screen_id == next_screen.screen_id
                            or not self._credential_controls(next_screen)
                        ):
                            # Stay on the observed screen after a duplicate tap.
                            # An Android Back action can leave the tab or app
                            # before the remaining sibling controls are tried.
                            current = next_screen
                            continue
                        stack.append(current)
                        current = next_screen
                        # Login may be behind a public landing screen. Treat
                        # that newly observed form as the checkpoint before
                        # the walker attempts any other screen action.
                        if self._credential_controls(current):
                            auth_screen_id = current.screen_id
                            current, authentication_blocked, authentication_reason = process_authentication(current)
                            if authentication_reason:
                                stop_reason = authentication_reason
                            current, authentication_blocked, authentication_reason, checkpoint_resumed = recover_from_authentication_checkpoint(
                                current, authentication_blocked, authentication_reason,
                            )
                            if authentication_blocked:
                                break
                            if checkpoint_resumed:
                                continue
                            # Keep the observed parent stack so public sibling
                            # journeys remain crawlable after authentication.
                            # The login edge is already visited, so returning
                            # to that parent will not submit the same form again.
                            if current.screen_id != auth_screen_id:
                                continue
                    except _UnexpectedTargetSurface as exc:
                        warnings.append(
                            f"Navigation control {control.semantic_label!r} left the uploaded app; its destination was not recorded: {exc}"
                        )
                        reviewed_controls = [
                            item.model_copy(
                                update={
                                    "risk": "review",
                                    "risk_reason": "This action left the uploaded application; the external surface was excluded.",
                                }
                            )
                            if item.control_id == control.control_id
                            else item
                            for item in current.controls
                        ]
                        current = current.model_copy(update={"controls": reviewed_controls})
                        for screen_index, item in enumerate(screens):
                            if item.screen_id == current.screen_id:
                                screens[screen_index] = current
                                break
                        try:
                            if package_hint:
                                driver.activate_app(package_hint)
                            else:
                                safe_navigate_back(driver, target_kind=request.target_kind)
                            time.sleep(1.2)
                            recovered, _ = capture(
                                persist_evidence=False,
                                require_target=True,
                            )
                            if recovered.screen_id != current.screen_id:
                                stack.clear()
                            current, authentication_blocked, authentication_reason = process_authentication(recovered)
                            if authentication_blocked:
                                stop_reason = authentication_reason or "Stopped at the authentication checkpoint after reopening the app"
                                break
                            continue
                        except AndroidDeviceDisconnected:
                            raise
                        except Exception as recovery_exc:
                            warnings.append(
                                f"Could not restore the uploaded app after leaving its boundary: {type(recovery_exc).__name__}"
                            )
                            stop_reason = "Discovery stopped because the uploaded app could not be safely restored."
                            break
                    except AndroidDeviceDisconnected:
                        raise
                    except Exception as exc:
                        warnings.append(
                            f"Could not safely interact with {control.semantic_label}: {type(exc).__name__}: {str(exc)[:180]}"
                        )
                        if not explore_named_uat_controls and len(warnings) >= 5:
                            stop_reason = "Stopped after repeated safe-navigation interaction failures"
                            break
                else:
                    if len(screens) >= screen_limit:
                        stop_reason = f"Reached max_screens={request.max_screens}"
                    elif actions_attempted >= request.max_actions:
                        stop_reason = f"Reached max_actions={request.max_actions}"
                    elif time.monotonic() >= crawl_deadline:
                        stop_reason = "Reached the discovery time budget"

            if unresolved_authentication:
                crawl_stop_reason = stop_reason
                checkpoint_note = " ".join(dict.fromkeys(unresolved_authentication.values()))
                stop_reason = (
                    f"{checkpoint_note} Sibling journeys were explored where reachable. "
                    f"Crawl ended: {crawl_stop_reason}"
                )
            if request.scope_modules and not any(screen.in_requested_scope for screen in screens):
                warnings.append("The requested module was not observed on a reachable screen.")

            return {
                "screens": screens,
                "transitions": transitions,
                "runtime_prompts": runtime_prompts,
                "entry_prompt_path": entry_prompt_path,
                "actions_attempted": actions_attempted,
                "unvisited_edge_count": remaining_control_count(),
                "frontier_unreachable": frontier_unreachable,
                "stop_reason": stop_reason,
                "warnings": warnings,
                "authentication_blocked": authentication_blocked,
                "verified_otp_fields": sorted(verified_otp_fields),
                "authenticated_surface_observed": authenticated_surface_observed,
                "full_uat_exploration": explore_named_uat_controls,
                "target_ready": target_ready,
                "interactive_surface_ready": not launch_surface_incomplete,
                "target_identity": target_identity,
                "target_activity": target_activity,
                "target_identity_reason": target_identity_reason,
            }
        except AndroidDeviceDisconnected as exc:
            reason = str(exc)
            return {
                "screens": screens if target_ready else [],
                "transitions": transitions if target_ready else [],
                "runtime_prompts": runtime_prompts,
                "entry_prompt_path": entry_prompt_path,
                "actions_attempted": actions_attempted,
                "stop_reason": reason,
                "warnings": warnings,
                "provider_interruption": reason,
                "verified_otp_fields": sorted(verified_otp_fields),
                "checkpoint_message": reason,
                "unvisited_edge_count": remaining_control_count() if target_ready else 0,
                "target_ready": target_ready is True,
                "interactive_surface_ready": bool(target_ready and screens and not launch_surface_incomplete),
                "authenticated_surface_observed": authenticated_surface_observed,
                "full_uat_exploration": explore_named_uat_controls or bool(
                    previous_discovery and previous_discovery.full_uat_exploration
                ),
                "target_identity": target_identity,
                "target_activity": target_activity,
                "target_identity_reason": target_identity_reason,
            }
        finally:
            safe_quit(driver)




