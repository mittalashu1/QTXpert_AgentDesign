"""Windows outbound runner for QTXpert Android execution jobs.

No inbound firewall rule or public Appium endpoint is required. Pair once with
an expiring code from QTXpert, then run this process while the PC, emulator,
ADB and loopback-only Appium server are available.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlparse, urljoin

LOG = logging.getLogger("qtxpert.local_runner")
DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"
LEASE_HEARTBEAT_SECONDS = 25
MAX_APK_BYTES = 1024 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _windows_protect(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("The packaged runner currently stores its token with Windows DPAPI; run it on Windows.")
    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = DataBlob()
    if decrypt:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        )
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "QTXpert local runner", None, None, None, 0, ctypes.byref(output)
        )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def credential_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "QTXpert" / "local-runner.dpapi"


def save_credentials(credentials: dict[str, str]) -> Path:
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ciphertext = _windows_protect(json.dumps(credentials).encode("utf-8"), decrypt=False)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(ciphertext)
    os.replace(temp, path)
    return path


def load_credentials() -> dict[str, str]:
    path = credential_path()
    if not path.is_file():
        raise RuntimeError("This computer is not paired. Run the pair command shown in QTXpert Test Execution.")
    try:
        values = json.loads(_windows_protect(path.read_bytes(), decrypt=True))
    except Exception as exc:
        raise RuntimeError("The saved runner identity cannot be decrypted for this Windows user.") from exc
    if not all(isinstance(values.get(key), str) for key in ("api_url", "runner_id", "runner_token")):
        raise RuntimeError("The saved runner identity is invalid; revoke it in QTXpert and pair again.")
    return values


def normalize_api_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        raise ValueError("QTXpert API URL is required")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a plain HTTP(S) API URL without embedded credentials, query parameters, or fragments")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Runner-to-cloud traffic must use HTTPS")
    if not parsed.path.rstrip("/").endswith("/api/v1"):
        base += "/api/v1"
    return base


def _headers(credentials: dict[str, str], lease: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {credentials['runner_token']}"}
    if lease:
        result["X-QTXpert-Lease"] = lease
    return result


def _http_client() -> httpx.Client:
    import httpx

    return httpx.Client(timeout=httpx.Timeout(15, connect=10), follow_redirects=False)


def _adb_executable() -> str:
    """Prefer the Android SDK configured for this user, even if adb is not on PATH."""
    candidates: list[Path] = []
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "adb"


def inspect_local_stack(appium_url: str = DEFAULT_APPIUM_URL) -> dict[str, Any]:
    result: dict[str, Any] = {
        "os": platform.system(),
        "python": sys.version.split()[0],
        "appium_python": False,
        "appium_server": False,
        "adb": False,
        "adb_path": _adb_executable(),
        "devices": [],
        "ready": False,
    }
    try:
        import appium  # noqa: F401
        result["appium_python"] = True
    except ImportError:
        pass
    try:
        import httpx

        response = httpx.get(f"{appium_url.rstrip('/')}/status", timeout=5)
        result["appium_server"] = response.is_success and bool(response.json().get("value", {}).get("ready", True))
    except Exception as exc:
        result["appium_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    try:
        completed = subprocess.run([result["adb_path"], "devices", "-l"], capture_output=True, text=True, timeout=8, check=True)
        result["adb"] = True
        result["devices"] = [
            line.split()[0]
            for line in completed.stdout.splitlines()[1:]
            if len(line.split()) >= 2 and line.split()[1] == "device"
        ]
    except Exception as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        result["adb_error"] = f"{type(exc).__name__}: {detail.strip()[:240]}"
    result["ready"] = bool(
        result["os"] == "Windows"
        and result["appium_python"]
        and result["appium_server"]
        and result["adb"]
        and result["devices"]
    )
    return result


def pair(api_url: str, enrollment_token: str, name: str, appium_url: str) -> Path:
    import httpx

    api_url = normalize_api_url(api_url)
    stack = inspect_local_stack(appium_url)
    if not stack["ready"]:
        raise RuntimeError(f"Local Android stack is not ready: {json.dumps(stack)}")
    payload = {
        "enrollment_token": enrollment_token.strip(),
        "name": name.strip(),
        "os_name": "Windows",
        "platforms": ["android"],
        "device_names": stack["devices"],
    }
    with _http_client() as client:
        response = client.post(f"{api_url}/local-runners/pair", json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"QTXpert pairing failed ({response.status_code}): {response.text[:500]}")
    response_data = response.json()
    path = save_credentials({
        "api_url": api_url,
        "runner_id": response_data["runner_id"],
        "runner_token": response_data["runner_token"],
        "appium_url": appium_url.rstrip("/"),
    })
    return path


def _download_artifact(client: httpx.Client, credentials: dict[str, str], job: dict[str, Any], lease: str, destination: Path) -> None:
    import httpx

    relative = str(job.get("artifact_path") or "")
    expected_prefix = f"/api/v1/local-runners/{credentials['runner_id']}/jobs/"
    if not relative.startswith(expected_prefix) or not relative.endswith("/artifact"):
        raise RuntimeError("QTXpert returned an invalid artifact route; refusing the download")
    url = urljoin(credentials["api_url"], relative)
    digest = hashlib.sha256()
    size = 0
    with client.stream("GET", url, headers=_headers(credentials, lease), timeout=httpx.Timeout(1800, connect=15)) as response:
        response.raise_for_status()
        length = int(response.headers.get("content-length", "0") or 0)
        if length > MAX_APK_BYTES:
            raise RuntimeError("The application package exceeds the local runner safety limit")
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise RuntimeError("The application package exceeded the local runner safety limit while downloading")
                digest.update(chunk)
                handle.write(chunk)
    expected = str(job.get("app_sha256") or "").lower()
    if expected and not hmac.compare_digest(digest.hexdigest(), expected):
        raise RuntimeError("The downloaded application checksum does not match the project repository")


def _locator(strategy: str | None):
    from appium.webdriver.common.appiumby import AppiumBy

    return {
        "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
        "id": AppiumBy.ID,
        "xpath": AppiumBy.XPATH,
    }.get(strategy or "accessibility_id")


def compile_mobile_steps(steps: list[str]) -> list[tuple[str, str | None, str | None]]:
    """Match the backend's constrained mobile DSL; never interpret prose as actions."""
    compiled: list[tuple[str, str | None, str | None]] = []
    for raw in steps:
        step = str(raw).strip()
        lower = step.lower()
        if lower in {"launch", "launch app", "open app", "start app", "install and launch application"}:
            continue
        if lower in {"back", "press back", "navigate back"}:
            compiled.append(("back", None, None))
            continue
        if lower.startswith("tap ") or lower.startswith("click "):
            locator = step[4:] if lower.startswith("tap ") else step[6:]
            strategy, value = _parse_locator(locator)
            compiled.append(("tap", strategy, value))
            continue
        if lower.startswith("fill ") and " :: " in step:
            parts = [part.strip() for part in step[5:].split(" :: ")]
            if len(parts) == 3 and parts[0].lower() in {"accessibility_id", "id", "xpath"}:
                strategy, locator, text_value = parts
            elif len(parts) == 2:
                strategy, locator, text_value = "accessibility_id", parts[0], parts[1]
            else:
                raise ValueError("Use fill <locator> :: <value> or fill <strategy> :: <locator> :: <value>.")
            if not locator or not text_value:
                raise ValueError("Mobile fill locator and value cannot be empty.")
            compiled.append(("fill", strategy.lower(), f"{locator} :: {text_value}"))
            continue
        if lower.startswith("assert-text "):
            expected = step[12:].strip()
            if not expected:
                raise ValueError("Mobile assert-text value cannot be empty.")
            compiled.append(("assert-text", None, expected))
            continue
        if lower.startswith("assert-visible "):
            strategy, value = _parse_locator(step[15:])
            compiled.append(("assert-visible", strategy, value))
            continue
        raise ValueError(f"Unsupported mobile automation step: {step!r}")
    return compiled


