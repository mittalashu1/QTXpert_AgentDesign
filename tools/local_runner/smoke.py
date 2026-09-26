"""Run a real, read-only Android/Appium setup check and retain its evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from appium import webdriver
from appium.options.android import UiAutomator2Options

from agent import DEFAULT_APPIUM_URL, inspect_local_stack, _validate_startup_ui


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stack = inspect_local_stack()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "stack": stack}
    if not stack["ready"]:
        report["status"] = "failed"
        (args.output / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2
    options = UiAutomator2Options().load_capabilities({
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": stack["devices"][0],
        "appium:deviceName": stack["devices"][0],
        "appium:appPackage": "com.android.settings",
        "appium:appActivity": ".Settings",
        "appium:noReset": True,
        "appium:newCommandTimeout": 60,
    })
    driver = None
    try:
        driver = webdriver.Remote(DEFAULT_APPIUM_URL, options=options)
        source = driver.page_source
        screenshot = driver.get_screenshot_as_png()
        (args.output / "settings.xml").write_text(source, encoding="utf-8")
        (args.output / "settings.png").write_bytes(screenshot)
        _validate_startup_ui(source)
        assert driver.current_package == "com.android.settings", "Android Settings did not launch"
        assert 'package="com.android.settings"' in source, "The readable UI does not belong to Android Settings"
        assert "Settings" in source, "Settings UI was not readable"
        assert screenshot.startswith(b"\x89PNG"), "Screenshot was not a PNG"
        report.update(status="passed", session_id=driver.session_id,
                      current_package=driver.current_package, source_chars=len(source),
                      screenshot_bytes=len(screenshot))
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        if driver:
            driver.quit()
            report["session_closed"] = True
        (args.output / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
