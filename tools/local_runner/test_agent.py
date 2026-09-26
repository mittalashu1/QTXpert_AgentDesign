"""Fast standard-library tests for the local runner's fail-closed boundaries."""
import unittest
from pathlib import Path
import tempfile
import threading
from unittest.mock import MagicMock, patch

import httpx

from agent import compile_mobile_steps, normalize_api_url, inspect_local_stack, _download_artifact, execute_android_job, _case_error, _validate_startup_ui


class LocalRunnerProtocolTests(unittest.TestCase):
    def test_adb_formats_detect_only_online_devices(self):
        output = ("List of devices attached\n"
                  "emulator-5554          device product:sdk model:Pixel\n"
                  "usb-device\tdevice product:test\n"
                  "offline-device\toffline\n"
                  "locked-device unauthorized\n")
        with patch("agent.subprocess.run") as adb, patch("httpx.get") as status:
            adb.return_value.stdout = output
            status.return_value.is_success = True
            status.return_value.json.return_value = {"value": {"ready": True}}
            result = inspect_local_stack()
        self.assertEqual(result["devices"], ["emulator-5554", "usb-device"])

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

    def test_fill_values_do_not_leak_into_error_report(self):
        self.assertEqual(_case_error(RuntimeError("request contained private-value"), ["fill id :: password :: private-value"]), "request contained [redacted input]")

    def test_system_crash_dialog_cannot_validate_app_startup(self):
        for source in ("", '<node resource-id="android:id/aerr_close"/>', '<node resource-id="android:id/aerr_wait"/>'):
            with self.assertRaises(RuntimeError):
                _validate_startup_ui(source)
        _validate_startup_ui('<node package="com.example.app" text="Sign in"/>')


if __name__ == "__main__":
    unittest.main(verbosity=2)