def _parse_locator(value: str) -> tuple[str, str]:
    raw = value.strip()
    if " :: " in raw:
        strategy, locator = raw.split(" :: ", 1)
        strategy = strategy.strip().lower()
        if strategy not in {"accessibility_id", "id", "xpath"}:
            raise ValueError("Mobile locator strategy must be accessibility_id, id, or xpath.")
        if not locator.strip():
            raise ValueError("Mobile locator cannot be empty.")
        return strategy, locator.strip()
    if not raw:
        raise ValueError("Mobile locator cannot be empty.")
    return "accessibility_id", raw


def _case_error(exc: Exception, steps: list[str]) -> str:
    message = str(exc)[:4000]
    # Even synthetic fill values may include a password or personal data.
    for step in steps:
        if str(step).lower().startswith("fill ") and " :: " in str(step):
            value = str(step).split(" :: ")[-1].strip()
            if value:
                message = message.replace(value, "[redacted input]")
    return message


def _validate_startup_ui(source: str) -> None:
    if not source.strip():
        raise RuntimeError("The device returned an empty UI hierarchy; startup was not validated")
    if any(marker in source for marker in ("android:id/aerr_close", "android:id/aerr_wait", "android:id/aerr_restart")):
        raise RuntimeError("An Android crash or application-not-responding dialog is blocking the test. Check the emulator's available memory and app logs.")


