"""Run a real, read-only Android/Appium setup check and retain its evidence."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from appium import webdriver
from appium.options.android import UiAutomator2Options

from agent import ANDROID_SERIAL_ENV, DEFAULT_APPIUM_URL, inspect_local_stack, _validate_startup_ui


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device-serial", help="ADB serial of the phone or emulator to check")
    args = parser.parse_args()
    if args.device_serial:
        os.environ[ANDROID_SERIAL_ENV] = args.device_serial
    args.output.mkdir(parents=True, exist_ok=True)
    stack = inspect_local_stack()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "stack": stack}
    if not stack["ready"] or len(stack["devices"]) != 1:
        report["status"] = "failed"
        if stack["ready"]:
            report["error"] = "Multiple Android devices are ready. Select one with --device-serial."
        (args.output / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2
    serial = stack["devices"][0]
    settings_package = "com.android.settings"
    settings_action = "android.settings.SETTINGS"
    driver = None
    try:
        options = UiAutomator2Options().load_capabilities({
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:udid": serial,
            "appium:deviceName": serial,
            "appium:noReset": True,
            "appium:autoLaunch": False,
            "appium:skipUnlock": True,
            "appium:newCommandTimeout": 60,
            "appium:androidInstallTimeout": 300_000,
            "appium:uiautomator2ServerInstallTimeout": 300_000,
            "appium:uiautomator2ServerLaunchTimeout": 120_000,
            "appium:adbExecTimeout": 120_000,
        })
        driver = webdriver.Remote(DEFAULT_APPIUM_URL, options=options)
        # Let Android resolve its Settings intent. Vendors can route an explicit
        # launcher activity or category to a different screen.
        subprocess.run(
            [stack["adb_path"], "-s", serial, "shell", "am", "start", "-W", "-a", settings_action],
            check=True, capture_output=True, text=True, timeout=20,
        )
        source = driver.page_source
        screenshot = driver.get_screenshot_as_png()
        _validate_startup_ui(source)
        current_package = driver.current_package
        assert current_package == settings_package, "Android Settings is not in the foreground. Check that the device is unlocked."
        assert f'package="{settings_package}"' in source, "The readable UI does not belong to Android Settings"
        assert screenshot.startswith(b"\x89PNG"), "Screenshot was not a PNG"
        (args.output / "settings.xml").write_text(source, encoding="utf-8")
        (args.output / "settings.png").write_bytes(screenshot)
        report.update(status="passed", session_id=driver.session_id,
                      current_package=current_package, source_chars=len(source),
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
