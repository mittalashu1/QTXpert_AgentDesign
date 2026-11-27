"""Appium transport for an isolated APK on a project-paired Android runner."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from concurrent.futures import TimeoutError as ThreadTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database.models.local_runner import LocalAutopilotSession, LocalDeviceRunner, LocalRunnerJob
from app.database.models.uploaded_asset import UploadedAsset
from app.database.session import AsyncSessionLocal
from app.services.appium_compat import AndroidDeviceDisconnected
from app.services.autopilot_input_store import _fernet

BOOT_TIMEOUT = 400
COMMAND_TIMEOUT = 75
LEASE_IDLE_SECONDS = 190
APK_SERIAL = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
PACKAGE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


logger = logging.getLogger(__name__)


class LocalDeviceUnavailable(AndroidDeviceDisconnected):
    pass


@dataclass(frozen=True)
class LocalAndroidTarget:
    runner_id: UUID
    owner_id: UUID
    project_id: UUID
    asset_id: UUID
    device_name: str
    package_name: str
    sha256: str


def now() -> datetime:
    return datetime.now(timezone.utc)


def pack(settings: Settings, value: dict) -> str:
    return _fernet(settings).encrypt(json.dumps(value).encode()).decode("ascii")


def unpack(settings: Settings, value: str) -> dict:
    return json.loads(_fernet(settings).decrypt(value.encode("ascii")))


class LocalAutopilotTransport:
    def __init__(self, settings: Settings, target: LocalAndroidTarget):
        self.settings = settings
        self.target = target
        self.session_id = uuid4()
        self.loop = asyncio.get_running_loop()

    @classmethod
    async def open(cls, settings: Settings, target: LocalAndroidTarget) -> LocalAutopilotTransport:
        if not APK_SERIAL.fullmatch(target.device_name) or not PACKAGE_NAME.fullmatch(target.package_name):
            raise LocalDeviceUnavailable("Select an Android device and an APK with a verified package identity.")
        transport = cls(settings, target)
        # Detect unavailable encryption before reserving a device.
        _fernet(settings)
        async with AsyncSessionLocal() as db:
            runner = await db.scalar(
                select(LocalDeviceRunner).where(
                    LocalDeviceRunner.id == target.runner_id,
                    LocalDeviceRunner.owner_id == target.owner_id,
                    LocalDeviceRunner.project_id == target.project_id,
                    LocalDeviceRunner.status == "active",
                ).with_for_update()
            )
            if (
                runner is None or not runner.last_seen_at
                or runner.last_seen_at < now() - timedelta(seconds=75)
                or not runner.capabilities.get("autopilot_android")
                or target.device_name not in runner.capabilities.get("devices", [])
            ):
                raise LocalDeviceUnavailable("The selected Android device is offline. Start the updated paired runner and reconnect the device.")
            artifact = await db.scalar(select(UploadedAsset.id).where(
                UploadedAsset.id == target.asset_id,
                UploadedAsset.owner_id == target.owner_id,
                UploadedAsset.project_id == target.project_id,
                UploadedAsset.extension == "apk",
                UploadedAsset.status == "ready",
                UploadedAsset.sha256 == target.sha256,
            ))
            if artifact is None:
                raise LocalDeviceUnavailable("The APK no longer matches the analyzed build in this project's repository.")
            busy = await db.scalar(select(LocalRunnerJob.execution_run_id).where(
                LocalRunnerJob.runner_id == runner.id,
                LocalRunnerJob.status == "leased",
                LocalRunnerJob.lease_expires_at > now(),
            ).limit(1))
            reservation = await db.get(LocalAutopilotSession, runner.id, with_for_update=True)
            if busy or (reservation and reservation.expires_at > now()):
                raise LocalDeviceUnavailable("The selected runner is executing another job. Retry when it is available.")
            if reservation is None:
                reservation = LocalAutopilotSession(runner_id=runner.id)
                db.add(reservation)
            reservation.session_id = transport.session_id
            reservation.asset_id = target.asset_id
            reservation.device_name = target.device_name
            reservation.package_name = target.package_name
            reservation.expires_at = now() + timedelta(seconds=BOOT_TIMEOUT + 10)
            reservation.worker_id = None
            reservation.command_id = None
            reservation.command_delivered = False
            reservation.command_payload = None
            reservation.command_answer = None
            await db.commit()
        return transport

    async def close(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                current = await db.get(LocalAutopilotSession, self.target.runner_id, with_for_update=True)
                if current and current.session_id == self.session_id:
                    await db.delete(current)
                    await db.commit()
        except SQLAlchemyError:
            logger.warning("The local Android reservation could not close immediately and will expire.")

    async def _exchange(self, command: str, params: dict) -> dict:
        command_id = uuid4()
        timeout = BOOT_TIMEOUT if command == "newSession" else COMMAND_TIMEOUT
        async with AsyncSessionLocal() as db:
            session = await db.get(LocalAutopilotSession, self.target.runner_id, with_for_update=True)
            if not session or session.session_id != self.session_id or session.expires_at <= now():
                raise LocalDeviceUnavailable("The paired Android session ended. Reconnect the device and continue discovery.")
            if session.command_id is not None:
                raise LocalDeviceUnavailable("The previous Android command did not complete.")
            session.command_id = command_id
            session.command_delivered = False
            session.command_payload = pack(self.settings, {"name": command, "params": params})
            session.expires_at = now() + timedelta(seconds=max(timeout + 10, LEASE_IDLE_SECONDS))
            await db.commit()
        deadline = self.loop.time() + timeout
        while self.loop.time() < deadline:
            await asyncio.sleep(0.35)
            async with AsyncSessionLocal() as db:
                session = await db.get(LocalAutopilotSession, self.target.runner_id)
                if not session or session.session_id != self.session_id:
                    raise LocalDeviceUnavailable("The paired runner session was closed.")
                if session.command_id == command_id and session.command_answer is not None:
                    answer = unpack(self.settings, session.command_answer)
                    session.command_id = None
                    session.command_answer = None
                    await db.commit()
                    if "interrupted" in answer:
                        raise LocalDeviceUnavailable(str(answer["interrupted"]))
                    return answer
        raise LocalDeviceUnavailable("The paired runner did not answer the Android command. Check the device and continue discovery.")

    def connection(self):
        from appium.webdriver.appium_connection import AppiumConnection
        from appium.webdriver.client_config import AppiumClientConfig

        transport = self

        class RelayConnection(AppiumConnection):
            def execute(self, command, params):
                timeout = BOOT_TIMEOUT if command == "newSession" else COMMAND_TIMEOUT
                future = asyncio.run_coroutine_threadsafe(
                    transport._exchange(command, params or {}), transport.loop
                )
                try:
                    response = future.result(timeout=timeout + 5)
                except ThreadTimeout as exc:
                    future.cancel()
                    raise LocalDeviceUnavailable("The Android runner command timed out.") from exc
                if response.get("status"):
                    # Appium's Python client unwraps the value returned by its
                    # HTTP executor before reading the W3C error payload. Keep
                    # the same shape so missing locators raise typed exceptions
                    # and the caller can try other observed locators.
                    error = str(response["status"])
                    details = response.get("value")
                    message = details.get("message") if isinstance(details, dict) else None
                    return {"value": {"value": {
                        "error": error,
                        "message": message or error,
                    }}}
                return response

        return RelayConnection(client_config=AppiumClientConfig(
            remote_server_addr="http://127.0.0.1",
        ))