def execute_android_job(app_path: Path, job: dict[str, Any], appium_url: str, stop: threading.Event | None = None) -> dict[str, Any]:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    if job.get("target_kind") != "android":
        raise RuntimeError("This Windows runner only accepts Android jobs. Pair a Mac runner for iOS.")
    configured_device = str(job.get("device_name") or "").strip()
    devices = inspect_local_stack(appium_url).get("devices", [])
    if not devices:
        raise RuntimeError("No Android device or emulator is online in ADB")
    if configured_device and configured_device not in devices:
        # A friendly Android model name is accepted only when exactly one ADB
        # device is connected. This prevents running on an unintended device.
        if len(devices) != 1:
            raise RuntimeError(f"Requested device {configured_device!r} is not online; available: {', '.join(devices)}")
        configured_device = devices[0]
    elif not configured_device:
        if len(devices) != 1:
            raise RuntimeError("Set a specific emulator/device because more than one Android device is connected")
        configured_device = devices[0]

    capabilities = {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:deviceName": configured_device,
        "appium:udid": configured_device,
        "appium:app": str(app_path),
        "appium:noReset": bool(job.get("no_reset", False)),
        "appium:autoGrantPermissions": bool(job.get("auto_grant_permissions", True)),
        "appium:newCommandTimeout": 180,
        "appium:androidInstallTimeout": 300_000,
        "appium:uiautomator2ServerInstallTimeout": 300_000,
        "appium:uiautomator2ServerLaunchTimeout": 120_000,
        "appium:adbExecTimeout": 120_000,
        "appium:appWaitDuration": 120_000,
    }
    if job.get("platform_version"):
        capabilities["appium:platformVersion"] = str(job["platform_version"])
    options = UiAutomator2Options().load_capabilities(capabilities)
    driver = webdriver.Remote(appium_url, options=options)
    results: list[dict[str, Any]] = []
    try:
        driver.implicitly_wait(5)
        time.sleep(2)
        screenshot = driver.get_screenshot_as_png()
        if len(screenshot) > MAX_SCREENSHOT_BYTES:
            raise RuntimeError("Startup screenshot exceeds the 5MB evidence cap")
        source = driver.page_source or ""
        _validate_startup_ui(source)
        page_source = source.encode("utf-8")[:MAX_SOURCE_BYTES]
        app_package = driver.current_package
        app_activity = driver.current_activity
        for case in job.get("cases", []):
            started = time.monotonic()
            outcome, error = "passed", None
            try:
                if stop is not None and stop.is_set():
                    raise RuntimeError("Execution lease was revoked or lost; no further device actions are allowed")
                if not case.get("steps"):
                    raise ValueError("This test has no executable steps; it has not been validated")
                for action, strategy, value in compile_mobile_steps(case.get("steps") or []):
                    if stop is not None and stop.is_set():
                        raise RuntimeError("Execution lease was revoked or lost; no further device actions are allowed")
                    if action == "back":
                        driver.back()
                    elif action == "tap":
                        driver.find_element(_locator(strategy), value or "").click()
                    elif action == "fill":
                        locator, text_value = (value or "").split(" :: ", 1)
                        element = driver.find_element(_locator(strategy), locator)
                        element.clear()
                        element.send_keys(text_value)
                    elif action == "assert-text":
                        if (value or "").casefold() not in (driver.page_source or "").casefold():
                            raise AssertionError(f"Expected UI text {value!r} was not visible")
                    elif action == "assert-visible":
                        if not driver.find_element(_locator(strategy), value or "").is_displayed():
                            raise AssertionError("The expected UI control exists but is not visible")
            except ValueError as exc:
                outcome, error = "blocked", _case_error(exc, case.get("steps") or [])
            except Exception as exc:
                outcome, error = "failed", _case_error(exc, case.get("steps") or [])
            results.append({
                "result_id": case["result_id"],
                "status": outcome,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error_message": error,
            })
        return {
            "results": results,
            "current_package": app_package,
            "current_activity": app_activity,
            "device_name": configured_device,
            "platform_version": driver.capabilities.get("platformVersion") or driver.capabilities.get("appium:platformVersion"),
            "screenshot_base64": base64.b64encode(screenshot).decode("ascii"),
            "page_source_base64": base64.b64encode(page_source).decode("ascii"),
        }
    finally:
        try:
            driver.quit()
        except Exception:
            LOG.debug("Appium session cleanup failed", exc_info=True)


