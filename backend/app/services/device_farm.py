"""AWS Device Farm remote Appium adapter.

Device Farm's remote-access API gives QTXpert a short-lived Appium endpoint
for one real Android device.  The adapter deliberately owns the whole
lifecycle: upload the already-approved APK, wait for AWS to process it, select
an available device, start a metered remote session, install the app when the
installed AWS SDK exposes that as a separate operation, and stop the session
when the bounded Autopilot operation finishes.

No AWS credentials are stored here.  boto3 uses the standard credential chain
provided by the hosting environment (for example, Render environment
secrets, an attached role, or a local AWS profile).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.config import Settings


class DeviceFarmError(RuntimeError):
    """Raised when Device Farm cannot prepare or expose an Appium session."""


@dataclass(frozen=True)
class DeviceFarmDevice:
    arn: str
    name: str
    model: str
    platform_version: str
    availability: str
    instance_arn: str | None = None


@dataclass(frozen=True)
class DeviceFarmSession:
    arn: str
    app_arn: str
    device: DeviceFarmDevice
    appium_url: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _device_from_payload(payload: dict[str, Any]) -> DeviceFarmDevice:
    return DeviceFarmDevice(
        arn=_text(payload.get("arn")),
        name=_text(payload.get("name") or payload.get("model") or "Android device"),
        model=_text(payload.get("model") or payload.get("name") or "Android device"),
        platform_version=_text(payload.get("os") or payload.get("platformVersion")),
        availability=_text(payload.get("availability") or "UNKNOWN"),
        instance_arn=_text(payload.get("instanceArn")) or None,
    )


def choose_device(
    devices: Iterable[dict[str, Any]],
    *,
    preferred_arn: str | None,
    preferred_name: str,
    platform_version: str | None,
) -> DeviceFarmDevice:
    """Select one available Android device without creating a device pool."""

    candidates = [_device_from_payload(item) for item in devices if _text(item.get("arn"))]
    if not candidates:
        raise DeviceFarmError("AWS Device Farm returned no Android devices for this project")

    available = [
        item for item in candidates
        if item.availability.upper() in {"AVAILABLE", "HIGHLY_AVAILABLE"}
    ] or candidates

    if preferred_arn:
        exact = [item for item in available if item.arn == preferred_arn]
        if exact:
            return exact[0]
        raise DeviceFarmError("The configured AWS Device Farm device is not currently available")

    desired = preferred_name.casefold().strip()
    desired_version = (platform_version or "").casefold().strip()

    def score(item: DeviceFarmDevice) -> tuple[int, int, int, str]:
        name = f"{item.name} {item.model}".casefold()
        name_match = int(bool(desired and (desired in name or name in desired)))
        version_match = int(bool(desired_version and desired_version == item.platform_version.casefold()))
        available_match = int(item.availability.upper() in {"AVAILABLE", "HIGHLY_AVAILABLE"})
        return (name_match, version_match, available_match, item.name)

    return sorted(available, key=score, reverse=True)[0]


class DeviceFarmService:
    """Small synchronous AWS adapter used from asyncio worker threads."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.DEVICE_FARM_ENABLED and self.settings.DEVICE_FARM_PROJECT_ARN)

    def _client(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - covered by deployment install
            raise DeviceFarmError("The backend AWS SDK is not installed") from exc
        try:
            client = boto3.client("devicefarm", region_name=self.settings.DEVICE_FARM_REGION)
            self._register_raw_endpoint_capture(client)
            return client
        except Exception as exc:  # pragma: no cover - provider-specific SDK errors
            raise DeviceFarmError(f"AWS Device Farm client could not be initialized: {exc}") from exc

    @staticmethod
    def _register_raw_endpoint_capture(client: Any) -> None:
        """Preserve new endpoint fields when an older botocore model parses the response.

        Device Farm added ``remoteAccessSession.endpoints.remoteDriverEndpoint``
        after some supported botocore releases.  The service response is JSON,
        so the raw after-call payload remains available even when an older model
        drops that unknown field during normal parsing.
        """

        def merge_endpoint(*, http_response: Any, parsed: Any, **_: Any) -> None:
            try:
                raw_content = getattr(http_response, "content", b"")
                if isinstance(raw_content, bytes):
                    raw_content = raw_content.decode("utf-8")
                raw_payload = json.loads(raw_content or "{}")
                raw_session = raw_payload.get("remoteAccessSession") or {}
                raw_endpoints = raw_session.get("endpoints") or {}
                if not raw_endpoints or not isinstance(parsed, dict):
                    return
                parsed_session = parsed.setdefault("remoteAccessSession", {})
                if isinstance(parsed_session, dict):
                    parsed_session["endpoints"] = raw_endpoints
            except (AttributeError, TypeError, UnicodeDecodeError, ValueError):
                return

        try:
            events = client.meta.events
            events.register_first(
                "after-call.devicefarm.GetRemoteAccessSession",
                merge_endpoint,
            )
        except Exception:
            # The compatibility hook is best effort; normal SDK parsing still
            # works on models that already know the endpoint field.
            return

    def _project_arn(self) -> str:
        value = _text(self.settings.DEVICE_FARM_PROJECT_ARN)
        if not value:
            raise DeviceFarmError(
                "AWS Device Farm is not configured. Set DEVICE_FARM_PROJECT_ARN in the backend environment."
            )
        return value

    @staticmethod
    def _operation_input_members(client: Any, operation_name: str) -> set[str]:
        """Return the request fields known by the installed botocore model.

        AWS added app installation and Appium-version parameters to the
        Device Farm remote-access request over time.  Render may resolve a
        botocore model older than the live service, so the adapter must shape
        its request to the SDK that is actually installed instead of sending
        fields that fail local parameter validation.
        """

        try:
            operation = client.meta.service_model.operation_model(operation_name)
            input_shape = operation.input_shape
            return set((input_shape.members or {}).keys()) if input_shape else set()
        except Exception:
            return set()

    @classmethod
    def _configuration_members(cls, client: Any) -> set[str]:
        """Return the fields supported inside CreateRemoteAccessSession.configuration."""

        try:
            operation = client.meta.service_model.operation_model("CreateRemoteAccessSession")
            input_shape = operation.input_shape
            configuration_shape = (input_shape.members or {}).get("configuration") if input_shape else None
            return set((configuration_shape.members or {}).keys()) if configuration_shape else set()
        except Exception:
            return set()

    def list_android_devices(self) -> list[dict[str, Any]]:
        """Return Android devices exposed by the account/project (read-only)."""

        client = self._client()
        filters = [{"attribute": "PLATFORM", "operator": "EQUALS", "values": ["ANDROID"]}]
        devices: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"arn": self._project_arn(), "filters": filters}
            if token:
                kwargs["nextToken"] = token
            response = client.list_devices(**kwargs)
            devices.extend(response.get("devices") or [])
            token = _text(response.get("nextToken")) or None
            if not token:
                return devices

    def _wait_for_upload(self, client: Any, upload_arn: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.DEVICE_FARM_UPLOAD_TIMEOUT_SECONDS
        while True:
            response = client.get_upload(arn=upload_arn)
            upload = response.get("upload") or {}
            status = _text(upload.get("status")).upper()
            if status == "SUCCEEDED":
                return upload
            if status == "FAILED":
                message = _text(upload.get("message")) or "AWS Device Farm rejected the app upload"
                raise DeviceFarmError(message[:500])
            if time.monotonic() >= deadline:
                raise DeviceFarmError("Timed out while AWS Device Farm processed the app upload")
            time.sleep(self.settings.DEVICE_FARM_POLL_INTERVAL_SECONDS)

    def upload_app(self, app_path: Path, sha256: str, cache_path: Path) -> str:
        """Upload an APK/IPA once per job hash and return its Device Farm ARN."""

        if not app_path.is_file():
            raise DeviceFarmError("The uploaded mobile artifact is unavailable for AWS Device Farm")
        suffix = app_path.suffix.lower()
        if suffix not in {".apk", ".ipa"}:
            raise DeviceFarmError("AWS Device Farm Appium requires an .apk or .ipa application artifact")

        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("sha256") == sha256 and _text(cached.get("app_arn")):
                    return str(cached["app_arn"])
            except (OSError, ValueError, TypeError):
                pass

        client = self._client()
        kind = "ANDROID_APP" if suffix == ".apk" else "IOS_APP"
        content_type = (
            "application/vnd.android.package-archive"
            if suffix == ".apk"
            else "application/octet-stream"
        )
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", app_path.name)[:220] or f"qtxpert{suffix}"
        if not safe_name.lower().endswith(suffix):
            safe_name = f"qtxpert-{sha256[:16]}{suffix}"
        created = client.create_upload(
            projectArn=self._project_arn(),
            name=safe_name,
            type=kind,
            contentType=content_type,
        )
        upload = created.get("upload") or {}
        upload_arn = _text(upload.get("arn"))
        upload_url = _text(upload.get("url"))
        if not upload_arn or not upload_url:
            raise DeviceFarmError("AWS Device Farm did not return a usable upload URL")

        timeout = httpx.Timeout(float(self.settings.DEVICE_FARM_UPLOAD_TIMEOUT_SECONDS), connect=30.0)
        try:
            with app_path.open("rb") as handle, httpx.Client(timeout=timeout) as http_client:
                response = http_client.put(
                    upload_url,
                    content=handle,
                    headers={"Content-Type": content_type},
                )
                response.raise_for_status()
        except (OSError, httpx.HTTPError) as exc:
            raise DeviceFarmError(f"AWS Device Farm app upload failed: {type(exc).__name__}") from exc

        self._wait_for_upload(client, upload_arn)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "sha256": sha256,
                    "app_arn": upload_arn,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return upload_arn

    def start_session(
        self,
        *,
        app_arn: str,
        device_name: str,
        platform_version: str | None,
        session_name: str,
    ) -> DeviceFarmSession:
        client = self._client()
        devices = self.list_android_devices()
        device = choose_device(
            devices,
            preferred_arn=_text(self.settings.DEVICE_FARM_DEVICE_ARN) or None,
            preferred_name=device_name or self.settings.DEVICE_FARM_DEVICE_NAME,
            platform_version=platform_version,
        )
        request_members = self._operation_input_members(client, "CreateRemoteAccessSession")
        configuration_members = self._configuration_members(client)
        configuration: dict[str, Any] = {}
        if "billingMethod" in configuration_members or not configuration_members:
            configuration["billingMethod"] = self.settings.DEVICE_FARM_BILLING_METHOD
        if "parameters" in configuration_members:
            configuration["parameters"] = {
                "appium:version": self.settings.DEVICE_FARM_APPIUM_VERSION,
            }
        request: dict[str, Any] = {
            "projectArn": self._project_arn(),
            "deviceArn": device.arn,
            "name": session_name[:256],
            "configuration": configuration,
        }
        if "appArn" in request_members:
            request["appArn"] = app_arn
        try:
            created = client.create_remote_access_session(**request)
        except Exception as exc:
            raise DeviceFarmError(f"AWS Device Farm could not start the Android session: {exc}") from exc

        session_payload = created.get("remoteAccessSession") or {}
        session_arn = _text(session_payload.get("arn"))
        if not session_arn:
            raise DeviceFarmError("AWS Device Farm did not return a remote session ARN")
        try:
            session = self._wait_for_session(client, session_arn, app_arn, device)
        except Exception:
            # A failed wait can happen before a DeviceFarmSession object exists,
            # so the caller's normal finally block cannot clean up this ARN.
            self.stop_session(session_arn)
            raise
        if "appArn" not in request_members:
            installer = getattr(client, "install_to_remote_access_session", None)
            if installer is None:
                self.stop_session(session_arn)
                raise DeviceFarmError(
                    "The installed AWS SDK cannot install an app into a remote access session"
                )
            try:
                installer(
                    remoteAccessSessionArn=session_arn,
                    appArn=app_arn,
                )
            except Exception as exc:
                self.stop_session(session_arn)
                raise DeviceFarmError(
                    f"AWS Device Farm could not install the uploaded app in the Android session: {exc}"
                ) from exc
        return session

    def _wait_for_session(
        self,
        client: Any,
        session_arn: str,
        app_arn: str,
        device: DeviceFarmDevice,
    ) -> DeviceFarmSession:
        deadline = time.monotonic() + self.settings.DEVICE_FARM_SESSION_TIMEOUT_SECONDS
        while True:
            response = client.get_remote_access_session(arn=session_arn)
            session = response.get("remoteAccessSession") or {}
            status = _text(session.get("status")).upper()
            endpoints = session.get("endpoints") or {}
            endpoint = _text(endpoints.get("remoteDriverEndpoint"))
            if status == "RUNNING" and endpoint:
                return DeviceFarmSession(
                    arn=session_arn,
                    app_arn=app_arn,
                    device=device,
                    appium_url=endpoint,
                )
            if status in {"ERRORED", "FAILED", "STOPPED", "STOPPING", "COMPLETED"}:
                result = _text(session.get("result")).upper()
                message = _text(session.get("message"))
                if result in {"PASSED", "WARNED"}:
                    message = (
                        "AWS Device Farm completed the setup lifecycle before exposing "
                        "an Appium endpoint"
                    )
                message = message or f"AWS Device Farm session ended with status {status}"
                raise DeviceFarmError(message[:500])
            if time.monotonic() >= deadline:
                raise DeviceFarmError("Timed out while AWS Device Farm started the Android session")
            time.sleep(self.settings.DEVICE_FARM_POLL_INTERVAL_SECONDS)

    def stop_session(self, session_arn: str) -> None:
        if not session_arn:
            return
        try:
            self._client().stop_remote_access_session(arn=session_arn)
        except Exception:
            # Cleanup is best effort. The caller already has the test outcome;
            # do not mask it with a provider cleanup error.
            return

