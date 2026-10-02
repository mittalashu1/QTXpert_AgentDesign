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
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.appium_compat import (
    activate_verified_target_surface,
    enter_observed_text,
    safe_app_identity,
    safe_page_source,
    safe_navigate_back,
    safe_quit,
    validate_target_surface,
)
from app.services.autopilot_labels import input_probe_guidance, observed_journey_label, observed_page_label


_BLOCKED_TERMS = {
    "pay", "payment", "payments", "transfer", "transfers", "send money", "send funds", "purchase", "buy",
    "checkout", "place order", "confirm order", "submit order", "delete", "remove",
    "close account", "terminate", "withdraw", "deposit", "invest", "trade", "sell",
    "redeem", "approve", "authorize", "otp", "one time password", "verify otp",
    "send otp", "notify customer", "submit", "confirm", "book now", "reserve now",
}
_SAFE_NAVIGATION_TERMS = {
    "menu", "more", "settings", "help", "about", "search", "skip", "back", "home",
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
            for control in screen.controls:
                if not control.input_capable:
                    continue
                field_type = control.input_kind or "text"
                key = cls.runtime_input_key(screen.screen_id, control.control_id, field_type)
                if key in seen:
                    continue
                seen.add(key)
                credential = field_type == "credential"
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
                    else "Autopilot will use a bounded synthetic value for this non-sensitive field by default. Override it with a non-production value, save one encrypted for reuse, generate a different value, or skip the dependent check."
                )
                format_hint = (
                    "Password values are encrypted immediately and never included in context, reports or logs."
                    if input_hint == "password"
                    else "The first pass uses a deterministic, non-secret synthetic value matching this field. Any override is encrypted before persistence."
                )
                locator = control.locators[0].value if control.locators else None
                # Public, non-sensitive fields should not turn the first pass
                # into a questionnaire.  The compiler has a bounded,
                # deterministic synthetic-data strategy for these controls,
                # so mark them as an automatic random candidate.  Credentials
                # and OTPs remain pending and are the only fields that can
                # pause the first authenticated journey.
                autonomous_status = "pending" if credential else "random"
                requests.append(
                    AutopilotInputRequest(
                        key=key,
                        label=label,
                        category=category,
                        reason=reason,
                        required_for=[f"{screen.screen_id}: {display_label}"],
                        sensitive=credential,
                        status=autonomous_status,
                        reference_present=not credential,
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

    @staticmethod
    def _looks_like_loading_screen(screen: DiscoveredScreen) -> bool:
        """Identify splash/blank or sparse initial surfaces without a safe entry point."""
        marker_text = " ".join(
            [
                screen.activity_name or "",
                screen.title or "",
                *(control.semantic_label for control in screen.controls),
                *(control.class_name for control in screen.controls),
            ]
        ).lower()
        if any(term in marker_text for term in ("splash", "loading", "progressbar", "launchscreen", "please wait")):
            return True
        generic_labels = {
            "view", "imageview", "textview", "unknown", "layout", "framelayout",
            "linearlayout", "relativelayout", "constraintlayout", "scrollview",
            "viewgroup", "flutterview", "fluttertextureview", "surfaceview",
        }
        generic_root_classes = generic_labels | {"decorview", "fluttercontainer"}

        def has_meaningful_entry(control: DiscoveredControl) -> bool:
            label = re.sub(r"[\s_-]+", " ", str(control.semantic_label or "").lower()).strip()
            class_short = str(control.class_name or "").rsplit(".", 1)[-1].casefold()
            # Flutter/Appium may tag a splash root as an enabled or even
            # input-capable View. That implementation flag is not evidence
            # of an end-user field; generic container nodes never open a path.
            is_generic_container = label in generic_labels or class_short in generic_root_classes
            if not control.enabled:
                return False
            if is_generic_container:
                # Flutter/Appium often marks the app's splash root as a
                # scrollable, located View. That root is not a journey. Only
                # concrete child controls or actual input widgets count.
                return False
            real_input = control.input_capable
            safe_action = control.clickable and bool(control.locators) and control.risk == "safe"
            scroll_surface = control.scrollable and bool(control.locators)
            return real_input or safe_action or scroll_surface

        # Do not label a sparse, ungrounded splash/landing surface as a
        # completed crawl just because its root View has a locator or an
        # Appium interaction flag. Credential fields, safe actions, and
        # scrollable content remain valid evidence-backed entry points.
        return len(screen.controls) <= 4 and not any(
            has_meaningful_entry(control) for control in screen.controls
        )

    @classmethod
    def _risk(cls, label: str, attrs: Dict[str, str]) -> tuple[str, Optional[str]]:
        haystack = " ".join(
            [label, attrs.get("text", ""), attrs.get("label", ""), attrs.get("name", ""), attrs.get("content-desc", ""), attrs.get("resource-id", ""), attrs.get("identifier", "")]
        ).lower().replace("_", " ").replace("-", " ")
        for term in _BLOCKED_TERMS:
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
                return "blocked", f"Blocked business/destructive action matched: {term}"
        normalized = cls._normalize(label)
        normalized = re.sub(r"\s+tab\s+\d+\s+of\s+\d+$", "", normalized, flags=re.I).strip()
        if normalized in _SAFE_NAVIGATION_TERMS or any(pattern.search(normalized) for pattern in _SAFE_NAVIGATION_PATTERNS):
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
        if not inputs or submit is None:
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
                    scrollable=scrollable,
                    input_capable=input_capable,
                    input_kind=input_kind,
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

    @classmethod
    def _screen_similarity(
        cls,
        left: DiscoveredScreen,
        right_package: Optional[str],
        right_activity: Optional[str],
        right_controls: Iterable[DiscoveredControl],
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
                merged[key] = control.model_copy(update={"locators": control.locators or prior.locators})
        existing.controls = list(merged.values())

    @staticmethod
    def _is_auth_entry_control(label: str) -> bool:
        normalized = re.sub(r"[\s_-]+", " ", str(label or "").lower()).strip()
        return bool(re.search(r"\b(?:log in|login|sign in|authenticate)\b", normalized))

    @classmethod
    def _select_safe_control(cls, controls: list[DiscoveredControl], visited: set[str]) -> Optional[DiscoveredControl]:
        candidates = [
            control for control in controls
            if control.enabled and control.clickable and not control.input_capable and control.risk == "safe"
            and control.locators and control.control_id not in visited
            and cls._safe_locator_confidence(control)
        ]
        if not candidates:
            return None
        # At the app entry screen, observe a real sign-in gate before any
        # guest/demo route; confidence remains the tie-breaker within each group.
        candidates.sort(key=lambda item: (
            0 if cls._is_auth_entry_control(item.semantic_label) else 1,
            -max(locator.confidence for locator in item.locators),
            item.semantic_label.lower(),
        ))
        return candidates[0]

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
    def _scroll_forward(driver: Any) -> bool:
        """Scroll the current native surface using provider-safe gestures.

        Appium providers differ on which mobile extension they expose. Try the
        Android UiAutomator2 scroll gesture first, then the portable swipe
        extension and finally the legacy client method. An unsupported method
        is treated as an unavailable exploration capability; it never becomes
        an ``UnknownMethodException`` in the generated test result.
        """
        width, height = 1080, 1920
        try:
            size = driver.get_window_size()
            width = max(320, int(size.get("width") or width))
            height = max(480, int(size.get("height") or height))
        except Exception:
            pass
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
                    # ``scrollGesture`` returns False when the list is already
                    # at its end; preserve that signal so the graph walker can
                    # move to another branch instead of repeating forever.
                    return result is not False
                except Exception:
                    continue
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
                return True
            except TypeError:
                try:
                    swipe(
                        int(width * 0.5),
                        int(height * 0.82),
                        int(width * 0.5),
                        int(height * 0.22),
                        700,
                    )
                    return True
                except Exception:
                    pass
            except Exception:
                pass
        return False

    @classmethod
    def _credential_hint(cls, control: DiscoveredControl) -> str:
        """Classify a credential control without reading its current value."""
        haystack = " ".join(
            [control.semantic_label, control.content_description, control.resource_id, control.class_name]
        ).lower().replace("_", " ").replace("-", " ")
        if any(term in haystack for term in ("otp", "one time", "mfa", "verification code", "passcode")):
            return "otp"
        if any(term in haystack for term in ("password", "secret", "pin", "securetextfield", "passwordtext", "passwd", "pwd")) or re.search(r"\bpass\b", haystack):
            return "password"
        return "username"

    @classmethod
    def _credential_controls(cls, screen: DiscoveredScreen) -> list[DiscoveredControl]:
        return [
            control
            for control in screen.controls
            if control.enabled and control.input_capable and control.input_kind == "credential"
        ]

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
        otp_controls = [control for control in credential_controls if cls._credential_hint(control) == "otp"]
        if approved and not missing_controls and not otp_controls:
            return None
        return (
            "Authentication checkpoint detected. Enter the non-production User ID and Password "
            "(and provide an approved OTP only when the flow permits it) before Autopilot continues."
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
                class_name = str(node.attrib.get("class") or "")
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
        if re.search(r"\b(?:network error|connection error|server error|service unavailable|timed out|timeout)\b", text):
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

    async def run(
        self,
        job_id: str,
        request: AutopilotDiscoveryRequest,
        input_values: Optional[Mapping[str, str]] = None,
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
        try:
            if request.provider == "browserstack":
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
                ),
                timeout=self.settings.AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS,
            )
            checkpoint_stop = bool(payload.get("authentication_blocked")) or str(payload.get("stop_reason") or "").lower().startswith(
                ("authentication", "sign-in", "credentials", "saved credentials", "the observed sign-in")
            )
            launch_wait_exhausted = "non-interactive launch screen" in str(payload.get("stop_reason") or "").lower()
            target_ready = payload.get("target_ready")
            status = (
                "blocked"
                if target_ready is False
                else "partial" if checkpoint_stop or launch_wait_exhausted
                else "completed" if payload["screens"]
                else "partial"
            )
            error = payload.get("target_identity_reason") if target_ready is False else None
        except Exception as exc:
            payload = {
                "screens": [], "transitions": [], "actions_attempted": 0,
                "stop_reason": "Discovery could not start or complete", "warnings": [],
                "target_ready": False,
                "target_identity_reason": f"{type(exc).__name__}: {exc}"[:1200],
            }
            status = "blocked" if self.prototype._looks_like_connector_problem(exc) else "failed"
            error = payload["target_identity_reason"]
        finally:
            await self.prototype._stop_device_farm_session(device_farm_service, device_farm_session)

        finished = datetime.now(timezone.utc)
        screens: list[DiscoveredScreen] = payload["screens"]
        controls = [control for screen in screens for control in screen.controls]
        bounded = str(payload.get("stop_reason") or "").lower()
        can_continue = any(token in bounded for token in ("max_screens", "max_actions", "bounds reached"))
        cursor = (
            hashlib.sha256(
                f"{job_id}|{request.continuation_token or ''}|{len(screens)}|{int(payload['actions_attempted'])}".encode()
            ).hexdigest()[:32]
            if can_continue
            else None
        )
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
            target_ready=payload.get("target_ready"),
            target_identity=payload.get("target_identity"),
            target_activity=payload.get("target_activity"),
            target_identity_reason=payload.get("target_identity_reason"),
            screens=screens,
            transitions=payload["transitions"],
            input_requests=self.runtime_input_requests(screens),
            warnings=payload["warnings"],
            error=error,
            exploration_cursor=cursor,
            can_continue=can_continue,
            visited_screen_count=len(screens),
            unvisited_edge_count=max(0, len(controls) - len(payload.get("transitions") or [])),
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
        input_values: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        from appium import webdriver
        from appium.webdriver.common.appiumby import AppiumBy

        is_ios = request.target_kind == "ios"
        is_device_farm = request.provider == "devicefarm"
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:noReset": request.no_reset,
            "appium:newCommandTimeout": 180,
        }
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
            capabilities["appium:autoGrantPermissions"] = request.auto_grant_permissions
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
        driver = webdriver.Remote(appium_url, options=options)
        screens: list[DiscoveredScreen] = []
        transitions: list[DiscoveredTransition] = []
        seen_fingerprints: dict[str, str] = {}
        visited_edges: set[tuple[str, str]] = set()
        scroll_rounds: dict[str, int] = {}
        warnings: list[str] = []
        actions_attempted = 0
        stop_reason = "Discovery bounds reached"
        launch_surface_incomplete = False
        target_ready: Optional[bool] = None
        target_identity: Optional[str] = None
        target_activity: Optional[str] = None
        target_identity_reason: Optional[str] = None

        def capture(
            *,
            persist_evidence: bool = True,
            require_target: bool = False,
        ) -> tuple[DiscoveredScreen, bool]:
            index = len(screens) + 1
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
            fp = self.fingerprint(package_name, activity_name, controls)
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
                        ) >= 0.78
                    ),
                    None,
                )
                duplicate_screen_id = near_duplicate.screen_id if near_duplicate else None
            duplicate = duplicate_screen_id is not None
            screen_id = duplicate_screen_id or f"screen-{index:03d}"
            if duplicate:
                existing = next(screen for screen in screens if screen.screen_id == screen_id)
                # Keep one canonical replay root for a volatile-but-equivalent
                # state while retaining the union of safe controls observed on
                # both provider frames.
                self._merge_screen_controls(existing, controls)
                # The post-login capture is intentionally non-persistent to
                # avoid writing typed credentials into evidence. Once the
                # credentials have been submitted, persist the resulting
                # authenticated screen (and any later duplicate) with the
                # same redaction policy so journey cases have usable proof.
                if persist_evidence and not existing.screenshot_path and not existing.page_source_path:
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
                fingerprint=fp,
                package_name=package_name,
                activity_name=activity_name,
                journey=observed_journey_label(
                    DiscoveredScreen(
                        screen_id=screen_id,
                        fingerprint=fp,
                        package_name=package_name,
                        activity_name=activity_name,
                        controls=controls,
                    ),
                    index,
                ),
                page_label=observed_page_label(
                    DiscoveredScreen(
                        screen_id=screen_id,
                        fingerprint=fp,
                        package_name=package_name,
                        activity_name=activity_name,
                        controls=controls,
                    ),
                    index,
                ),
                screenshot_path=str(screenshot_path) if persist_evidence and screenshot_path.exists() else None,
                page_source_path=str(source_path) if persist_evidence else None,
                controls=controls,
            )
            screens.append(screen)
            seen_fingerprints[fp] = screen_id
            return screen, False

        try:
            # Appium sessions can report the launch/splash hierarchy before
            # the first real screen is ready. Settle it with a bounded retry
            # instead of treating the splash as the complete app map.
            initial_wait = max(1, min(5, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_SECONDS", 4))))
            retry_wait = max(1, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_SECONDS", 4)))
            retry_limit = max(0, int(getattr(self.settings, "AUTOPILOT_DISCOVERY_SETTLE_RETRIES", 3)))
            time.sleep(initial_wait)
            # Keep launch/splash surfaces in memory until target identity has
            # been checked. If the provider left Android Home foreground, it
            # must never be persisted as an InvestNation product screen.
            current, _ = capture(persist_evidence=False)
            retries = 0
            while self._looks_like_loading_screen(current) and retries < retry_limit:
                retries += 1
                time.sleep(retry_wait)
                candidate, duplicate = capture(persist_evidence=False)
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
            elif current is not screens[0]:
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
                page_source=safe_page_source(driver),
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
                    screens.clear()
                    seen_fingerprints.clear()
                    retry_ready, retry_reason, retry_identity = activate_verified_target_surface(
                        driver,
                        package_hint,
                        expected_activity=activity_hint,
                        timeout_seconds=15.0,
                        poll_interval=0.5,
                        page_source=safe_page_source(driver),
                    )
                    if retry_ready:
                        candidate, _ = capture(persist_evidence=False)
                        candidate_ready, candidate_reason, candidate_identity = validate_target_surface(
                            driver,
                            expected_package=package_hint,
                            expected_activity=activity_hint,
                            page_source=safe_page_source(driver),
                            control_labels=[control.semantic_label for control in candidate.controls],
                        )
                        if candidate_ready:
                            current = candidate
                            target_ready = True
                            target_identity_reason = candidate_reason or retry_reason
                            target_identity = candidate_identity.get("package") or retry_identity.get("package")
                            target_activity = candidate_identity.get("activity") or retry_identity.get("activity")
                        else:
                            target_identity_reason = candidate_reason
                            screens.clear()
                            seen_fingerprints.clear()
                    else:
                        target_identity_reason = retry_reason
                        target_identity = retry_identity.get("package")
                        target_activity = retry_identity.get("activity")
                        screens.clear()
                        seen_fingerprints.clear()
                except Exception as exc:
                    screens.clear()
                    seen_fingerprints.clear()
                    warnings.append(
                        f"Explicit target activation retry was unavailable: {type(exc).__name__}"
                    )
            if not target_ready:
                warnings.append(target_identity_reason)
                return {
                    "screens": [],
                    "transitions": [],
                    "actions_attempted": actions_attempted,
                    "stop_reason": target_identity_reason,
                    "warnings": warnings,
                    "target_ready": False,
                    "target_identity": target_identity,
                    "target_activity": target_activity,
                    "target_identity_reason": target_identity_reason,
                }
            # Persist only the now-verified target root. This also upgrades an
            # identical in-memory candidate if the session needed activation.
            current, _ = capture(persist_evidence=True, require_target=True)
            if launch_surface_incomplete:
                diagnostic = self._startup_surface_diagnostic(driver, package_hint)
                if diagnostic:
                    warnings.append(diagnostic)
                    stop_reason = f"{stop_reason} {diagnostic}"
                # Keep the launch-state diagnosis authoritative. A verified package with no readable controls is not a completed app crawl.
                return {
                    "screens": screens,
                    "transitions": [],
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                    "authentication_blocked": False,
                    "target_ready": target_ready,
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
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                    "target_ready": target_ready,
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
            auth_rounds = 0

            def process_authentication(
                screen: DiscoveredScreen,
            ) -> tuple[DiscoveredScreen, bool, Optional[str]]:
                nonlocal actions_attempted, auth_rounds
                while screen is not None:
                    credential_controls = self._credential_controls(screen)
                    if not credential_controls:
                        return screen, False, None
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
                        pre_submit_source = safe_page_source(driver)
                        pre_submit_feedback = self._auth_feedback_code(pre_submit_source)
                        submit_element.click()
                        actions_attempted += 1
                        # A staged native login may take several seconds to
                        # render its next form. Observe a bounded series of
                        # credential-safe frames before calling the tap a
                        # failure; none of these frames is persisted.
                        next_screen, duplicate = screen, True
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
                            )
                            if not duplicate:
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
                        if not duplicate and self._credential_controls(next_screen):
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
                        # Retry once with an observed-element gesture only if
                        # the form and its source stayed unchanged after the
                        # bounded wait. A validation message, challenge, or
                        # other visible source change must not be tapped again.
                        username_stage = any(
                            self._credential_hint(control) == "username"
                            for control in credential_controls
                        )
                        gesture_attempted = False
                        current_submit = self._auth_submit_control(next_screen.controls) if duplicate else None
                        if (
                            duplicate and (username_stage or password_stage)
                            and post_native_source == pre_submit_source
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
                                    )
                                    if not duplicate:
                                        break
                            except Exception as gesture_error:
                                warnings.append(
                                    "Observed sign-in gesture was unavailable: "
                                    f"{type(gesture_error).__name__}. No credential values were recorded."
                                )
                        next_has_sensitive_inputs = bool(self._credential_controls(next_screen))
                        if not duplicate and not next_has_sensitive_inputs:
                            next_screen, _ = capture(
                                persist_evidence=True,
                                require_target=True,
                            )
                        transitions.append(
                            DiscoveredTransition(
                                from_screen_id=screen.screen_id,
                                to_screen_id=next_screen.screen_id,
                                control_id=submit.control_id,
                                control_label=submit.semantic_label,
                                duplicate_state=duplicate,
                            )
                        )
                        if duplicate:
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

            current, authentication_blocked, authentication_reason = process_authentication(current)
            if authentication_reason:
                stop_reason = authentication_reason

            # A bounded depth-first traversal explores sibling navigation controls
            # instead of following one path and stopping at the first leaf. Every
            # edge is attempted at most once per observed screen; all backtracking
            # is reversible and destructive controls remain excluded by risk.
            if not authentication_blocked and current is not None and not launch_surface_incomplete:
                stack: list[DiscoveredScreen] = []
                while len(screens) < request.max_screens and actions_attempted < request.max_actions:
                    visited_for_screen = {
                        control_id for screen_id, control_id in visited_edges if screen_id == current.screen_id
                    }
                    control = self._select_safe_control(current.controls, visited_for_screen)
                    if control is None:
                        # A large portion of mobile navigation is hidden below
                        # the first viewport. Give each observed screen a
                        # bounded opportunity to reveal additional controls
                        # before backtracking to its parent. The scroll itself
                        # is recorded in the graph so generated cases replay
                        # the same route.
                        rounds = scroll_rounds.get(current.screen_id, 0)
                        if rounds < 3 and actions_attempted < request.max_actions:
                            scroll_rounds[current.screen_id] = rounds + 1
                            if self._scroll_forward(driver):
                                actions_attempted += 1
                                try:
                                    next_screen, duplicate = capture(require_target=True)
                                except _UnexpectedTargetSurface as exc:
                                    warnings.append(
                                        f"Stopped before counting a screen outside the uploaded app after scrolling: {exc}"
                                    )
                                    stop_reason = "Discovery stopped at the uploaded-app boundary."
                                    break
                                transitions.append(
                                    DiscoveredTransition(
                                        from_screen_id=current.screen_id,
                                        to_screen_id=next_screen.screen_id,
                                        control_id=f"__scroll__{rounds + 1}",
                                        control_label="Scroll down",
                                        action="scroll",
                                        duplicate_state=duplicate,
                                    )
                                )
                                if not duplicate:
                                    stack.append(current)
                                    current = next_screen
                                continue
                        if not stack:
                            stop_reason = "No additional safe navigation controls were available"
                            break
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
                                    to_screen_id=parent.screen_id,
                                    control_id="__back__",
                                    control_label="Back",
                                    action="back",
                                    duplicate_state=recovered_duplicate,
                                )
                            )
                            current = parent if recovered.screen_id == parent.screen_id else recovered
                        except Exception as exc:
                            warnings.append(f"Could not backtrack safely: {type(exc).__name__}: {str(exc)[:180]}")
                            stop_reason = "Stopped because safe backtracking was unavailable"
                            break
                        continue
                    visited_edges.add((current.screen_id, control.control_id))
                    try:
                        element = self._find_discovered_element(driver, control, AppiumBy)
                        element.click()
                        actions_attempted += 1
                        time.sleep(1.2)
                        next_screen, duplicate = capture(require_target=True)
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
                                safe_navigate_back(driver, target_kind=request.target_kind)
                                time.sleep(0.8)
                            except Exception:
                                pass
                            current, _ = capture(persist_evidence=False, require_target=True)
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
                            if authentication_blocked:
                                break
                            # After a successful sign-in, do not backtrack into
                            # the unauthenticated landing/login stack and risk
                            # replaying the same credential form.
                            if current.screen_id != auth_screen_id:
                                stack.clear()
                                visited_edges.clear()
                                scroll_rounds.clear()
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
                            recovered, duplicate = capture(
                                persist_evidence=False,
                                require_target=True,
                            )
                            if not duplicate and recovered.fingerprint != current.fingerprint:
                                # The reactivated app did not return to the
                                # prior observed state. Discard the disconnected
                                # snapshot and stop rather than fabricate a path.
                                screens[:] = [item for item in screens if item.screen_id != recovered.screen_id]
                                seen_fingerprints.pop(recovered.fingerprint, None)
                                stop_reason = "Discovery stopped because the app could not return to the previous observed screen."
                                break
                            current = recovered
                            continue
                        except Exception as recovery_exc:
                            warnings.append(
                                f"Could not restore the uploaded app after leaving its boundary: {type(recovery_exc).__name__}"
                            )
                            stop_reason = "Discovery stopped because the uploaded app could not be safely restored."
                            break
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
                "authentication_blocked": authentication_blocked,
                "target_ready": target_ready,
                "target_identity": target_identity,
                "target_activity": target_activity,
                "target_identity_reason": target_identity_reason,
            }
        finally:
            safe_quit(driver)