def _heartbeat_loop(credentials: dict[str, str], run_id: str, lease: str, stop: threading.Event) -> None:
    endpoint = f"{credentials['api_url']}/local-runners/{credentials['runner_id']}/jobs/{run_id}/heartbeat"
    with _http_client() as client:
        while not stop.wait(LEASE_HEARTBEAT_SECONDS):
            try:
                response = client.post(endpoint, headers=_headers(credentials, lease))
                if response.status_code in {401, 409}:
                    LOG.error("Runner authorization or execution lease is no longer valid; stopping this job")
                    stop.set()
                    return
                response.raise_for_status()
            except Exception as exc:
                LOG.warning("Could not renew execution lease; will retry next heartbeat (%s)", type(exc).__name__)


def _execute_claimed_job(client: httpx.Client, credentials: dict[str, str], job: dict[str, Any]) -> None:
    run_id = str(job["run_id"])
    lease = str(job["lease_token"])
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(credentials, run_id, lease, stop_heartbeat),
        daemon=True,
    )
    heartbeat.start()
    try:
        with tempfile.TemporaryDirectory(prefix="qtxpert-local-runner-") as temp_dir:
            app_path = Path(temp_dir) / Path(str(job.get("app_filename") or "application.apk")).name
            _download_artifact(client, credentials, job, lease, app_path)
            if stop_heartbeat.is_set():
                raise RuntimeError("Execution lease is no longer valid")
            report = execute_android_job(app_path, job, credentials.get("appium_url", DEFAULT_APPIUM_URL), stop_heartbeat)
            endpoint = f"{credentials['api_url']}/local-runners/{credentials['runner_id']}/jobs/{run_id}/complete"
            response = client.post(endpoint, headers=_headers(credentials, lease), json=report, timeout=60)
            response.raise_for_status()
            outcome = response.json()
            LOG.info(
                "Run %s completed: passed=%s failed=%s blocked=%s",
                run_id, outcome.get("passed", 0), outcome.get("failed", 0), outcome.get("blocked", 0),
            )
    except Exception as exc:
        message = f"Local runner could not complete the Android job ({type(exc).__name__}): {str(exc)[:1200]}"
        # HTTP/Appium exceptions can contain request bodies. Never write their
        # full traceback to a persistent log, where test credentials may leak.
        LOG.error("Run %s failed (%s)", run_id, type(exc).__name__)
        endpoint = f"{credentials['api_url']}/local-runners/{credentials['runner_id']}/jobs/{run_id}/fail"
        try:
            response = client.post(endpoint, headers=_headers(credentials, lease), json={"message": message})
            if response.status_code >= 400:
                LOG.error("Could not report run failure (%s)", response.status_code)
        except Exception:
            LOG.exception("Could not report the runner failure to QTXpert")
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=2)


