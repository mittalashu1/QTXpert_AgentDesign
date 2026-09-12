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
from app.services.appium_compat import safe_app_identity, safe_page_source, safe_quit


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
    "transactions", "activity", "rewards", "offers", "benefits", "support",
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
                    )
                )
                if len(requests) >= 40:
                    return requests
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
        interactive = [
            control for control in screen.controls
            if control.enabled and (control.clickable or control.input_capable)
        ]
        # A small non-interactive hierarchy is characteristic of an Android
        # splash/launch view. This is deliberately conservative and is only
        # retried a few times before the state is retained as evidence.
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
        known_credential = [control for control in inputs if control.input_kind == "credential"]
        if known_credential and len(known_credential) == len(inputs):
            return controls
        input_positions = {control.control_id: index for index, control in enumerate(inputs)}
        updated: list[DiscoveredControl] = []
        for control in controls:
            if control.control_id not in input_positions:
                updated.append(control)
                continue
            if control.input_kind == "credential":
                updated.append(control)
                continue
            position = input_positions[control.control_id]
            label = control.semantic_label or ""
            # Preserve a meaningful product label; replace only generic class
            # names such as EditText/TextField so the checkpoint is readable.
            if cls._is_generic_input_label(label, control.class_name):
                label = "User ID / email" if position == 0 else "Password" if position == 1 else label
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
            input_capable = class_name in _INPUT_CLASSES or class_name in {
                "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
            }
            actionable = clickable or input_capable or class_name in _ACTIONABLE_CLASSES
            raw_label = cls._semantic_label(attrs)
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
            kind_attrs = {**attrs}
            if nearby_label:
                kind_attrs["hint"] = " ".join(filter(None, [attrs.get("hint", ""), nearby_label]))
            input_kind = cls._input_kind(kind_attrs, " ".join(filter(None, [label, nearby_label or ""]))) if input_capable else None
            # Do not create a text XPath from a value in an input widget.
            locator_attrs = {**attrs, "text": ""} if input_capable else attrs
            locators = cls._locators(locator_attrs)
            if input_capable and not locators and re.fullmatch(r"[A-Za-z0-9_.]+", class_name):
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
    def _select_safe_control(controls: list[DiscoveredControl], visited: set[str]) -> Optional[DiscoveredControl]:
        candidates = [
            control for control in controls
            if control.enabled and control.clickable and not control.input_capable and control.risk == "safe"
            and control.locators and control.control_id not in visited
            and max(locator.confidence for locator in control.locators) >= 0.90
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-max(locator.confidence for locator in item.locators), item.semantic_label.lower()))
        return candidates[0]

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
            status = "partial" if checkpoint_stop else "completed" if payload["screens"] else "partial"
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
            input_requests=self.runtime_input_requests(screens),
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
        warnings: list[str] = []
        actions_attempted = 0
        stop_reason = "Discovery bounds reached"

        def capture(*, persist_evidence: bool = True) -> tuple[DiscoveredScreen, bool]:
            index = len(screens) + 1
            page_source = safe_page_source(driver)
            controls = self._ensure_auth_input_semantics(self.parse_controls(page_source))
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
            current, _ = capture()
            retries = 0
            while self._looks_like_loading_screen(current) and retries < retry_limit:
                retries += 1
                time.sleep(retry_wait)
                candidate, duplicate = capture()
                current_score = sum(1 for item in current.controls if item.enabled and (item.clickable or item.input_capable))
                candidate_score = sum(1 for item in candidate.controls if item.enabled and (item.clickable or item.input_capable))
                if not duplicate or candidate_score >= current_score:
                    current = candidate
            if self._looks_like_loading_screen(current):
                warnings.append(
                    f"Initial app screen remained non-interactive after {retries} bounded settle attempt(s); "
                    "the launch state was retained as evidence and no controls were auto-clicked."
                )
            elif current is not screens[0]:
                # The replay root must be the settled app, not its splash.
                screens.remove(current)
                screens.insert(0, current)
            if request.observe_only:
                stop_reason = "Observe-only discovery captured the current screen"
                return {
                    "screens": screens,
                    "transitions": transitions,
                    "actions_attempted": actions_attempted,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                }

            # Authentication is the first user checkpoint.  Never walk past a
            # login hierarchy or fabricate a credential; when the caller has
            # already supplied approved, decrypted values we fill them only in
            # the live session and suppress the immediate evidence snapshot.
            input_values = input_values or {}
            credential_controls = [
                control
                for control in current.controls
                if control.input_capable and control.input_kind == "credential"
            ]
            authentication_blocked = False
            auth_rounds = 0
            while current is not None:
                credential_controls = [
                    control
                    for control in current.controls
                    if control.input_capable and control.input_kind == "credential"
                ]
                if not credential_controls:
                    break
                auth_rounds += 1
                if auth_rounds > 3:
                    authentication_blocked = True
                    stop_reason = "Authentication has more than three sequential checkpoints; continue under supervision."
                    break
                auth_approved = str(input_values.get("__auth_approved") or "") == "1"
                missing_controls = [
                    control
                    for control in credential_controls
                    if self._credential_hint(control) != "otp"
                    and self._credential_value(current.screen_id, control, input_values) is None
                ]
                otp_controls = [control for control in credential_controls if self._credential_hint(control) == "otp"]
                if not auth_approved or missing_controls or otp_controls:
                    authentication_blocked = True
                    stop_reason = (
                        "Authentication checkpoint detected. Enter the non-production User ID and Password "
                        "(and provide an approved OTP only when the flow permits it) before Autopilot continues."
                    )
                    break
                if actions_attempted >= request.max_actions:
                    authentication_blocked = True
                    stop_reason = f"Authentication values are ready, but max_actions={request.max_actions} was reached"
                    break
                try:
                    for control in credential_controls:
                        value = self._credential_value(current.screen_id, control, input_values)
                        if value is None:
                            continue
                        locator = control.locators[0]
                        by = {
                            "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
                            "id": AppiumBy.ID,
                            "xpath": AppiumBy.XPATH,
                        }[locator.strategy]
                        element = driver.find_element(by, locator.value)
                        try:
                            element.clear()
                        except Exception:
                            pass
                        element.send_keys(value)
                    submit = self._auth_submit_control(current.controls)
                    if submit is None:
                        authentication_blocked = True
                        stop_reason = "Credentials were supplied, but no safe sign-in control was found"
                        break
                    if actions_attempted >= request.max_actions:
                        authentication_blocked = True
                        stop_reason = f"Authentication values are ready, but max_actions={request.max_actions} was reached"
                        break
                    locator = submit.locators[0]
                    by = {
                        "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
                        "id": AppiumBy.ID,
                        "xpath": AppiumBy.XPATH,
                    }[locator.strategy]
                    driver.find_element(by, locator.value).click()
                    actions_attempted += 1
                    time.sleep(1.5)
                    # Do not persist a screenshot/XML immediately after typing
                    # credentials. The next stable screen is captured normally
                    # once authentication succeeds.
                    next_screen, duplicate = capture(persist_evidence=False)
                    transitions.append(
                        DiscoveredTransition(
                            from_screen_id=current.screen_id,
                            to_screen_id=next_screen.screen_id,
                            control_id=submit.control_id,
                            control_label=submit.semantic_label,
                            duplicate_state=duplicate,
                        )
                    )
                    next_credentials = [
                        control
                        for control in next_screen.controls
                        if control.input_capable and control.input_kind == "credential"
                    ]
                    if duplicate:
                        authentication_blocked = True
                        stop_reason = (
                            "Sign-in returned to the same screen; credentials may be invalid or the flow needs supervision."
                        )
                        break
                    if next_credentials:
                        # Multi-step sign-in (for example user ID → password)
                        # is still part of the login checkpoint. Loop once more
                        # with the same approved in-memory values; OTP remains
                        # a hard supervised stop in the next iteration.
                        current = next_screen
                        continue
                    current = next_screen
                    break
                except Exception as exc:
                    authentication_blocked = True
                    warnings.append(
                        f"Could not safely submit the approved sign-in form: {type(exc).__name__}: {str(exc)[:180]}"
                    )
                    stop_reason = "Authentication could not be completed safely; review the sign-in checkpoint"
                    break

            # A bounded depth-first traversal explores sibling navigation controls
            # instead of following one path and stopping at the first leaf. Every
            # edge is attempted at most once per observed screen; all backtracking
            # is reversible and destructive controls remain excluded by risk.
            if not authentication_blocked and current is not None:
                stack: list[DiscoveredScreen] = []
                while len(screens) < request.max_screens and actions_attempted < request.max_actions:
                    visited_for_screen = {
                        control_id for screen_id, control_id in visited_edges if screen_id == current.screen_id
                    }
                    control = self._select_safe_control(current.controls, visited_for_screen)
                    if control is None:
                        if not stack:
                            stop_reason = "No additional safe navigation controls were available"
                            break
                        parent = stack.pop()
                        try:
                            driver.back()
                            time.sleep(0.8)
                            recovered, recovered_duplicate = capture(persist_evidence=False)
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
                            current, _ = capture(persist_evidence=False)
                            continue
                        stack.append(current)
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
