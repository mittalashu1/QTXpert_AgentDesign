"""Human-facing labels and bounded data-probe guidance for Autopilot.

Runtime identifiers are intentionally opaque and stable, but they are not
useful test-case names.  This module turns observed screen/activity/control
metadata into concise journey labels without treating a URL or a guessed
business capability as evidence.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.schemas.autopilot import DiscoveredControl, DiscoveredScreen


# Ordered from the most specific user journeys to broad navigation surfaces.
# A label is returned only when one of these terms is actually observed in a
# screen title, activity name or control label.
_JOURNEY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Authentication", ("sign in", "sign-in", "log in", "login", "password", "user id", "username", "otp", "mfa")),
    ("Send money", ("send money", "send funds", "beneficiary", "recipient", "transfer")),
    ("Investments", ("investment", "investments", "portfolio", "fund", "stocks", "shares", "trade")),
    ("Deposits", ("deposit", "deposits", "add money", "top up", "top-up", "cash in")),
    ("Accounts", ("account", "accounts", "balance", "statement")),
    ("Cards", ("card", "cards", "credit card", "debit card")),
    ("Profile", ("profile", "personal details", "my details", "preferences")),
    ("Registration", ("register", "registration", "sign up", "create account", "onboarding")),
    ("Search and browse", ("search", "filter", "sort", "catalog", "browse", "explore")),
    ("Notifications", ("notification", "notifications", "inbox", "alerts")),
    ("Settings", ("settings", "security", "privacy", "language")),
    ("Support", ("help", "support", "faq", "contact", "customer service")),
    ("Documents", ("document", "documents", "upload", "file")),
    ("Rewards", ("reward", "rewards", "offers", "benefits")),
    ("Home", ("home", "dashboard", "overview", "welcome")),
)

_GENERIC_SCREEN_TOKENS = {
    "screen", "page", "view", "activity", "mainactivity", "launchscreen", "splash",
    "root", "container", "unknown", "untitled", "android", "ios",
}


def _clean(value: str | None, *, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def _normalized(value: str | None) -> str:
    # Keep word boundaries meaningful while making generated IDs comparable.
    return re.sub(r"[_\-./:#]+", " ", _clean(value, limit=240)).casefold()


def _meaningful(value: str | None) -> bool:
    candidate = _clean(value)
    if not candidate or candidate.startswith(("http://", "https://")):
        return False
    compact = re.sub(r"[^a-z0-9]+", "", candidate.casefold())
    return bool(re.search(r"[a-zA-Z]", candidate)) and compact not in _GENERIC_SCREEN_TOKENS


def observed_journey_label(screen: DiscoveredScreen, index: int = 1) -> str:
    """Return a concise journey name supported by observed UI metadata."""

    evidence: list[str] = [screen.title or "", screen.activity_name or ""]
    evidence.extend(control.semantic_label for control in screen.controls[:24])
    combined = _normalized(" ".join(evidence))
    for label, terms in _JOURNEY_RULES:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", combined) for term in terms):
            return label

    title = _clean(screen.title)
    if _meaningful(title):
        # Strip common product suffixes while retaining the page's own name.
        title = re.sub(r"\s*[|·—-]\s*(?:qtxpert|investnation|app|website)\s*$", "", title, flags=re.I)
        if _meaningful(title):
            return title[:80]

    activity = _clean(screen.activity_name)
    if _meaningful(activity):
        short = activity.rsplit(".", 1)[-1]
        short = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", short).replace("_", " ").replace("-", " ")
        short = _clean(short).title()
        if _meaningful(short):
            return short[:80]

    # A first meaningful control is a better explanation than an opaque URL or
    # screen hash. It remains an observation, not a product capability claim.
    for control in screen.controls[:24]:
        label = _clean(control.semantic_label)
        if _meaningful(label):
            return label[:80]
    return f"Observed journey {max(1, index)}"


def observed_page_label(screen: DiscoveredScreen, index: int = 1) -> str:
    """Return the best observed page/screen label without exposing an URL."""

    title = _clean(screen.title)
    if _meaningful(title):
        title = re.sub(r"\s*[|·—-]\s*(?:qtxpert|investnation|app|website)\s*$", "", title, flags=re.I)
        if _meaningful(title):
            # A product-level document title (for example, ``InvestNation``)
            # is not a useful page name when the observed controls expose a
            # concrete journey. Keep known page terms such as Login or
            # Dashboard, but prefer the evidence-derived journey for an
            # otherwise opaque one-word product title.
            normalized_title = _normalized(title)
            title_is_journey = any(
                re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized_title)
                for _, terms in _JOURNEY_RULES
                for term in terms
            )
            journey = observed_journey_label(screen, index)
            if title_is_journey or journey == title or len(screen.controls) == 0:
                return title[:100]
            if journey and not journey.startswith("Observed journey "):
                return journey[:100]
            return title[:100]
    journey = observed_journey_label(screen, index)
    return journey


def input_probe_guidance(label: str, field_type: str | None = None) -> list[dict[str, str]]:
    """Describe deterministic positive/negative/boundary probes for a field.

    These are strategy descriptions, never secret values.  The runner keeps
    using its own bounded synthetic values; the UI can show this guidance so a
    user understands exactly what a deferred field means.
    """

    lower = _normalized(label)
    if any(term in lower for term in ("name", "first", "last", "surname")):
        positive = "Alphabetic name, for example Alex Morgan"
        negative = "Numbers, symbols-only or an overlong name"
        boundary = "Minimum and maximum accepted name length"
    elif any(term in lower for term in ("email", "e mail")):
        positive = "A syntactically valid non-production email"
        negative = "Missing @, malformed domain or blank value"
        boundary = "Shortest accepted local part and maximum length"
    elif any(term in lower for term in ("phone", "mobile", "telephone")):
        positive = "A non-production phone number in the expected country format"
        negative = "Letters, invalid prefix or too few digits"
        boundary = "Minimum and maximum digit count"
    elif any(term in lower for term in ("amount", "number", "quantity", "count", "price")):
        positive = "A safe in-range numeric value"
        negative = "Letters, negative value or invalid decimal format"
        boundary = "Zero, minimum, maximum and precision limits"
    elif any(term in lower for term in ("date", "dob", "birth")):
        positive = "A valid non-production date in the expected format"
        negative = "Invalid date, impossible date or wrong format"
        boundary = "Earliest/latest permitted date"
    elif any(term in lower for term in ("address", "street", "city", "country", "postal", "zip")):
        positive = "A realistic synthetic address value"
        negative = "Unsupported characters, blank or malformed postal value"
        boundary = "Required fields and maximum address length"
    elif field_type == "text":
        positive = "A short, ordinary non-production text value"
        negative = "Blank, unsupported characters or an invalid format"
        boundary = "Minimum and maximum accepted length"
    else:
        positive = "A valid value matching the observed field format"
        negative = "Wrong type, malformed format or blank value"
        boundary = "Observed minimum/maximum or required-field boundary"
    return [
        {"kind": "positive", "label": "Positive", "guidance": positive},
        {"kind": "negative", "label": "Negative", "guidance": negative},
        {"kind": "boundary", "label": "Boundary", "guidance": boundary},
    ]


def journey_for_title(title: str) -> str | None:
    """Extract the journey prefix used by generated runtime titles."""

    prefix = _clean((title or "").split(" — ", 1)[0], limit=100)
    return prefix or None