def run_agent(*, once: bool = False, poll_seconds: int = 5) -> int:
    import httpx

    credentials = load_credentials()
    stack = inspect_local_stack(credentials.get("appium_url", DEFAULT_APPIUM_URL))
    if not stack["ready"]:
        LOG.error("Local Android setup is not ready: %s", json.dumps(stack))
        return 2
    claim_url = f"{credentials['api_url']}/local-runners/{credentials['runner_id']}/jobs/claim"
    heartbeat_url = f"{credentials['api_url']}/local-runners/{credentials['runner_id']}/heartbeat"
    stop = threading.Event()
    with _http_client() as client:
        try:
            client.post(heartbeat_url, headers=_headers(credentials)).raise_for_status()
            LOG.info("Runner online; device(s): %s", ", ".join(stack["devices"]))
            while not stop.is_set():
                try:
                    response = client.post(claim_url, headers=_headers(credentials))
                    if response.status_code == 204:
                        if once:
                            LOG.info("No queued Android runs for this project")
                            return 0
                        stop.wait(poll_seconds)
                        continue
                    response.raise_for_status()
                    job = response.json()
                    LOG.info("Claimed run %s with %s cases", job.get("run_id"), len(job.get("cases", [])))
                    _execute_claimed_job(client, credentials, job)
                    if once:
                        return 0
                except httpx.HTTPError as exc:
                    LOG.warning("QTXpert connection unavailable (%s); retrying", type(exc).__name__)
                    if once:
                        return 3
                    stop.wait(max(5, poll_seconds))
        except KeyboardInterrupt:
            LOG.info("Stopping local runner gracefully")
            stop.set()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="QTXpert Windows Android runner (outbound HTTPS only)")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pair_parser = subparsers.add_parser("pair", help="Pair this Windows machine with a one-time QTXpert token")
    pair_parser.add_argument("--api-url", required=True, help="QTXpert API origin or /api/v1 URL")
    pair_parser.add_argument("--token", required=True, help="One-time token created in QTXpert Test Execution")
    pair_parser.add_argument("--name", default=f"{platform.node()} Android runner")
    pair_parser.add_argument("--appium-url", default=DEFAULT_APPIUM_URL)
    subparsers.add_parser("doctor", help="Check local Appium, Python client, and ADB device state")
    run_parser = subparsers.add_parser("run", help="Poll QTXpert and execute queued Android runs")
    run_parser.add_argument("--once", action="store_true", help="Claim at most one run and exit")
    run_parser.add_argument("--poll-seconds", type=int, default=5, choices=range(2, 31))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        if args.command == "doctor":
            result = inspect_local_stack()
            print(json.dumps(result, indent=2))
            return 0 if result["ready"] else 2
        if args.command == "pair":
            saved = pair(args.api_url, args.token, args.name, args.appium_url)
            LOG.info("Pairing complete. Runner token is DPAPI-protected for this Windows user at %s", saved)
            return 0
        return run_agent(once=args.once, poll_seconds=args.poll_seconds)
    except Exception as exc:
        LOG.error("%s", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
