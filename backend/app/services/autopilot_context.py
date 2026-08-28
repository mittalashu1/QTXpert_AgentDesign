"""Profile-driven business context for the autonomous mobile QA agent.

The UI shows a short context so a user can understand what will be tested at a
glance. The selected profile is also sent to the API, which keeps direct API
clients and reruns consistent with the profile selected in the browser.
"""

from __future__ import annotations

from typing import Any

from app.schemas.autopilot import AutopilotProfileOption


DEFAULT_AUTOPILOT_PROFILE_ID = "uae_fintech"

_PROFILE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "uae_fintech",
        "name": "UAE Digital Banking & Wealth",
        "description": "UAE fintech QA, investment journeys and CBUAE/SCA evidence.",
        "brief_context": (
            "Act as a Fintech QA Lead and Compliance Auditor for Investnation by Finance House. "
            "Scope UAE PASS, digital KYC, risk profiling, Saver/Flex/Growth portfolios and the "
            "Investnation Credit Card (up to 90% against invested funds). Apply CBUAE/SCA audit, "
            "security and data-residency checks on {platform}. Use non-production data only; keep "
            "payments, transfers, OTP and destructive actions approval-gated. Produce an evidence-led "
            "executive Test and Audit Report. Do not invent metrics, defects or compliance evidence."
        ),
    },
    {
        "id": "payments_cards",
        "name": "Payments & Cards",
        "description": "Wallets, cards, checkout, transaction integrity and fraud controls.",
        "brief_context": (
            "Act as a Payments QA Lead. Validate the {platform} app's wallet, card, checkout, "
            "authentication, ledger consistency, refunds, limits and fraud/abuse controls. Keep "
            "money movement, OTP and irreversible actions approval-gated; use non-production data. "
            "Capture device, API, audit-log and transaction evidence for an executive release report. "
            "Do not invent metrics, defects or security/compliance evidence."
        ),
    },
    {
        "id": "healthcare_regulated",
        "name": "Healthcare & Regulated Data",
        "description": "Patient journeys, privacy, consent, access control and regulated data handling.",
        "brief_context": (
            "Act as a Healthcare QA and Privacy Auditor for the {platform} app. Validate identity, "
            "consent, patient/provider journeys, sensitive-data handling, access control, audit trails "
            "and retention/deletion safeguards. Use synthetic data only and keep clinical, payment and "
            "destructive actions approval-gated. Produce an evidence-led release report; do not invent "
            "metrics, defects, privacy or regulatory evidence."
        ),
    },
    {
        "id": "ecommerce_marketplace",
        "name": "E-commerce & Marketplace",
        "description": "Catalog, search, cart, checkout, orders, delivery and refunds.",
        "brief_context": (
            "Act as an E-commerce QA Lead for the {platform} app. Validate catalog/search, account, "
            "cart, checkout, payment hand-off, order state, delivery, returns and refunds across "
            "supported devices. Use non-production products and payment data; keep purchases, refunds "
            "and destructive actions approval-gated. Report only observed evidence and mark missing "
            "metrics, defects and compliance controls as pending validation."
        ),
    },
    {
        "id": "general_mobile",
        "name": "General Mobile Application",
        "description": "A neutral profile for apps without a specialised industry scope.",
        "brief_context": (
            "Act as a Senior Mobile QA Lead for the {platform} application. Discover critical user "
            "journeys, permissions, navigation, resilience, accessibility and security guardrails. "
            "Use non-production data; keep authentication, payments and destructive actions approval-gated. "
            "Create an evidence-led executive release report and do not invent metrics, defects or "
            "compliance evidence."
        ),
    },
    {
        "id": "custom",
        "name": "Custom profile",
        "description": "Start with a short neutral brief and tailor it in the context editor.",
        "brief_context": (
            "Act as a Senior QA Lead for the {platform} application. Focus on the product's critical "
            "journeys, risk controls, security, performance and release evidence. Use non-production "
            "data and keep irreversible actions approval-gated. Add product-specific details below; "
            "do not invent metrics, defects or compliance evidence."
        ),
    },
)


def list_profiles() -> list[AutopilotProfileOption]:
    """Return selectable profiles in their stable UI order."""

    return [AutopilotProfileOption.model_validate(item) for item in _PROFILE_DEFINITIONS]


def get_profile(profile_id: str | None) -> AutopilotProfileOption:
    """Resolve an unknown profile safely to the neutral custom profile."""

    requested = (profile_id or DEFAULT_AUTOPILOT_PROFILE_ID).strip().lower()
    for item in list_profiles():
        if item.id == requested:
            return item
    return next(item for item in list_profiles() if item.id == "custom")


def profile_context(
    profile_id: str | None = DEFAULT_AUTOPILOT_PROFILE_ID,
    application_name: str | None = None,
    platform: str = "Android",
) -> str:
    """Render the concise context associated with a selected profile."""

    profile = get_profile(profile_id)
    platform_label = platform.strip() or "Android"
    brief = profile.brief_context.replace("{platform}", platform_label)
    resolved_application = application_name.strip() if application_name else (
        "Investnation by Finance House" if profile.id == DEFAULT_AUTOPILOT_PROFILE_ID else "[TO CONFIRM]"
    )
    if application_name:
        # Keep the profile-specific UAE product name when no override exists,
        # while allowing other profiles to identify the uploaded application.
        if profile.id == DEFAULT_AUTOPILOT_PROFILE_ID:
            brief = brief.replace("Investnation by Finance House", application_name.strip())
    return f"Profile category: {profile.name}\nApplication: {resolved_application}\n{brief}"[:2400]


# Backwards-compatible name used by existing API clients and tests.
DEFAULT_AUTOPILOT_CONTEXT = profile_context(DEFAULT_AUTOPILOT_PROFILE_ID)


def default_context(
    application_name: str | None = None,
    platform: str = "Android",
    profile_id: str | None = DEFAULT_AUTOPILOT_PROFILE_ID,
) -> str:
    """Return a concise, profile-driven context with optional substitutions."""

    return profile_context(profile_id, application_name=application_name, platform=platform)

