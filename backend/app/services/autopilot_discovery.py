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
    def _looks_like_loading_screen(screen: DiscoveredScreen) -> bool:
        """Identify splash/blank states that deserve a bounded settle retry."""
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
        }
        interactive = [
            control for control in screen.controls
            if control.enabled
            and control.locators
            and (
                control.input_capable
                or (
                    control.clickable
                    and re.sub(r"[\s_-]+", " ", str(control.semantic_label or "").lower()).strip() not in generic_labels
                )
            )
        ]
        # Some providers expose an Android splash as a clickable generic View.
        # It is not a ready product page without a deterministic locator and
        # a meaningful user-facing label; keep waiting rather than reporting
        # a false one-screen discovery.
        return len(interactive) == 0 and len(screen.controls) <= 4

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
        submit = cls._auth_submit_control(controls)
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
        candidates.sort(key=lambda item: (-max(locator.confidence for locator in item.locators), item.semantic_label.lower()))
        return candidates[0] if candidates else None

    @staticmethod
    def _find_discovered_element(driver: Any, control: DiscoveredControl, appium_by: Any) -> Any:
        """Resolve one control using only locators observed on that control."""
        locator_map = {
            "accessibility_id": appium_by.ACCESSIBILITY_ID,
            "id": appium_by.ID,
            "xpath": appium_by.XPATH,
        }
        candidates = sorted(control.locators, key=lambda locator: -locator.confidence)
        last_error: Optional[Exception] = None
        for locator in candidates[:3]:
            strategy = locator_map.get(locator.strategy)
            if strategy is None:
                continue
            try:
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
                    input_values or {},
                ),
                timeout=self.settings.AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS,
            )
            checkpoint_stop = str(payload.get("stop_reason") or "").lower().startswith(
                ("authentication", "sign-in", "credentials")
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
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:newCommandTimeout": 180,
        }
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
            duplicate = fp in seen_fingerprints
            screen_id = seen_fingerprints.get(fp) or f"screen-{index:03d}"
            if duplicate:
                existing = next(screen for screen in screens if screen.screen_id == screen_id)
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
                    f"Initial app screen remained non-interactive after {retries} bounded settle attempt(s); "
                    "the launch state was retained as evidence and no controls were auto-clicked."
                )
                stop_reason = (
                    "App remained on a non-interactive launch screen after bounded settling; "
                    "login and workflows were not inferred."
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
                # Some cloud sessions honour ``app`` but leave the launcher or
                # system UI foreground until the package is explicitly
                # activated. Retry that deterministic operation once before
                # declaring the provider unusable.
                try:
                    # Discard the unverified launch surface before retrying;
                    # it is not part of the app's screen graph.
                    screens.clear()
                    seen_fingerprints.clear()
                    driver.activate_app(package_hint)
                    time.sleep(2)
                    candidate, _ = capture(persist_evidence=False)
                    retry_ready, retry_reason, retry_identity = validate_target_surface(
                        driver,
                        expected_package=package_hint,
                        expected_activity=activity_hint,
                        page_source=safe_page_source(driver),
                        control_labels=[control.semantic_label for control in candidate.controls],
                    )
                    if retry_ready:
                        current = candidate
                        target_ready = True
                        target_identity_reason = retry_reason
                        target_identity = retry_identity.get("package")
                        target_activity = retry_identity.get("activity")
                    else:
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
                        for control in credential_controls:
                            value = self._credential_value(screen.screen_id, control, input_values)
                            if value is None:
                                continue
                            element = self._find_discovered_element(driver, control, AppiumBy)
                            try:
                                element.clear()
                            except Exception:
                                pass
                            element.send_keys(value)
                        submit = self._auth_submit_control(screen.controls)
                        if submit is None:
                            return screen, True, "Credentials were supplied, but no safe sign-in control was found"
                        if actions_attempted >= request.max_actions:
                            return (
                                screen,
                                True,
                                f"Authentication values are ready, but max_actions={request.max_actions} was reached",
                            )
                        self._find_discovered_element(driver, submit, AppiumBy).click()
                        actions_attempted += 1
                        time.sleep(1.5)
                        # Never persist the post-fill frame until it has been
                        # checked for remaining sensitive fields.
                        next_screen, duplicate = capture(
                            persist_evidence=False,
                            require_target=True,
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
                            return (
                                screen,
                                True,
                                "Sign-in returned to the same screen; credentials may be invalid or the flow needs supervision.",
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
                            f"Could not safely submit the approved sign-in form: {type(exc).__name__}: {str(exc)[:180]}"
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
                "target_ready": target_ready,
                "target_identity": target_identity,
                "target_activity": target_activity,
                "target_identity_reason": target_identity_reason,
            }
        finally:
            safe_quit(driver)

