"""Execute the Autopilot crawler's bounded native UI protocol on loopback."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+")
BASE_APK_PATH = re.compile(r"package:(/data/app/(?:[A-Za-z0-9_~+=@-][A-Za-z0-9_~+=@.-]*/)+base\.apk)")
NATIVE_COMMANDS = {
    "getPageSource": ("GET", "/source"),
    "screenshot": ("GET", "/screenshot"),
    "getWindowRect": ("GET", "/window/rect"),
    "findElement": ("POST", "/element"),
    "findElements": ("POST", "/elements"),
    "clickElement": ("POST", "/element/{id}/click"),
    "clear": ("POST", "/element/{id}/clear"),
    "clearElement": ("POST", "/element/{id}/clear"),
    "sendKeysToElement": ("POST", "/element/{id}/value"),
    "getElementText": ("GET", "/element/{id}/text"),
    "getElementRect": ("GET", "/element/{id}/rect"),
    "getElementAttribute": ("GET", "/element/{id}/attribute/{name}"),
    "isElementDisplayed": ("GET", "/element/{id}/displayed"),
    "isElementEnabled": ("GET", "/element/{id}/enabled"),
    "goBack": ("POST", "/back"),
    "actions": ("POST", "/actions"),
    "clearActionState": ("DELETE", "/actions"),
    "w3cExecuteScript": ("POST", "/execute/sync"),
    "quit": ("DELETE", ""),
}
MOBILE_UI_CALLS = {
    "getCurrentPackage", "getCurrentActivity", "getAppiumSessionCapabilities",
    "hideKeyboard", "isKeyboardShown", "scrollGesture", "swipeGesture",
    "swipe", "clickGesture", "type", "replaceElementValue", "backgroundApp",
}
PACKAGE_CALLS = {"activateApp", "terminateApp", "queryAppState", "isAppInstalled", "clearApp", "changePermissions"}


def _mobile_command(body: dict, package: str) -> None:
    script = body.get("script")
    args = body.get("args") or []
    if not isinstance(script, str) or not script.startswith("mobile: "):
        raise ValueError("Only native Android UI actions are supported.")
    name = script.removeprefix("mobile: ")
    if not isinstance(args, list) or len(args) > 1 or (args and not isinstance(args[0], dict)):
        raise ValueError("Invalid native Android UI arguments.")
    arguments = args[0] if args else {}
    if name in MOBILE_UI_CALLS:
        return
    if name == "pressKey" and arguments.get("keycode") in {3, 4, 66, 61, 62, 67, 111}:
        return
    if name in PACKAGE_CALLS:
        identifiers = [arguments.get(key) for key in ("appId", "appPackage", "bundleId") if key in arguments]
        if identifiers and all(identifier == package for identifier in identifiers):
            if name != "changePermissions" or (
                arguments.get("action") == "revoke" and arguments.get("target") == "pm"
                and arguments.get("permissions") == "all"
            ):
                return
    raise ValueError("This native action falls outside the selected Android application.")


class AndroidSession:
    def __init__(self, appium: httpx.Client, manifest: dict, apk: Path, adb: str):
        self.appium = appium
        self.device = manifest["device_name"]
        self.package = manifest["package_name"]
        self.digest = manifest["app_sha256"]
        self.apk = apk
        self.adb = adb
        self.session_id: str | None = None
        if not PACKAGE.fullmatch(self.package) or not ID.fullmatch(self.device):
            raise ValueError("The APK package or selected device is invalid.")

    def _has_selected_apk(self) -> bool:
        """Only skip installation when the standalone installed APK matches the repository bytes."""
        shell = [self.adb, "-s", self.device, "shell"]
        opts = {"capture_output": True, "text": True, "check": True, "timeout": 8}
        try:
            paths = subprocess.run([*shell, "pm", "path", self.package], **opts).stdout.strip()
            base = BASE_APK_PATH.fullmatch(paths)
            if not base:
                return False
            digest = subprocess.run([*shell, "sha256sum", base[1]], **opts).stdout.split(maxsplit=1)
            return bool(digest and digest[0].lower() == self.digest.lower())
        except (OSError, subprocess.SubprocessError):
            return False

    def _call(self, method: str, path: str, body: dict | None = None, *, timeout: int = 60) -> dict:
        response = self.appium.request(method, path.lstrip("/"), json=body, timeout=timeout)
        data = response.json()
        if not response.is_success:
            error = data.get("value") or {}
            if not isinstance(error, dict):
                error = {}
            message = str(error.get("message") or "").casefold()
            if error.get("error") == "invalid session id" or any(fragment in message for fragment in (
                "device offline", "no devices/emulators found", "device not found", "socket hang up",
                "instrumentation process is not running",
            )):
                return {"interrupted": "The Android device or its Appium session disconnected."}
            # Provider diagnostics can contain typed text or local paths.
            return {"status": error.get("error") or "unknown error", "value": {
                "message": f"Appium returned {error.get('error') or 'an error'} for a native UI command."
            }}
        return data

    def _start(self, params: dict) -> dict:
        if self.session_id:
            raise ValueError("Finish the current Appium session before opening another.")
        requested = params.get("capabilities", {}).get("alwaysMatch", {})
        no_reset = requested.get("appium:noReset") is True
        full_reset = requested.get("appium:fullReset") is True
        grant_permissions = requested.get("appium:autoGrantPermissions") is True
        reuse_installed = no_reset and not full_reset and not grant_permissions and self._has_selected_apk()
        options = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:deviceName": self.device,
            "appium:udid": self.device,
            "appium:appPackage": self.package,
            "appium:noReset": no_reset,
            "appium:fullReset": full_reset,
            "appium:autoGrantPermissions": grant_permissions,
            "appium:newCommandTimeout": 180,
            "appium:androidInstallTimeout": 180_000,
            "appium:uiautomator2ServerInstallTimeout": 180_000,
            "appium:uiautomator2ServerLaunchTimeout": 100_000,
            "appium:adbExecTimeout": 60_000,
            "appium:appWaitDuration": 60_000,
            "appium:forceAppLaunch": not reuse_installed,
            "appium:enforceAppInstall": not reuse_installed,
            "appium:dontStopAppOnReset": reuse_installed or requested.get("appium:dontStopAppOnReset") is True,
        }
        if reuse_installed:
            logging.getLogger(__name__).info("Resuming with the verified installed Android APK.")
        else:
            options["appium:app"] = str(self.apk)
        activity = requested.get("appium:appActivity")
        if isinstance(activity, str) and re.fullmatch(r"\.?[A-Za-z_$][A-Za-z0-9_.$]{0,499}", activity):
            options["appium:appActivity"] = activity
        result = self._call("POST", "/session", {"capabilities": {"alwaysMatch": options, "firstMatch": [{}]}}, timeout=330)
        value = result.get("value", {})
        if not result.get("status") and not result.get("interrupted"):
            sid = value.get("sessionId")
            if not isinstance(sid, str) or not ID.fullmatch(sid):
                raise ValueError("Appium did not return a valid native session ID.")
            self.session_id = sid
            capabilities = value.get("capabilities") or {}
            value["capabilities"] = {
                name: capabilities[name] for name in (
                    "platformName", "appium:platformVersion", "appium:appPackage", "appium:appActivity",
                    "appium:deviceName", "appium:udid", "appium:automationName",
                ) if name in capabilities
            }
        return result

    def execute(self, name: str, params: dict) -> dict:
        if name == "newSession":
            return self._start(params)
        if self.session_id is None or params.get("sessionId") != self.session_id:
            return {"interrupted": "The native Android session is no longer active."}
        command = NATIVE_COMMANDS.get(name)
        if command is None:
            raise ValueError("This command is outside the Android UI protocol.")
        method, route = command
        body = {key: value for key, value in params.items() if key != "sessionId"}
        for key in ("id", "name"):
            if "{" + key + "}" in route:
                value = body.pop(key, "")
                if not isinstance(value, str) or not ID.fullmatch(value):
                    raise ValueError("Invalid native element identifier.")
                route = route.replace("{" + key + "}", value)
        if name == "w3cExecuteScript":
            _mobile_command(body, self.package)
        result = self._call(method, f"/session/{self.session_id}{route}", body if method == "POST" else None)
        if name == "quit" and not result.get("status"):
            self.session_id = None
        return result

    def close(self) -> None:
        if self.session_id:
            try:
                self._call("DELETE", f"/session/{self.session_id}", timeout=8)
            except (ValueError, httpx.HTTPError):
                pass


def run_session(client, base_url, headers, manifest, appium_url, ready_devices, download, *, adb: str) -> None:
    parsed = urlparse(appium_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"} or parsed.username:
        raise ValueError("The paired runner requires a loopback-only Appium endpoint.")
    session_url = f"{base_url}/{manifest['session_id']}"
    with tempfile.TemporaryDirectory(prefix="qtxpert-autopilot-") as directory, httpx.Client(
        base_url=appium_url.rstrip("/") + "/", trust_env=False,
    ) as local_appium:
        apk = Path(directory) / "application.apk"
        session = AndroidSession(local_appium, manifest, apk, adb)
        try:
            while True:
                response = client.post(f"{session_url}/next", headers=headers)
                if response.status_code in {401, 409}:
                    return
                if response.status_code == 204:
                    time.sleep(0.35)
                    continue
                response.raise_for_status()
                command = response.json()
                try:
                    if command["name"] == "newSession" and not apk.is_file():
                        if session.device not in ready_devices():
                            raise RuntimeError("The selected ADB device is unavailable.")
                        with client.stream("GET", f"{session_url}/artifact", headers=headers, timeout=120) as artifact:
                            download(artifact, apk, manifest["app_sha256"])
                    result = session.execute(command["name"], command["params"])
                    if len(json.dumps(result)) > 7_900_000:
                        raise ValueError("Appium evidence exceeded the command size limit.")
                except (httpx.HTTPError, OSError, RuntimeError):
                    if command["name"] == "newSession" and not session.session_id:
                        apk.unlink(missing_ok=True)
                    result = {"interrupted": "The runner could not reach the Android device or install its repository APK."}
                except ValueError as exc:
                    result = {"status": "invalid argument", "value": {"message": str(exc)[:200]}}
                body = {"command_id": command["command_id"], "response_json": json.dumps(result)}
                # Retrying the answer never executes the device action again.
                for attempt in range(3):
                    try:
                        answer = client.post(f"{session_url}/answer", headers=headers, json=body)
                        if answer.status_code in {401, 409}:
                            return
                        answer.raise_for_status()
                        break
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        time.sleep(1)
        finally:
            session.close()
