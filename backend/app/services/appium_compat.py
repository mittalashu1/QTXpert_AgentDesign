"""Provider-safe Appium metadata helpers.

Some hosted Appium providers do not implement the ``mobile: getCurrentPackage``
extension used by the Python client's ``driver.current_package`` property.  A
metadata lookup must never terminate a discovery or execution session, so these
helpers derive identity from negotiated capabilities and the UI hierarchy only.
"""
from __future__ import annotations

import re
import time
from typing import Any, Mapping, Optional


_PACKAGE_RE = re.compile(r'\bpackage="([^"]+)"')


def safe_page_source(driver: Any) -> str:
    """Return the current hierarchy without allowing evidence lookup to fail a run."""
    try:
        return str(driver.page_source or "")
    except Exception:
        return ""


def safe_capabilities(driver: Any) -> dict[str, Any]:
    """Return a plain capability mapping without invoking mobile commands."""
    try:
        raw = driver.capabilities
    except Exception:
        return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def safe_app_identity(
    driver: Any,
    *,
    page_source: Optional[str] = None,
    package_hint: Optional[str] = None,
    activity_hint: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """Resolve app identity without calling ``current_package/current_activity``."""
    capabilities = safe_capabilities(driver)
    package = _first(
        capabilities,
        "appium:appPackage",
        "appPackage",
        "packageName",
        "appium:bundleId",
        "bundleId",
    )
    activity = _first(
        capabilities,
        "appium:appActivity",
        "appActivity",
        "currentActivity",
    )
    source = "capabilities" if package else None
    hierarchy = page_source if page_source is not None else safe_page_source(driver)
    if not package and hierarchy:
        match = _PACKAGE_RE.search(hierarchy)
        if match:
            package = match.group(1).strip() or None
            source = "page_source"
    if not package and package_hint:
        package = package_hint.strip() or None
        source = "analysis_hint" if package else source
    if not activity and activity_hint:
        activity = activity_hint.strip() or None
    return {"package": package, "activity": activity, "identity_source": source}


def expected_package_state(driver: Any, expected: Optional[str], *, page_source: Optional[str] = None) -> Optional[bool]:
    """Return True/False when identity is observable, otherwise None."""
    if not expected:
        return None
    hierarchy = page_source if page_source is not None else safe_page_source(driver)
    identity = safe_app_identity(driver, page_source=hierarchy)
    actual = identity.get("package")
    if actual:
        return actual == expected
    if hierarchy:
        return expected in hierarchy
    return None


def safe_quit(driver: Any) -> None:
    """Best-effort session cleanup that cannot mask the recorded result."""
    try:
        driver.quit()
    except Exception:
        pass


def safe_background_application(
    driver: Any,
    seconds: float = 2.0,
    *,
    package: Optional[str] = None,
) -> str:
    """Background Android without depending on the optional ``backgroundApp`` extension.

    BrowserStack's current UiAutomator2 endpoint rejects both ``backgroundApp``
    and ``pressKey``. Preserve the native method for local Appium; on that
    provider-specific error, exercise a stronger terminate/relaunch lifecycle
    using the standard application endpoint that BrowserStack supports. The
    caller performs the foreground restore and records the returned mechanism.
    """
    try:
        driver.background_app(seconds)
        return "background_app"
    except Exception as exc:
        message = str(exc).lower()
        if "unknown mobile command" not in message or "backgroundapp" not in message:
            raise

    if not package:
        raise RuntimeError(
            "This provider does not expose backgroundApp and no application package was available for the lifecycle fallback"
        )
    driver.terminate_app(package)
    mechanism = "terminate_app_fallback"
    time.sleep(max(0.0, seconds))
    return mechanism


def _first(values: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

