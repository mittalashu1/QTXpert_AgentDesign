from app.schemas.autopilot import DiscoveredControl, DiscoveredScreen
from app.services.autopilot_labels import (
    input_probe_guidance,
    observed_journey_label,
    observed_page_label,
)


def _screen(*, title: str | None = None, activity: str | None = None, controls=None) -> DiscoveredScreen:
    return DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="fingerprint",
        title=title,
        activity_name=activity,
        url="https://example.test/accounts/profile",
        controls=list(controls or []),
    )


def test_observed_labels_prefer_real_journey_terms_over_url_or_screen_id():
    screen = _screen(
        title="InvestNation",
        activity="MainActivity",
        controls=[DiscoveredControl(control_id="profile", semantic_label="Profile", clickable=True)],
    )

    assert observed_journey_label(screen) == "Profile"
    assert observed_page_label(screen) == "Profile"
    assert "screen-001" not in observed_page_label(screen)
    assert "accounts/profile" not in observed_page_label(screen)


def test_probe_guidance_explains_positive_negative_and_boundary_name_checks():
    probes = input_probe_guidance("Full name", "test_data")

    assert [item["kind"] for item in probes] == ["positive", "negative", "boundary"]
    assert "Alphabetic" in probes[0]["guidance"]
    assert "Numbers" in probes[1]["guidance"]
    assert "length" in probes[2]["guidance"]


def test_credential_probe_guidance_never_treats_user_id_as_a_personal_name():
    probes = input_probe_guidance("Username · User ID / email", "credential")

    assert "approved non-production" in probes[0]["guidance"].lower()
    assert "guessed invalid credentials" in probes[1]["guidance"].lower()
    assert "lockout" in probes[2]["guidance"].lower()
    assert all("alphabetic" not in item["guidance"].lower() for item in probes)


def test_unknown_screen_gets_an_honest_observed_fallback():
    screen = _screen(activity="MainActivity")

    assert observed_journey_label(screen, 3) == "Observed journey 3"
    assert observed_page_label(screen, 3) == "Observed journey 3"


def test_short_fragment_is_not_promoted_to_a_journey_name():
    screen = _screen(
        title="InvestNation",
        activity="MainActivity",
        controls=[DiscoveredControl(control_id="fragment", semantic_label="EM")],
    )

    assert observed_journey_label(screen) == "InvestNation"
    assert observed_page_label(screen) == "InvestNation"

