"""Fast standard-library tests for the local runner's fail-closed boundaries."""
import unittest
from pathlib import Path
import tempfile
import threading
from unittest.mock import MagicMock, call, patch

import httpx

from agent import compile_mobile_steps, normalize_api_url, inspect_local_stack, _download_artifact, execute_android_job, _case_error, _validate_startup_ui
from autopilot_android import AndroidSession


class LocalRunnerProtocolTests(unittest.TestCase):
    def test_adb_formats_detect_only_online_devices(self):
        output = ("List of devices attached\n"
                  "emulator-5554          device product:sdk model:Pixel\n"
                  "usb-device\tdevice product:test\n"
                  "offline-device\toffline\n"
                  "locked-device unauthorized\n")
        with patch("agent.subprocess.run") as adb, patch("httpx.get") as status, patch("agent.platform.system", return_value="Windows"):
            adb.side_effect = [MagicMock(stdout=output), MagicMock(stdout="1\n"), MagicMock(stdout="1\n")]
            status.return_value.is_success = True
            status.return_value.json.return_value = {"value": {"ready": True}}
            result = inspect_local_stack()
        self.assertEqual(result["devices"], ["emulator-5554", "usb-device"])

    def test_online_but_booting_device_is_not_ready(self):
        with patch("agent.subprocess.run") as adb, patch("httpx.get") as status, patch("agent.platform.system", return_value="Windows"):
            adb.side_effect = [MagicMock(stdout="List of devices attached\nemulator-5554 device\n"), MagicMock(stdout="\n")]
            status.return_value.is_success = True
            status.return_value.json.return_value = {"value": {"ready": True}}
            result = inspect_local_stack()
        self.assertEqual(result["online_devices"], ["emulator-5554"])
        self.assertEqual(result["devices"], [])
        self.assertEqual(result["boot_state"]["emulator-5554"], "booting")
        self.assertFalse(result["ready"])

    def test_device_boot_probe_timeout_is_not_ready(self):
        import subprocess
        with patch("agent.subprocess.run") as adb, patch("httpx.get") as status, patch("agent.platform.system", return_value="Windows"):
            adb.side_effect = [MagicMock(stdout="List of devices attached\nemulator-5554 device\n"), subprocess.TimeoutExpired("adb", 8)]
            status.return_value.is_success = True
            status.return_value.json.return_value = {"value": {"ready": True}}
            result = inspect_local_stack()
        self.assertEqual(result["boot_state"]["emulator-5554"], "unavailable")
        self.assertFalse(result["ready"])

    def test_artifact_download_keeps_one_api_prefix_and_checks_hash(self):
        import hashlib
        import uuid
        runner_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
        route = f"/api/v1/local-runners/{runner_id}/jobs/{run_id}/artifact"
        content = b"test apk bytes"
        def handle(request):
            self.assertEqual(str(request.url), "https://design.example" + route)
            self.assertEqual(request.headers["x-qtxpert-lease"], "lease")
            return httpx.Response(200, content=content)
        credentials = {"runner_id": runner_id, "runner_token": "test-secret", "api_url": "https://design.example/api/v1"}
        with httpx.Client(transport=httpx.MockTransport(handle)) as client, tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "app.apk"
            job = {"artifact_path": route, "app_sha256": hashlib.sha256(content).hexdigest()}
            _download_artifact(client, credentials, job, "lease", path)
            self.assertEqual(path.read_bytes(), content)
            job["app_sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                _download_artifact(client, credentials, job, "lease", path)

    def test_android_resume_reuses_only_the_repository_apk(self):
        digest = "a" * 64
        manifest = {"device_name": "usb-device", "package_name": "com.example.app", "app_sha256": digest}
        path = "/data/app/~~instance/com.example.app-instance/base.apk"
        for installed_digest, should_install in ((digest, False), ("b" * 64, True)):
            with self.subTest(should_install=should_install), patch(
                "autopilot_android.subprocess.run",
                side_effect=[MagicMock(stdout=f"package:{path}\n"), MagicMock(stdout=f"{installed_digest}  {path}\n")],
            ) as adb:
                session = AndroidSession(MagicMock(), manifest, Path("app.apk"), "adb")
                with patch.object(session, "_call", return_value={"value": {"sessionId": "binary-session"}}) as call:
                    session.execute("newSession", {"capabilities": {"alwaysMatch": {"appium:noReset": True}}})
                capabilities = call.call_args.args[2]["capabilities"]["alwaysMatch"]
                self.assertEqual("appium:app" in capabilities, should_install)
                self.assertEqual(capabilities["appium:enforceAppInstall"], should_install)
                self.assertEqual(capabilities["appium:forceAppLaunch"], should_install)
                self.assertEqual(adb.call_args.args[0], ["adb", "-s", "usb-device", "shell", "sha256sum", path])

    def test_android_runner_accepts_appium_clear_as_well_as_selenium_clear(self):
        manifest = {"device_name": "usb-device", "package_name": "com.example.app", "app_sha256": "a" * 64}
        session = AndroidSession(MagicMock(), manifest, Path("app.apk"), "adb")
        session.session_id = "test-session"
        with patch.object(session, "_call", return_value={"value": None}) as call:
            for command in ("clear", "clearElement"):
                session.execute(command, {"sessionId": "test-session", "id": "field-1"})
                call.assert_called_with("POST", "/session/test-session/element/field-1/clear", {})

    def test_api_url_requires_https_for_cloud(self):
        self.assertEqual(normalize_api_url("https://design.example"), "https://design.example/api/v1")
        self.assertEqual(normalize_api_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000/api/v1")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            normalize_api_url("http://design.example")
        for invalid in ("ftp://localhost", "https://user:secret@design.example", "https://design.example?token=secret", "https://design.example#secret"):
            with self.assertRaises(ValueError):
                normalize_api_url(invalid)

    def test_mobile_compiler_accepts_only_explicit_actions(self):
        actions = compile_mobile_steps([
            "launch app",
            "tap accessibility_id :: Sign in",
            "fill id :: username :: qa-user",
            "assert-text Home",
            "assert-visible xpath :: //android.widget.Button[@text='Continue']",
            "back",
        ])
        self.assertEqual([item[0] for item in actions], ["tap", "fill", "assert-text", "assert-visible", "back"])
        self.assertEqual(actions[0], ("tap", "accessibility_id", "Sign in"))
        self.assertEqual(actions[1], ("fill", "id", "username :: qa-user"))

    def test_unknown_prose_and_locator_strategies_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "Unsupported mobile automation step"):
            compile_mobile_steps(["explore the investment page and choose something suitable"])
        with self.assertRaisesRegex(ValueError, "strategy"):
            compile_mobile_steps(["tap css :: .submit"])

    def test_empty_steps_and_hidden_control_are_not_passed(self):
        driver = MagicMock()
        driver.get_screenshot_as_png.return_value = b"png"
        driver.page_source = "<screen/>"
        driver.capabilities = {}
        driver.current_package = "com.example.app"
        driver.current_activity = ".MainActivity"
        driver.find_element.return_value.is_displayed.return_value = False
        job = {"target_kind": "android", "cases": [
            {"result_id": "empty", "steps": []},
            {"result_id": "hidden", "steps": ["assert-visible id :: target"]},
        ]}
        with patch("appium.webdriver.Remote", return_value=driver), patch("agent.inspect_local_stack", return_value={"devices": ["emulator-5554"]}), patch("agent.time.sleep"):
            report = execute_android_job(Path("app.apk"), job, "http://127.0.0.1:4723")
        self.assertEqual([item["status"] for item in report["results"]], ["blocked", "failed"])
        driver.quit.assert_called_once()

    def test_cancelled_lease_prevents_device_actions(self):
        driver = MagicMock()
        driver.get_screenshot_as_png.return_value = b"png"
        driver.page_source = "<screen/>"
        driver.capabilities = {}
        driver.current_package = "com.example.app"
        driver.current_activity = ".MainActivity"
        stop = threading.Event()
        stop.set()
        job = {"target_kind": "android", "cases": [{"result_id": "cancelled", "steps": ["tap Login"]}]}
        with patch("appium.webdriver.Remote", return_value=driver), patch("agent.inspect_local_stack", return_value={"devices": ["emulator-5554"]}), patch("agent.time.sleep"):
            report = execute_android_job(Path("app.apk"), job, "http://127.0.0.1:4723", stop)
        self.assertEqual(report["results"][0]["status"], "failed")
        driver.find_element.assert_not_called()
        driver.quit.assert_called_once()

    def test_authored_batch_relaunches_only_when_app_state_is_not_retained(self):
        from selenium.common.exceptions import NoSuchElementException

        for keep_app_state in (False, True):
            with self.subTest(keep_app_state=keep_app_state):
                driver = MagicMock()
                driver.get_screenshot_as_png.return_value = b"png"
                driver.page_source = "<screen/>"
                driver.capabilities = {"appium:appPackage": "com.example.app"}
                driver.current_package = "com.example.app"
                driver.current_activity = ".MainActivity"
                state = {"screen": "welcome"}

                def find_element(strategy, locator):
                    if locator != state["screen"]:
                        raise NoSuchElementException()
                    element = MagicMock()
                    element.click.side_effect = lambda: state.update(screen="home")
                    return element

                driver.find_element.side_effect = find_element
                driver.activate_app.side_effect = lambda package: state.update(screen="welcome")
                job = {"target_kind": "android", "no_reset": keep_app_state, "cases": [
                    {"result_id": "first", "authored_steps": [
                        {"action": "tap", "strategy": "id", "locator": "welcome"},
                    ]},
                    {"result_id": "second", "authored_steps": [
                        {"action": "assert_visible", "strategy": "id", "locator": "home" if keep_app_state else "welcome"},
                    ]},
                ]}
                with (
                    patch("appium.webdriver.Remote", return_value=driver),
                    patch("agent.inspect_local_stack", return_value={"devices": ["emulator-5554"]}),
                    patch("agent.time.sleep"),
                ):
                    report = execute_android_job(Path("app.apk"), job, "http://127.0.0.1:4723")
                self.assertEqual([item["status"] for item in report["results"]], ["passed", "passed"])
                lifecycle_calls = [entry for entry in driver.method_calls if entry[0] in ("terminate_app", "activate_app")]
                self.assertEqual(lifecycle_calls, [] if keep_app_state else [
                    call.terminate_app("com.example.app"), call.activate_app("com.example.app"),
                ])

    def test_fill_values_do_not_leak_into_error_report(self):
        self.assertEqual(_case_error(RuntimeError("request contained private-value"), ["fill id :: password :: private-value"]), "request contained [redacted input]")

    def test_system_crash_dialog_cannot_validate_app_startup(self):
        for source in ("", '<node resource-id="android:id/aerr_close"/>', '<node resource-id="android:id/aerr_wait"/>'):
            with self.assertRaises(RuntimeError):
                _validate_startup_ui(source)
        _validate_startup_ui('<node package="com.example.app" text="Sign in"/>')


if __name__ == "__main__":
    unittest.main(verbosity=2)
