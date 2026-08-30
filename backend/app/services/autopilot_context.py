"""Profile-driven business context for the autonomous QA agent.

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
        "description": "UAE banking and wealth QA, regulated journeys and CBUAE/SCA evidence.",
        "brief_context": (
            "Act as a UAE Digital Banking and Wealth QA Lead and Compliance Auditor for the {platform} "
            "application. Validate applicable onboarding/eKYC, UAE PASS, authentication, risk profiling, "
            "accounts, portfolios, cards, payments and customer journeys. Assess CBUAE/SCA-aligned "
            "controls, auditability, security, resilience, performance and data residency. Use only "
            "non-production data; keep money movement, OTP and destructive actions approval-gated. "
            "Produce an evidence-led executive Test and Audit Report. Unknown features, metrics, defects "
            "and compliance claims remain pending until observed or evidenced."
        ),
    },
    {
        "id": "payments_cards",
        "name": "Payments & Cards",
        "description": "Wallets, cards, checkout, transaction integrity and fraud controls.",
        "brief_context": (
            "Act as a Payments QA Lead for the {platform} application. Validate wallet and card lifecycle, "
            "checkout, authentication, ledger/settlement consistency, refunds, limits, fraud and abuse "
            "controls. Use non-production data and keep money movement, OTP and irreversible actions "
            "approval-gated. Capture device, API, audit-log and transaction evidence for an executive "
            "release report. Unknown metrics, defects and security/compliance claims remain pending."
        ),
    },
    {
        "id": "healthcare_regulated",
        "name": "Healthcare & Regulated Data",
        "description": "Patient journeys, privacy, consent, access control and regulated data handling.",
        "brief_context": (
            "Act as a Healthcare QA and Privacy Auditor for the {platform} application. Validate identity, "
            "consent, patient/provider journeys, sensitive-data handling, access control, audit trails "
            "and retention/deletion safeguards. Use synthetic data only; keep clinical, payment and "
            "destructive actions approval-gated. Produce an evidence-led release report. Unknown metrics, "
            "defects, privacy and regulatory claims remain pending until evidenced."
        ),
    },
    {
        "id": "ecommerce_marketplace",
        "name": "E-commerce & Marketplace",
        "description": "Catalog, search, cart, checkout, orders, delivery and refunds.",
        "brief_context": (
            "Act as an E-commerce QA Lead for the {platform} application. Validate catalog/search, account, "
            "cart, checkout, payment hand-off, order state, delivery, returns and refunds across the "
            "approved device matrix. Use non-production products and payment data; keep purchases, refunds "
            "and destructive actions approval-gated. Report observed evidence only and mark missing metrics, "
            "defects and compliance controls as pending validation."
        ),
    },
    {
        "id": "general_mobile",
        "name": "General Mobile Application",
        "description": "A neutral profile for applications without a specialised industry scope.",
        "brief_context": (
            "Act as a Senior QA Lead for the {platform} application. Discover critical user journeys, "
            "navigation, permissions, resilience, accessibility, integrations and security guardrails. "
            "Use non-production data; keep authentication, payments and destructive actions approval-gated. "
            "Create an evidence-led executive release report. Unknown metrics, defects and compliance "
            "claims remain pending until supported by evidence."
        ),
    },
    {
        "id": "custom",
        "name": "Custom profile",
        "description": "Start with a short neutral brief and tailor it in the context editor.",
        "brief_context": (
            "Act as a Senior QA Lead for the {platform} application. Focus on the product's critical "
            "journeys, risk controls, integrations, security, performance and release evidence. Use "
            "non-production data and keep authentication, money movement and irreversible actions "
            "approval-gated. Add product-specific details below; unknown metrics, defects and compliance "
            "claims remain pending until supported by evidence."
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
    # A profile describes a testing scope, not a particular product. Keep the
    # application unknown until an artifact/URL supplies an observed identity
    # or the user explicitly adds one to the context.
    resolved_application = application_name.strip() if application_name else "[TO CONFIRM]"
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

