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


class ProviderLifecycleUnavailable(RuntimeError):
    """The connected device cloud cannot perform a lifecycle-only check safely."""


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
    """Background Android using the strongest lifecycle control the provider exposes.

    Local Appium supports ``background_app`` directly. BrowserStack's current
    UiAutomator2 endpoint can reject ``backgroundApp``, ``pressKey`` and
    ``terminateApp`` while advertising ``mobile: shell``. In that case an Android
    HOME key event backgrounds the app without mutating its state; the caller then
    restores the package. If the provider also denies shell, return an actionable
    capability block instead of leaking an UnknownMethodException as a test failure.
    """
    try:
        driver.background_app(seconds)
        return "background_app"
    except Exception as exc:
        message = str(exc).lower()
        if "unknown mobile command" not in message or "backgroundapp" not in message:
            raise

    try:
        driver.execute_script(
            "mobile: shell",
            {
                "command": "input",
                "args": ["keyevent", "3"],
                "includeStderr": True,
                "timeout": 5000,
            },
        )
        time.sleep(max(0.0, seconds))
        return "mobile_shell_home"
    except Exception as exc:
        raise ProviderLifecycleUnavailable(
            "Background/foreground lifecycle control is unavailable on this device provider. "
            "Run this resilience check with custom/local Appium or enable the provider's mobile shell capability."
        ) from exc


def _first(values: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

