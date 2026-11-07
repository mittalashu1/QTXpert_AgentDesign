from __future__ import annotations


def upload_error_message(status_code: int, response_text: str) -> str:
    """Turn BrowserStack upload failures into useful, credential-safe guidance."""
    lowered = response_text.lower()
    if "browserstack_testing_time_limit_exhausted" in lowered:
        return (
            "BrowserStack App Automate rejected the app upload because the account used by the "
            "Render credentials has no testing time available. QTXpert's request timeout was not "
            "reached, and BrowserStack did not start a device session. Verify that the "
            "BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY saved in Render belong to the "
            "same App Automate account that shows the remaining minutes. If they do, BrowserStack "
            "needs to reconcile that account's trial entitlement."
        )
    if status_code == 401:
        return (
            "BrowserStack rejected the configured credentials (401). Check that the "
            "BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY saved in Render are a matching "
            "pair from an active App Automate account."
        )
    if status_code == 403:
        return (
            "BrowserStack rejected the app upload (403) because this account is not currently "
            "authorized to use App Automate. Check the account's App Automate plan and access."
        )

    detail = response_text[:500]
    return f"BrowserStack app upload failed ({status_code}): {detail}"

