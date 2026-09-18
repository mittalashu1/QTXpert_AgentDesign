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
_PACKAGE_SINGLE_RE = re.compile(r"\bpackage='([^']+)'")

# Appium hierarchies often include the Android system navigation/status bars
# alongside the application.  They are harmless when the target package is
# also present, but a hierarchy containing only these surfaces is a false
# positive: the provider created a session without launching the uploaded
# build.  Keep the list deliberately narrow so a product package is never
# rejected merely because it starts with a common vendor prefix.
_SYSTEM_PACKAGE_NAMES = {
    "android",
    "com.android.systemui",
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.packageinstaller",
    "io.appium.settings",
    "io.appium.uiautomator2.server",
    "io.appium.uiautomator2.server.test",
}
_SYSTEM_SURFACE_MARKERS = (
    "navigationbarbackground",
    "statusbar",
    "com.android.systemui",
    "permissioncontroller",
    "packageinstaller",
    "android:id/navigationbar",
    "android:id/statusbar",
)


class ProviderLifecycleUnavailable(RuntimeError):
    """The connected device cloud cannot perform a lifecycle-only check safely."""


def _is_system_package(value: Optional[str]) -> bool:
    normalized = str(value or "").strip().casefold()
    return not normalized or normalized in _SYSTEM_PACKAGE_NAMES


def _hierarchy_packages(page_source: str) -> list[str]:
    """Return package attributes visible in a native UI hierarchy."""
    if not page_source:
        return []
    values = [*(_PACKAGE_RE.findall(page_source)), *(_PACKAGE_SINGLE_RE.findall(page_source))]
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        package = str(value or "").strip()
        if package and package not in seen:
            seen.add(package)
            result.append(package)
    return result


def observed_app_identity(driver: Any, *, page_source: Optional[str] = None) -> dict[str, Any]:
    """Resolve identity without falling back to an analysis hint.

    ``safe_app_identity`` intentionally uses ``package_hint`` as a last
    resort so legacy smoke checks can still produce useful evidence.  Target
    validation must distinguish that hint from what the provider actually
    exposed; otherwise an Android system hierarchy can be reported as the
    uploaded app.  This helper returns the hierarchy package list so callers
    can fail fast on a wrong or unlaunched target.
    """
    capabilities = safe_capabilities(driver)
    hierarchy = page_source if page_source is not None else safe_page_source(driver)
    hierarchy_packages = _hierarchy_packages(hierarchy)
    package = next((item for item in hierarchy_packages if not _is_system_package(item)), None)
    activity = _first(
        capabilities,
        "appium:appActivity",
        "appActivity",
        "currentActivity",
    )
    if not package:
        package = _first(
            capabilities,
            "appium:appPackage",
            "appPackage",
            "packageName",
            "appium:bundleId",
            "bundleId",
        )
    source = "hierarchy" if hierarchy_packages and package in hierarchy_packages else "capabilities" if package else None
    return {
        "package": package,
        "activity": activity,
        "identity_source": source,
        "hierarchy_packages": hierarchy_packages,
    }


def validate_target_surface(
    driver: Any,
    *,
    expected_package: Optional[str] = None,
    expected_activity: Optional[str] = None,
    page_source: Optional[str] = None,
    control_labels: Optional[list[str]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify that a live session is attached to the uploaded application.

    A successful Appium handshake is not enough for Autopilot: BrowserStack
    and custom providers can leave the Android system UI foreground when an
    app upload, package or launch capability is wrong.  Return a structured,
    actionable diagnostic instead of allowing that state to generate a
    misleading "completed" discovery or passing smoke case.
    """
    hierarchy = page_source if page_source is not None else safe_page_source(driver)
    identity = observed_app_identity(driver, page_source=hierarchy)
    expected = str(expected_package or "").strip()
    packages = list(identity.get("hierarchy_packages") or [])
    non_system = [item for item in packages if not _is_system_package(item)]
    labels = [str(item or "").strip().casefold() for item in (control_labels or []) if str(item or "").strip()]
    system_only_labels = bool(labels) and all(
        any(marker in label for marker in _SYSTEM_SURFACE_MARKERS)
        for label in labels
    )
    if not labels and any(marker in hierarchy.casefold() for marker in _SYSTEM_SURFACE_MARKERS):
        system_only_labels = True

    if expected:
        if expected in packages:
            return True, "Target package observed in the live hierarchy.", identity
        actual = next((item for item in non_system), identity.get("package"))
        if actual and str(actual).strip() != expected:
            return (
                False,
                f"Runtime session foreground package {actual!r} does not match uploaded package {expected!r}.",
                identity,
            )
        # A few providers omit package attributes from the hierarchy while
        # advertising the requested appPackage in capabilities.  Accept that
        # state only when the hierarchy is not recognisably system-only.
        if identity.get("package") == expected and not system_only_labels:
            return True, "Target package supplied by the provider capabilities.", identity
        if system_only_labels:
            return (
                False,
                "Runtime session reached only Android system UI; the uploaded application was not launched.",
                identity,
            )
        return (
            False,
            f"Runtime provider did not expose uploaded package {expected!r} in the live application surface.",
            identity,
        )

    if non_system:
        return True, "A non-system application package was observed in the live hierarchy.", identity
    if identity.get("package") and not _is_system_package(str(identity.get("package"))):
        return True, "A non-system application package was supplied by the provider.", identity
    if system_only_labels or packages:
        return (
            False,
            "Runtime session reached only Android system UI; configure the uploaded app package/activity or retry the device session.",
            identity,
        )
    return (
        False,
        "Runtime provider did not expose a verifiable application package; configure appPackage/appActivity or a supported device session.",
        identity,
    )


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


