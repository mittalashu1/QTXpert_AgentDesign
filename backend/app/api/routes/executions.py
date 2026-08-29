"""Web and mobile execution, reporting, and embedded defect logging."""
import asyncio
import ipaddress
import logging
import tempfile
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urljoin, urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.execution import Defect, DefectStatus, ExecutionResult, ExecutionRun, ExecutionStatus, ResultStatus
from app.database.models.generation_run import GenerationRun
from app.database.models.project import Project
from app.database.models.requirement import Requirement
from app.database.models.test_case import TestCase
from app.database.models.user import User
from app.database.session import AsyncSessionLocal, get_db_session
from app.schemas.autopilot import AutopilotExecutionRequest
from app.schemas.execution import DashboardSummary, DefectCreate, DefectOut, ExecutionCreate, ExecutionRunOut
from app.services.autopilot import AutopilotPrototypeService
from app.services.upload_repository import UploadRepositoryService

router = APIRouter(tags=["execution"])
logger = logging.getLogger(__name__)


async def _owned_project(db: AsyncSession, project_id: UUID, user_id: UUID) -> Project:
    project = await db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _validated_target(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Execution target must be an HTTP(S) URL")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("Local execution targets are disabled")
    for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(item[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Private-network execution targets are disabled")
    return value


async def _validate_execution_target(
    db: AsyncSession,
    user: User,
    project_id: UUID,
    *,
    target_kind: str,
    provider: str,
    base_url: str | None,
    app_asset_id: UUID | None,
    device_name: str | None,
    platform_version: str | None,
    appium_url: str | None,
    appium_app: str | None,
    no_reset: bool,
    auto_grant_permissions: bool,
    settings: Settings,
) -> dict:
    """Validate and normalize a web or mobile execution target.

    The browser never supplies provider credentials. BrowserStack secrets stay
    in Render environment variables, while custom Appium endpoints are
    validated and stored without embedded credentials.
    """
    if target_kind == "web":
        if provider != "playwright":
            raise HTTPException(status_code=400, detail="Web execution uses the Playwright provider.")
        if not base_url:
            raise HTTPException(status_code=400, detail="An HTTP(S) application target URL is required for web execution.")
        try:
            validated_url = _validated_target(base_url)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "target_kind": "web",
            "provider": "playwright",
            "base_url": validated_url,
            "app_asset_id": None,
            "device_name": None,
            "platform_version": None,
            "appium_url": None,
            "appium_app": None,
            "target_metadata": {"target_kind": "web", "provider": "playwright"},
        }

    if target_kind not in {"android", "ios"}:
        raise HTTPException(status_code=400, detail="Target type must be web, android, or ios.")
    if provider not in {"browserstack", "appium"}:
        raise HTTPException(status_code=400, detail="Mobile execution uses BrowserStack or custom Appium.")
    if app_asset_id is None:
        raise HTTPException(status_code=400, detail="Select an APK or IPA from the project repository before running mobile tests.")
    asset = await UploadRepositoryService.get_owned(db, app_asset_id, user.id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(status_code=404, detail="The selected mobile app is not available in this project.")
    expected_extension = "apk" if target_kind == "android" else "ipa"
    # Older repository rows may not have had ``extension`` populated.  Keep
    # those assets reusable by deriving the type from the filename/category,
    # while still enforcing a strict APK-versus-IPA match.
    asset_extension = (asset.extension or Path(asset.filename).suffix.lstrip(".") or asset.category or "").lower()
    if asset_extension != expected_extension:
        raise HTTPException(status_code=400, detail=f"{target_kind.title()} execution requires a .{expected_extension} asset.")
    normalized_device = (device_name or "").strip()
    if not normalized_device:
        raise HTTPException(status_code=400, detail="A real-device or emulator name is required for mobile execution.")
    if provider == "browserstack" and not settings.browserstack_configured:
        raise HTTPException(
            status_code=409,
            detail="BrowserStack is not configured on the execution service. Add BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY or choose custom Appium.",
        )

    normalized_appium_url: str | None = None
    if provider == "appium":
        try:
            normalized_appium_url = AutopilotPrototypeService(settings).resolve_appium_url(
                AutopilotExecutionRequest(provider="appium", appium_url=appium_url, device_name=normalized_device)
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # A hosted Appium server cannot read a path on this Render container.
        # Require a remote app reference unless the endpoint is local to the
        # same process (local development keeps the convenient file path).
        parsed_endpoint = urlparse(normalized_appium_url)
        local_endpoint = parsed_endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        if settings.APP_ENV != "local" and not local_endpoint and not (appium_app or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Hosted custom Appium requires a reachable endpoint and a remote app reference; the Render filesystem is not visible to your device lab.",
            )
        if appium_app and (urlparse(appium_app).username or urlparse(appium_app).password):
            raise HTTPException(status_code=400, detail="Do not embed credentials in the remote app reference.")

    return {
        "target_kind": target_kind,
        "provider": provider,
        "base_url": None,
        "app_asset_id": asset.id,
        "device_name": normalized_device,
        "platform_version": (platform_version or "").strip() or None,
        "appium_url": normalized_appium_url,
        "appium_app": (appium_app or "").strip() or None,
        "target_metadata": {
            "target_kind": target_kind,
            "provider": provider,
            "asset_filename": asset.filename,
            "asset_sha256": asset.sha256,
            "device_name": normalized_device,
            "platform_version": (platform_version or "").strip() or None,
            "no_reset": bool(no_reset),
            "auto_grant_permissions": bool(auto_grant_permissions),
        },
    }


def _parse_mobile_locator(value: str) -> tuple[str, str]:
    """Parse ``strategy :: value`` while keeping plain labels accessible."""
    raw = value.strip()
    if " :: " in raw:
        strategy, locator = raw.split(" :: ", 1)
        strategy = strategy.strip().lower()
        if strategy not in {"accessibility_id", "id", "xpath"}:
            raise ValueError("Mobile locator strategy must be accessibility_id, id, or xpath.")
        if not locator.strip():
            raise ValueError("Mobile locator value cannot be empty.")
        return strategy, locator.strip()
    if not raw:
        raise ValueError("Mobile locator value cannot be empty.")
    return "accessibility_id", raw


def _compile_mobile_steps(steps: list) -> list[tuple[str, str | None, str | None]]:
    """Compile the explicit, safe mobile execution DSL.

    Generated prose is blocked instead of guessed. A Design case can become
    executable after its steps are converted to this small Appium DSL.
    """
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
            prefix = "tap " if lower.startswith("tap ") else "click "
            strategy, locator = _parse_mobile_locator(step[len(prefix):])
            compiled.append(("tap", strategy, locator))
            continue
        if lower.startswith("fill ") and " :: " in step:
            parts = [part.strip() for part in step[5:].split(" :: ")]
            if len(parts) == 3 and parts[0].lower() in {"accessibility_id", "id", "xpath"}:
                locator_strategy, locator, value = parts
            elif len(parts) == 2:
                locator_strategy, locator, value = "accessibility_id", parts[0], parts[1]
            else:
                raise ValueError("Mobile fill syntax is fill <locator> :: <value> or fill <strategy> :: <locator> :: <value>.")
            if not locator or not value:
                raise ValueError("Mobile fill value cannot be empty.")
            compiled.append(("fill", locator_strategy, f"{locator} :: {value}"))
            continue
        if lower.startswith("assert-text "):
            expected = step[12:].strip()
            if not expected:
                raise ValueError("Mobile assert-text value cannot be empty.")
            compiled.append(("assert-text", None, expected))
            continue
        if lower.startswith("assert-visible "):
            strategy, locator = _parse_mobile_locator(step[15:])
            compiled.append(("assert-visible", strategy, locator))
            continue
        raise ValueError(
            f"Unsupported mobile automation step: {step!r}. Convert it to launch, tap/click, "
            "fill <strategy> :: <value>, assert-text, assert-visible, or back."
        )
    return compiled


async def _upload_mobile_app_to_browserstack(
    path: Path,
    *,
    sha256: str,
    settings: Settings,
) -> str:
    """Upload one repository asset to BrowserStack without exposing secrets."""
    if not settings.browserstack_configured:
        raise RuntimeError("BrowserStack credentials are not configured on the execution service.")
    timeout = httpx.Timeout(
        float(settings.AUTOPILOT_BROWSERSTACK_UPLOAD_TIMEOUT_SECONDS),
        connect=30.0,
    )
    custom_id = f"qtxpert-execution-{sha256[:24]}"
    async with httpx.AsyncClient(
        auth=(settings.BROWSERSTACK_USERNAME or "", settings.BROWSERSTACK_ACCESS_KEY or ""),
        timeout=timeout,
    ) as client:
        with path.open("rb") as handle:
            response = await client.post(
                settings.BROWSERSTACK_UPLOAD_URL,
                files={"file": (path.name, handle, "application/octet-stream")},
                data={"custom_id": custom_id},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"BrowserStack app upload failed ({response.status_code}): {response.text[:500]}")
        payload = response.json()
    app_url = payload.get("app_url")
    if not app_url:
        raise RuntimeError("BrowserStack app upload did not return an app_url")
    return str(app_url)


def _mobile_capabilities(
    *,
    target_kind: str,
    device_name: str,
    platform_version: str | None,
    app_reference: str,
    no_reset: bool,
    auto_grant_permissions: bool,
    browserstack_options: dict | None,
    install_timeout_ms: int,
    server_launch_timeout_ms: int,
    adb_exec_timeout_ms: int,
) -> tuple[object, dict]:
    """Build Appium options for Android, iOS, BrowserStack and local labs."""
    from appium.options.android import UiAutomator2Options

    platform_name = "iOS" if target_kind == "ios" else "Android"
    automation_name = "XCUITest" if target_kind == "ios" else "UiAutomator2"
    capabilities: dict = {
        "platformName": platform_name,
        "appium:automationName": automation_name,
        "appium:deviceName": device_name,
        "appium:app": app_reference,
        "appium:noReset": no_reset,
        "appium:newCommandTimeout": 180,
    }
    if platform_version:
        capabilities["appium:platformVersion"] = platform_version
    if target_kind == "android":
        capabilities.update(
            {
                "appium:autoGrantPermissions": auto_grant_permissions,
                "appium:androidInstallTimeout": install_timeout_ms,
                "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
                "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
                "appium:adbExecTimeout": adb_exec_timeout_ms,
                "appium:appWaitDuration": adb_exec_timeout_ms,
            }
        )
        options = UiAutomator2Options().load_capabilities(capabilities)
    else:
        from appium.options.ios import XCUITestOptions

        capabilities["appium:wdaLaunchTimeout"] = server_launch_timeout_ms
        capabilities["appium:wdaConnectionTimeout"] = adb_exec_timeout_ms
        options = XCUITestOptions().load_capabilities(capabilities)
    if browserstack_options:
        capabilities["bstack:options"] = browserstack_options
        options = options.load_capabilities(capabilities)
    return options, capabilities


def _execute_mobile_sync(
    appium_url: str,
    app_reference: str,
    *,
    target_kind: str,
    provider: str,
    device_name: str,
    platform_version: str | None,
    no_reset: bool,
    auto_grant_permissions: bool,
    browserstack_options: dict | None,
    cases: list[dict],
    screenshot_path: Path,
    source_path: Path,
    install_timeout_ms: int,
    server_launch_timeout_ms: int,
    adb_exec_timeout_ms: int,
) -> dict:
    """Run explicit Appium DSL cases and return serializable evidence."""
    from appium import webdriver
    from appium.webdriver.common.appiumby import AppiumBy

    options, _ = _mobile_capabilities(
        target_kind=target_kind,
        device_name=device_name,
        platform_version=platform_version,
        app_reference=app_reference,
        no_reset=no_reset,
        auto_grant_permissions=auto_grant_permissions,
        browserstack_options=browserstack_options,
        install_timeout_ms=install_timeout_ms,
        server_launch_timeout_ms=server_launch_timeout_ms,
        adb_exec_timeout_ms=adb_exec_timeout_ms,
    )
    driver = webdriver.Remote(appium_url, options=options)
    try:
        time.sleep(3)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        driver.get_screenshot_as_file(str(screenshot_path))
        page_source = driver.page_source or ""
        source_path.write_text(page_source, encoding="utf-8")
        current_package = getattr(driver, "current_package", None)
        current_activity = getattr(driver, "current_activity", None)
        results: list[dict] = []
        locator_map = {
            "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
            "id": AppiumBy.ID,
            "xpath": AppiumBy.XPATH,
        }
        for case in cases:
            started = time.perf_counter()
            status_value = "passed"
            error: str | None = None
            evidence: dict = {
                "target_kind": target_kind,
                "provider": provider,
                "device_name": device_name,
                "platform_version": platform_version,
                "dsl_version": "mobile-1.0",
            }
            try:
                compiled = _compile_mobile_steps(case.get("steps") or [])
                for action, strategy, value in compiled:
                    if action == "back":
                        driver.back()
                    elif action == "tap":
                        driver.find_element(locator_map[strategy or "accessibility_id"], value or "").click()
                    elif action == "fill":
                        locator, text_value = (value or "").split(" :: ", 1)
                        driver.find_element(locator_map[strategy or "accessibility_id"], locator).send_keys(text_value)
                    elif action == "assert-text":
                        if (value or "").lower() not in (driver.page_source or "").lower():
                            raise AssertionError(f"Expected mobile UI text {value!r} was not present")
                    elif action == "assert-visible":
                        driver.find_element(locator_map[strategy or "accessibility_id"], value or "")
                evidence["current_package"] = getattr(driver, "current_package", None)
                evidence["current_activity"] = getattr(driver, "current_activity", None)
            except ValueError as exc:
                status_value = "blocked"
                error = str(exc)
            except Exception as exc:  # Appium element/driver errors are product evidence.
                status_value = "failed"
                error = str(exc)[:4000]
            results.append(
                {
                    "id": str(case["id"]),
                    "status": status_value,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "error_message": error,
                    "evidence": evidence,
                }
            )
        return {
            "results": results,
            "current_package": current_package,
            "current_activity": current_activity,
            "screenshot_path": str(screenshot_path) if screenshot_path.exists() else None,
            "page_source_path": str(source_path) if source_path.exists() else None,
        }
    finally:
        try:
            driver.quit()
        except Exception:
            logger.debug("Appium driver quit failed", exc_info=True)


async def _persist_execution_evidence(
    db: AsyncSession,
    run: ExecutionRun,
    settings: Settings,
    *,
    screenshot_path: Path | None,
    source_path: Path | None,
) -> dict[str, str]:
    """Persist mobile evidence as report-owned assets, hidden from Uploads."""
    persisted: dict[str, str] = {}
    for key, path, filename, content_type in (
        ("screenshot_asset_id", screenshot_path, f"execution-{run.id}-launch.png", "image/png"),
        ("page_source_asset_id", source_path, f"execution-{run.id}-page-source.xml", "application/xml"),
    ):
        if path is None or not path.is_file():
            continue
        try:
            asset = await UploadRepositoryService.create_from_path(
                db,
                path,
                run.requested_by_id,
                filename=filename,
                content_type=content_type,
                project_id=run.project_id,
                source_module="execution_report",
                category="execution_evidence",
                max_bytes=25 * 1024 * 1024,
                minimum_bytes=1,
                settings=settings,
            )
            persisted[key] = str(asset.id)
        except Exception:
            await db.rollback()
            logger.warning("Execution evidence persistence skipped for %s", path, exc_info=True)
    return persisted


async def _run_mobile_execution(run_id: UUID) -> None:
    """Execute a queued Android/iOS plan through BrowserStack or Appium."""
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        run = await db.scalar(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
                selectinload(ExecutionRun.execution_plan),
            )
            .where(ExecutionRun.id == run_id)
        )
        if run is None:
            return
        run.status = ExecutionStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        if run.execution_plan is not None:
            run.execution_plan.status = "running"
        await db.commit()
        workdir = Path(tempfile.mkdtemp(prefix="qtxpert-execution-"))
        screenshot_path = workdir / "launch.png"
        source_path = workdir / "page-source.xml"
        try:
            if run.app_asset_id is None:
                raise RuntimeError("The mobile execution has no APK/IPA asset reference.")
            app_path = workdir / ("application.ipa" if run.target_kind == "ios" else "application.apk")
            asset = await UploadRepositoryService.materialize(
                db,
                run.app_asset_id,
                run.requested_by_id,
                app_path,
                settings=settings,
            )
            app_reference = run.appium_app or str(app_path)
            browserstack_options = None
            appium_url = run.appium_url
            if run.provider == "browserstack":
                app_reference = await _upload_mobile_app_to_browserstack(
                    app_path,
                    sha256=asset.sha256,
                    settings=settings,
                )
                appium_url = settings.BROWSERSTACK_HUB_URL
                browserstack_options = {
                    "userName": settings.BROWSERSTACK_USERNAME,
                    "accessKey": settings.BROWSERSTACK_ACCESS_KEY,
                    "projectName": settings.BROWSERSTACK_PROJECT_NAME,
                    "buildName": f"QTXpert {run.target_kind.title()} execution",
                    "sessionName": run.name[:100],
                    "debug": True,
                    "networkLogs": True,
                }
            if not appium_url:
                raise RuntimeError("No Appium endpoint is available for this execution.")
            cases = [
                {
                    "id": str(result.id),
                    "steps": (
                        result.execution_plan_case.steps
                        if result.execution_plan_case is not None
                        else result.test_case.steps
                    ),
                }
                for result in run.results
                if result.status == ResultStatus.PENDING
            ]
            driver_result = await asyncio.wait_for(
                asyncio.to_thread(
                    _execute_mobile_sync,
                    appium_url,
                    app_reference,
                    target_kind=run.target_kind,
                    provider=run.provider,
                    device_name=run.device_name or "Configured device",
                    platform_version=run.platform_version,
                    no_reset=bool((run.target_metadata or {}).get("no_reset", False)),
                    auto_grant_permissions=bool((run.target_metadata or {}).get("auto_grant_permissions", True)),
                    browserstack_options=browserstack_options,
                    cases=cases,
                    screenshot_path=screenshot_path,
                    source_path=source_path,
                    install_timeout_ms=settings.AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS * 1000,
                    server_launch_timeout_ms=settings.AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS * 1000,
                    adb_exec_timeout_ms=settings.AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS * 1000,
                ),
                timeout=settings.AUTOPILOT_SMOKE_TIMEOUT_SECONDS,
            )
            evidence_ids = await _persist_execution_evidence(
                db,
                run,
                settings,
                screenshot_path=screenshot_path,
                source_path=source_path,
            )
            result_map = {item["id"]: item for item in driver_result.get("results", [])}
            for result in run.results:
                update = result_map.get(str(result.id))
                if update is None:
                    continue
                result.status = ResultStatus(update["status"])
                result.duration_ms = update.get("duration_ms")
                result.error_message = update.get("error_message")
                result.evidence = {
                    **(update.get("evidence") or {}),
                    **evidence_ids,
                    "current_package": driver_result.get("current_package"),
                    "current_activity": driver_result.get("current_activity"),
                }
            run.target_metadata = {
                **(run.target_metadata or {}),
                "asset_filename": asset.filename,
                "asset_sha256": asset.sha256,
                "screenshot_asset_id": evidence_ids.get("screenshot_asset_id"),
                "page_source_asset_id": evidence_ids.get("page_source_asset_id"),
            }
            run.passed_tests = sum(item.status == ResultStatus.PASSED for item in run.results)
            run.failed_tests = sum(item.status == ResultStatus.FAILED for item in run.results)
            run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
            run.status = ExecutionStatus.COMPLETED
        except Exception as exc:
            run.status = ExecutionStatus.FAILED
            message = f"Mobile execution worker unavailable: {str(exc)[:2000]}"
            for result in run.results:
                if result.status == ResultStatus.PENDING:
                    result.status = ResultStatus.BLOCKED
                    result.error_message = message
                    result.evidence = {
                        "target_kind": run.target_kind,
                        "provider": run.provider,
                        "device_name": run.device_name,
                    }
            run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
            logger.warning("Mobile execution %s failed: %s", run_id, exc, exc_info=True)
        finally:
            run.completed_at = datetime.now(timezone.utc)
            if run.execution_plan is not None:
                run.execution_plan.status = "completed" if run.status == ExecutionStatus.COMPLETED else "failed"
            await db.commit()
            try:
                import shutil

                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                logger.debug("Mobile execution temporary directory cleanup failed", exc_info=True)


def _compile_steps(steps: list, base_url: str) -> list[tuple[str, str, str | None]]:
    """Compile the deliberately small M4 DSL. Unknown prose is blocked, never guessed."""
    compiled: list[tuple[str, str, str | None]] = [("navigate", base_url, None)]
    for raw in steps:
        step = str(raw).strip()
        lower = step.lower()
        if lower.startswith("navigate "):
            compiled.append(("navigate", urljoin(base_url, step[9:].strip()), None))
        elif lower.startswith("click "):
            compiled.append(("click", step[6:].strip(), None))
        elif lower.startswith("fill ") and " :: " in step:
            locator, value = step[5:].split(" :: ", 1)
            compiled.append(("fill", locator.strip(), value))
        elif lower.startswith("assert-text "):
            compiled.append(("assert-text", step[12:].strip(), None))
        elif lower.startswith("assert-url "):
            compiled.append(("assert-url", step[11:].strip(), None))
        else:
            raise ValueError(
                f"Unsupported automation step: {step!r}. Convert it to navigate, click, "
                "fill <locator> :: <value>, assert-text, or assert-url."
            )
    return compiled


async def _run_execution(run_id: UUID) -> None:
    # Keep the existing Playwright path fast and isolated while dispatching
    # mobile plans to the Appium/BrowserStack adapter.
    async with AsyncSessionLocal() as probe:
        target_kind = await probe.scalar(select(ExecutionRun.target_kind).where(ExecutionRun.id == run_id))
    if target_kind and target_kind != "web":
        await _run_mobile_execution(run_id)
        return
    async with AsyncSessionLocal() as db:
        run = await db.scalar(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
                selectinload(ExecutionRun.execution_plan),
            )
            .where(ExecutionRun.id == run_id)
        )
        if run is None:
            return
        run.status = ExecutionStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        if run.execution_plan is not None:
            run.execution_plan.status = "running"
        await db.commit()
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as manager:
                browser_type = getattr(manager, run.browser)
                browser = await browser_type.launch(headless=True)
                context = await browser.new_context(ignore_https_errors=False)
                for result in run.results:
                    if result.status != ResultStatus.PENDING:
                        continue
                    started = time.perf_counter()
                    try:
                        source_steps = (
                            result.execution_plan_case.steps
                            if result.execution_plan_case is not None
                            else result.test_case.steps
                        )
                        steps = _compile_steps(source_steps or [], run.base_url or "")
                    except ValueError as exc:
                        result.status = ResultStatus.BLOCKED
                        result.error_message = str(exc)
                        result.duration_ms = 0
                        continue
                    page = await context.new_page()
                    try:
                        for action, target, value in steps:
                            if action == "navigate":
                                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                            elif action == "click":
                                await page.locator(target).click(timeout=10_000)
                            elif action == "fill":
                                await page.locator(target).fill(value or "", timeout=10_000)
                            elif action == "assert-text":
                                await page.get_by_text(target, exact=False).wait_for(state="visible", timeout=10_000)
                            elif action == "assert-url" and target not in page.url:
                                raise AssertionError(f"Expected URL to contain {target!r}, got {page.url!r}")
                        result.status = ResultStatus.PASSED
                        result.evidence = {"final_url": page.url, "title": await page.title(), "dsl_version": "1.0"}
                    except Exception as exc:
                        result.status = ResultStatus.FAILED
                        result.error_message = str(exc)[:4000]
                        result.evidence = {"final_url": page.url, "dsl_version": "1.0"}
                    finally:
                        result.duration_ms = int((time.perf_counter() - started) * 1000)
                        await page.close()
                await browser.close()
            run.passed_tests = sum(x.status == ResultStatus.PASSED for x in run.results)
            run.failed_tests = sum(x.status == ResultStatus.FAILED for x in run.results)
            run.blocked_tests = sum(x.status == ResultStatus.BLOCKED for x in run.results)
            run.status = ExecutionStatus.COMPLETED
        except Exception as exc:
            run.status = ExecutionStatus.FAILED
            for result in run.results:
                if result.status == ResultStatus.PENDING:
                    result.status = ResultStatus.BLOCKED
                    result.error_message = f"Execution worker unavailable: {str(exc)[:1000]}"
            run.blocked_tests = sum(x.status == ResultStatus.BLOCKED for x in run.results)
        finally:
            run.completed_at = datetime.now(timezone.utc)
            if run.execution_plan is not None:
                run.execution_plan.status = "completed" if run.status == ExecutionStatus.COMPLETED else "failed"
            await db.commit()


@router.post("/executions", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def create_execution(
    payload: ExecutionCreate,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await _owned_project(db, payload.project_id, user.id)
    target = await _validate_execution_target(
        db,
        user,
        payload.project_id,
        target_kind=payload.target_kind,
        provider=payload.provider,
        base_url=str(payload.base_url) if payload.base_url else None,
        app_asset_id=payload.app_asset_id,
        device_name=payload.device_name,
        platform_version=payload.platform_version,
        appium_url=payload.appium_url,
        appium_app=payload.appium_app,
        no_reset=payload.no_reset,
        auto_grant_permissions=payload.auto_grant_permissions,
        settings=settings,
    )
    cases = (await db.scalars(
        select(TestCase).join(GenerationRun).where(
            GenerationRun.project_id == payload.project_id,
            TestCase.id.in_(payload.test_case_ids),
            TestCase.is_automation_candidate.is_(True),
        )
    )).unique().all()
    if len(cases) != len(set(payload.test_case_ids)):
        raise HTTPException(status_code=400, detail="One or more test cases are unavailable or not automation candidates")
    run = ExecutionRun(
        project_id=payload.project_id,
        requested_by_id=user.id,
        name=payload.name,
        base_url=target["base_url"],
        browser=payload.browser if target["target_kind"] == "web" else target["provider"],
        target_kind=target["target_kind"],
        provider=target["provider"],
        app_asset_id=target["app_asset_id"],
        device_name=target["device_name"],
        platform_version=target["platform_version"],
        appium_url=target["appium_url"],
        appium_app=target["appium_app"],
        target_metadata=target["target_metadata"],
        total_tests=len(cases),
    )
    db.add(run)
    await db.flush()
    for case in cases:
        db.add(ExecutionResult(execution_run_id=run.id, test_case_id=case.id))
    await db.commit()
    run = await db.scalar(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.id == run.id))
    background.add_task(_run_execution, run.id)
    return run


@router.get("/executions", response_model=list[ExecutionRunOut])
async def list_executions(project_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    await _owned_project(db, project_id, user.id)
    return (await db.scalars(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc()).limit(50))).unique().all()


@router.get("/executions/{run_id}", response_model=ExecutionRunOut)
async def get_execution(run_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    run = await db.scalar(select(ExecutionRun).join(Project).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.id == run_id, Project.owner_id == user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Execution run not found")
    return run


@router.post("/execution-results/{result_id}/defects", response_model=DefectOut, status_code=status.HTTP_201_CREATED)
async def create_defect(result_id: UUID, payload: DefectCreate, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    result = await db.scalar(select(ExecutionResult).join(ExecutionRun).join(Project).where(ExecutionResult.id == result_id, Project.owner_id == user.id))
    if result is None:
        raise HTTPException(status_code=404, detail="Execution result not found")
    if result.status != ResultStatus.FAILED:
        raise HTTPException(status_code=400, detail="Defects can only be logged from failed execution results")
    sequence = (await db.scalar(select(func.count(Defect.id)))) or 0
    defect = Defect(execution_result_id=result.id, defect_key=f"QTX-{sequence + 1:05d}", title=payload.title, description=payload.description, severity=payload.severity, logged_by_id=user.id)
    db.add(defect)
    await db.commit()
    await db.refresh(defect)
    return defect


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(project_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    await _owned_project(db, project_id, user.id)
    requirements = await db.scalar(select(func.count(Requirement.id)).where(Requirement.project_id == project_id)) or 0
    test_cases = await db.scalar(select(func.count(TestCase.id)).join(GenerationRun).where(GenerationRun.project_id == project_id)) or 0
    automation = await db.scalar(select(func.count(TestCase.id)).join(GenerationRun).where(GenerationRun.project_id == project_id, TestCase.is_automation_candidate.is_(True))) or 0
    run_count = await db.scalar(select(func.count(ExecutionRun.id)).where(ExecutionRun.project_id == project_id)) or 0
    passed = await db.scalar(select(func.coalesce(func.sum(ExecutionRun.passed_tests), 0)).where(ExecutionRun.project_id == project_id)) or 0
    failed = await db.scalar(select(func.coalesce(func.sum(ExecutionRun.failed_tests), 0)).where(ExecutionRun.project_id == project_id)) or 0
    open_defects = await db.scalar(select(func.count(Defect.id)).join(ExecutionResult).join(ExecutionRun).where(ExecutionRun.project_id == project_id, Defect.status.in_([DefectStatus.OPEN, DefectStatus.IN_PROGRESS]))) or 0
    recent = (await db.scalars(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc()).limit(5))).unique().all()
    denominator = int(passed) + int(failed)
    return DashboardSummary(requirements=requirements, test_cases=test_cases, execution_runs=run_count, pass_rate=round(int(passed) * 100 / denominator, 1) if denominator else 0, open_defects=open_defects, automation_candidates=automation, recent_runs=recent)


