"""Android-first autonomous mobile QA prototype service.

The prototype separates deterministic binary/runtime analysis from LLM enrichment.
If the configured LLM is unavailable, QTXpert still returns a useful test plan.
Real-device smoke execution can use BrowserStack App Automate when credentials are
configured, while a generic Appium endpoint remains available for local/private labs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database.models.autopilot_job import AutopilotJob
from app.database.session import AsyncSessionLocal
from app.llm.base import LLMMessage
from app.llm.factory import get_llm_provider
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotExecutionRequest,
    AutopilotExecutionResult,
    AutopilotJobStatus,
    AutopilotTest,
)

logger = logging.getLogger(__name__)
_MISSING = object()


class AutopilotUploadTooLarge(ValueError):
    """Raised when an Autopilot upload exceeds the configured byte limit."""


class AutopilotUploadInvalid(ValueError):
    """Raised when an Autopilot upload is empty or otherwise unusable."""


_DANGEROUS_PERMISSION_HINTS = {
    "android.permission.CAMERA": ("Camera", "Validate camera permission grant/deny and recovery flows."),
    "android.permission.ACCESS_FINE_LOCATION": ("Location", "Validate precise-location permission, denial and degraded behavior."),
    "android.permission.ACCESS_COARSE_LOCATION": ("Location", "Validate approximate-location behavior and fallback."),
    "android.permission.RECORD_AUDIO": ("Microphone", "Validate microphone permission grant/deny behavior."),
    "android.permission.READ_CONTACTS": ("Contacts", "Validate contacts permission and privacy-safe fallback."),
    "android.permission.POST_NOTIFICATIONS": ("Notifications", "Validate notification permission and notification-dependent journeys."),
    "android.permission.READ_MEDIA_IMAGES": ("Media", "Validate media selection permission and denied-state UX."),
}


class AutopilotPrototypeService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = Path(settings.AUTOPILOT_STORAGE_PATH).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._persistence_disabled_until = 0.0

    @property
    def _durable_results_enabled(self) -> bool:
        """Use the database for deployed jobs while keeping local tests local.

        Render services normally set ``APP_ENV=production``. The connection
        string check is an additional safeguard for an existing service whose
        environment was created before that variable was added: a non-local
        database should still get durable Autopilot results.
        """
        if getattr(self.settings, "AUTOPILOT_DEGRADED_MODE_ENABLED", False):
            return False
        if not getattr(self.settings, "AUTOPILOT_DB_PERSISTENCE_ENABLED", True):
            return False
        if self.settings.APP_ENV != "local":
            return True
        database_url = str(getattr(self.settings, "POSTGRES_URL", "")).lower()
        return not any(host in database_url for host in ("localhost", "127.0.0.1", "postgres:5432"))

    async def _persist_job(self, job: Dict[str, Any], analysis: Any = _MISSING) -> None:
        """Best-effort durable write; filesystem operation must never fail on DB hiccups."""
        if not self._durable_results_enabled or time.monotonic() < self._persistence_disabled_until:
            return
        try:
            owner_id = uuid.UUID(str(job["owner_id"]))
            created_at = datetime.fromisoformat(str(job["created_at"]).replace("Z", "+00:00"))
            async with AsyncSessionLocal() as session:
                record = await session.scalar(
                    select(AutopilotJob).where(AutopilotJob.job_id == str(job["job_id"]))
                )
                if record is None:
                    record = AutopilotJob(
                        job_id=str(job["job_id"]),
                        owner_id=owner_id,
                        filename=str(job.get("filename", "application.apk")),
                        created_at=created_at,
                    )
                    session.add(record)
                record.filename = str(job.get("filename", record.filename))
                record.owner_id = owner_id
                repository_asset_id = job.get("repository_asset_id")
                record.repository_asset_id = (
                    uuid.UUID(str(repository_asset_id)) if repository_asset_id else None
                )
                record.context = str(job.get("context", ""))[:8000]
                record.apk_path = job.get("apk_path")
                record.status = str(job.get("status", "uploaded"))
                record.stage = str(job.get("stage", "queued"))
                record.progress = int(job.get("progress", 0))
                record.error = job.get("error")
                if analysis is not _MISSING:
                    record.analysis = analysis
                await session.commit()
        except Exception as exc:  # pragma: no cover - exercised by unavailable production DBs
            # Do not turn a healthy APK analysis into a failed job just because
            # the optional result store is temporarily unavailable. Avoid
            # repeatedly waiting on a broken connection for the next minute.
            self._persistence_disabled_until = time.monotonic() + 60
            logger.warning("Autopilot durable result write skipped: %s", exc)

    async def _load_job_from_db(self, job_id: str) -> Dict[str, Any] | None:
        if not self._durable_results_enabled or time.monotonic() < self._persistence_disabled_until:
            return None
        try:
            async with AsyncSessionLocal() as session:
                record = await session.scalar(
                    select(AutopilotJob).where(AutopilotJob.job_id == job_id)
                )
                if record is None:
                    return None
                result: Dict[str, Any] = {
                    "job_id": record.job_id,
                    "owner_id": str(record.owner_id),
                    "repository_asset_id": str(record.repository_asset_id)
                    if record.repository_asset_id
                    else None,
                    "filename": record.filename,
                    "context": record.context or "",
                    "apk_path": record.apk_path,
                    "status": record.status,
                    "stage": record.stage,
                    "progress": record.progress,
                    "error": record.error,
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat(),
                }
                if record.analysis is not None:
                    result["analysis"] = record.analysis
                return result
        except Exception as exc:  # pragma: no cover - exercised by unavailable production DBs
            self._persistence_disabled_until = time.monotonic() + 60
            logger.warning("Autopilot durable result read skipped: %s", exc)
            return None

    async def _latest_job_id_from_db(self, owner_id: str) -> str | None:
        if not self._durable_results_enabled or time.monotonic() < self._persistence_disabled_until:
            return None
        try:
            async with AsyncSessionLocal() as session:
                record = await session.scalar(
                    select(AutopilotJob)
                    .where(AutopilotJob.owner_id == uuid.UUID(str(owner_id)))
                    .order_by(AutopilotJob.created_at.desc())
                    .limit(1)
                )
                return record.job_id if record else None
        except Exception as exc:  # pragma: no cover - exercised by unavailable production DBs
            self._persistence_disabled_until = time.monotonic() + 60
            logger.warning("Autopilot durable latest-job read skipped: %s", exc)
            return None

    def _job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", job_id):
            raise ValueError("Invalid Autopilot job id")
        return self.root / job_id

    def _metadata_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "analysis.json"

    def _execution_dir(self, job_id: str) -> Path:
        """Return the per-job execution directory used as a local fallback."""
        return self._job_dir(job_id) / "executions"

    async def _persist_execution_file(
        self,
        result: AutopilotExecutionResult,
        request: AutopilotExecutionRequest,
    ) -> None:
        """Keep a local copy when the database is unavailable.

        Production requests are additionally persisted in PostgreSQL by the
        API route. The file fallback is intentionally one JSON file per run so
        repeated smoke attempts never overwrite one another.
        """
        try:
            execution_dir = self._execution_dir(result.job_id)
            await asyncio.to_thread(execution_dir.mkdir, parents=True, exist_ok=True)
            payload = {
                "execution_id": str(result.execution_id),
                "request": request.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            }
            path = execution_dir / f"{result.execution_id}.json"
            await asyncio.to_thread(path.write_text, json.dumps(payload, indent=2), "utf-8")
        except Exception as exc:  # pragma: no cover - defensive local fallback
            logger.warning("Autopilot execution file write skipped: %s", exc)

    async def list_execution_files(self, job_id: str) -> list[dict[str, Any]]:
        """Read filesystem fallback execution records in newest-first order."""
        directory = self._execution_dir(job_id)
        if not directory.exists():
            return []

        def read_all() -> list[dict[str, Any]]:
            records: list[dict[str, Any]] = []
            for path in directory.glob("*.json"):
                try:
                    payload = json.loads(path.read_text("utf-8"))
                    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
                        records.append(payload)
                except (OSError, ValueError):
                    continue
            records.sort(
                key=lambda item: str(item.get("result", {}).get("started_at", "")),
                reverse=True,
            )
            return records

        return await asyncio.to_thread(read_all)

    async def save_upload(self, filename: str, data: bytes, owner_id: str, context: str = "") -> tuple[str, Path]:
        job_id = str(uuid4())
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        safe_name = Path(filename).name or "application.apk"
        apk_path = job_dir / safe_name
        await asyncio.to_thread(apk_path.write_bytes, data)
        seed = {
            "job_id": job_id,
            "owner_id": owner_id,
            "filename": safe_name,
            "context": context[:8000],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "apk_path": str(apk_path),
            "status": "uploaded",
            "stage": "queued",
            "progress": 5,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.to_thread((job_dir / "job.json").write_text, json.dumps(seed, indent=2), "utf-8")
        await self._persist_job(seed)
        return job_id, apk_path

    async def save_upload_stream(
        self,
        filename: str,
        upload: Any,
        owner_id: str,
        context: str = "",
        max_bytes: int = 0,
    ) -> tuple[str, Path]:
        """Persist an UploadFile incrementally instead of duplicating it in memory.

        Starlette already spools large multipart bodies to a temporary file, so
        reading one bounded chunk at a time and writing directly to the job file
        keeps the process memory stable even for the 250 MB prototype limit.
        """
        job_id = str(uuid4())
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        safe_name = Path(filename).name or "application.apk"
        apk_path = job_dir / safe_name
        total = 0
        handle = None
        try:
            handle = await asyncio.to_thread(apk_path.open, "wb")
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise AutopilotUploadTooLarge(
                        f"APK exceeds the {max_bytes // (1024 * 1024)}MB Autopilot prototype limit"
                    )
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            if total < 1024:
                raise AutopilotUploadInvalid("APK file is empty or invalid")
            seed = {
                "job_id": job_id,
                "owner_id": owner_id,
                "filename": safe_name,
                "context": context[:8000],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "apk_path": str(apk_path),
                "status": "uploaded",
                "stage": "queued",
                "progress": 5,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await asyncio.to_thread((job_dir / "job.json").write_text, json.dumps(seed, indent=2), "utf-8")
            await self._persist_job(seed)
            return job_id, apk_path
        except Exception:
            if handle is not None:
                await asyncio.to_thread(handle.close)
                handle = None
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)
            raise
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)

    async def update_job(self, job_id: str, **changes: Any) -> Dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        job = await self.load_job(job_id)
        job.update(changes)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if path.parent.exists():
            temporary = path.with_suffix(".tmp")
            await asyncio.to_thread(temporary.write_text, json.dumps(job, indent=2), "utf-8")
            await asyncio.to_thread(temporary.replace, path)
        await self._persist_job(job)
        return job

    async def get_job_status(self, job_id: str) -> AutopilotJobStatus:
        job = await self.load_job(job_id)
        analysis = None
        if job.get("status") == "analyzed":
            try:
                analysis = await self.load_analysis(job_id)
            except FileNotFoundError:
                await self.update_job(job_id, status="failed", stage="failed", error="Analysis result is missing")
                job = await self.load_job(job_id)
        elif job.get("status") in {"uploaded", "analyzing"}:
            # A Render deploy replaces the container filesystem. Do not leave a
            # durable in-flight job polling forever when its APK is gone.
            apk_path = job.get("apk_path")
            if not apk_path or not Path(apk_path).is_file():
                await self.update_job(
                    job_id,
                    status="failed",
                    stage="failed",
                    progress=100,
                    error="The uploaded APK is no longer available after a service restart. Please upload it again.",
                )
                job = await self.load_job(job_id)
        artifact_path = job.get("apk_path")
        return AutopilotJobStatus(
            job_id=job_id,
            filename=job["filename"],
            status=job.get("status", "uploaded"),
            stage=job.get("stage", "queued"),
            progress=int(job.get("progress", 0)),
            created_at=job["created_at"],
            updated_at=job.get("updated_at", job["created_at"]),
            context=str(job.get("context", "")),
            artifact_available=bool(artifact_path and Path(artifact_path).is_file()),
            error=job.get("error"),
            analysis=analysis,
        )

    async def get_latest_job_status(self, owner_id: str) -> AutopilotJobStatus | None:
        """Return the newest job owned by a user, if one has been uploaded."""
        # Prefer the database in deployed environments. This is what makes a
        # completed result survive a Render deploy; the local scan remains a
        # fast path for development and for the APK artifact itself.
        job_id = await self._latest_job_id_from_db(owner_id)
        if not job_id:
            job_id = await asyncio.to_thread(self._latest_job_id_sync, owner_id)
        if not job_id:
            return None
        return await self.get_job_status(job_id)

    def _latest_job_id_sync(self, owner_id: str) -> str | None:
        latest: tuple[str, str] | None = None
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return None
        for job_dir in entries:
            if not job_dir.is_dir():
                continue
            try:
                job = json.loads((job_dir / "job.json").read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if str(job.get("owner_id")) != owner_id or not job.get("job_id"):
                continue
            created_at = str(job.get("created_at", ""))
            if latest is None or created_at > latest[0]:
                latest = (created_at, str(job["job_id"]))
        return latest[1] if latest else None

    async def analyze_safely(self, job_id: str) -> None:
        started = time.perf_counter()
        try:
            await self.update_job(job_id, status="analyzing", stage="reading_apk", progress=15, error=None)
            await asyncio.wait_for(self.analyze(job_id), timeout=900)
            await self.update_job(job_id, status="analyzed", stage="complete", progress=100)
            logger.info("Autopilot analysis completed job_id=%s duration_seconds=%.2f", job_id, time.perf_counter() - started)
        except Exception as exc:
            logger.exception("Autopilot analysis failed job_id=%s", job_id)
            await self.update_job(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )

    async def load_job(self, job_id: str) -> Dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if path.exists():
            return json.loads(await asyncio.to_thread(path.read_text, "utf-8"))
        durable = await self._load_job_from_db(job_id)
        if durable is None:
            raise FileNotFoundError(job_id)
        return durable

    async def load_analysis(self, job_id: str) -> AutopilotAnalysis:
        path = self._metadata_path(job_id)
        if path.exists():
            return AutopilotAnalysis.model_validate_json(await asyncio.to_thread(path.read_text, "utf-8"))
        durable = await self._load_job_from_db(job_id)
        if not durable or durable.get("analysis") is None:
            raise FileNotFoundError(job_id)
        return AutopilotAnalysis.model_validate(durable["analysis"])

    async def analyze(self, job_id: str) -> AutopilotAnalysis:
        job = await self.load_job(job_id)
        apk_path = Path(job["apk_path"])
        metadata = await asyncio.to_thread(self._analyze_apk_sync, apk_path)
        await self.update_job(job_id, status="analyzing", stage="designing_tests", progress=65)
        deterministic_tests = self._build_deterministic_tests(metadata)
        enrichment = await self._enrich_with_ai(metadata, job.get("context", ""))
        await self.update_job(job_id, status="analyzing", stage="finalizing", progress=90)

        tests = deterministic_tests + enrichment.get("tests", [])
        deduped: list[AutopilotTest] = []
        seen: set[str] = set()
        for test in tests:
            key = re.sub(r"\W+", " ", test.title.lower()).strip()
            if key and key not in seen:
                deduped.append(test)
                seen.add(key)

        analysis = AutopilotAnalysis(
            job_id=job_id,
            filename=job["filename"],
            status="analysis_partial" if metadata.get("warnings") else "analyzed",
            app_name=metadata.get("app_name"),
            package_name=metadata.get("package_name"),
            version_name=metadata.get("version_name"),
            version_code=metadata.get("version_code"),
            min_sdk=metadata.get("min_sdk"),
            target_sdk=metadata.get("target_sdk"),
            main_activity=metadata.get("main_activity"),
            activities=metadata.get("activities", []),
            services=metadata.get("services", []),
            receivers=metadata.get("receivers", []),
            permissions=metadata.get("permissions", []),
            file_count=metadata.get("file_count", 0),
            size_bytes=metadata.get("size_bytes", 0),
            sha256=metadata["sha256"],
            debuggable=metadata.get("debuggable"),
            inferred_domain=enrichment.get("inferred_domain") or self._infer_domain(metadata, job.get("context", "")),
            app_summary=enrichment.get("app_summary") or self._fallback_summary(metadata),
            critical_journeys=enrichment.get("critical_journeys") or self._fallback_journeys(metadata),
            clarification_questions=enrichment.get("clarification_questions") or self._fallback_questions(metadata),
            tests=deduped[:80],
            release_risks=enrichment.get("release_risks") or self._fallback_risks(metadata),
            warnings=metadata.get("warnings", []),
            capabilities=self._capabilities(metadata),
        )
        await asyncio.to_thread(self._metadata_path(job_id).write_text, analysis.model_dump_json(indent=2), "utf-8")
        await self._persist_job(job, analysis=analysis.model_dump(mode="json"))
        return analysis

    def _analyze_apk_sync(self, apk_path: Path) -> Dict[str, Any]:
        digest = hashlib.sha256()
        with apk_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        result: Dict[str, Any] = {
            "sha256": digest.hexdigest(),
            "size_bytes": apk_path.stat().st_size,
            "warnings": [],
            "activities": [],
            "services": [],
            "receivers": [],
            "permissions": [],
            "file_count": 0,
        }
        try:
            from androguard.core.apk import APK

            apk = APK(str(apk_path))
            result.update(
                {
                    "app_name": apk.get_app_name() or None,
                    "package_name": apk.get_package() or None,
                    "version_name": apk.get_androidversion_name() or None,
                    "version_code": apk.get_androidversion_code() or None,
                    "min_sdk": apk.get_min_sdk_version() or None,
                    "target_sdk": apk.get_target_sdk_version() or None,
                    "main_activity": apk.get_main_activity() or None,
                    "activities": sorted(apk.get_activities() or []),
                    "services": sorted(apk.get_services() or []),
                    "receivers": sorted(apk.get_receivers() or []),
                    "permissions": sorted(apk.get_permissions() or []),
                    "file_count": len(apk.get_files() or []),
                }
            )
            debuggable = apk.get_attribute_value("application", "debuggable")
            result["debuggable"] = str(debuggable).lower() == "true" if debuggable is not None else None
        except Exception as exc:
            result["warnings"].append(f"Deep APK parsing was partial: {type(exc).__name__}: {exc}")
            try:
                import zipfile

                with zipfile.ZipFile(apk_path) as archive:
                    result["file_count"] = len(archive.infolist())
            except Exception:
                pass
        return result

    def _build_deterministic_tests(self, meta: Dict[str, Any]) -> List[AutopilotTest]:
        tests: list[AutopilotTest] = [
            AutopilotTest(
                id="QT-AUTO-SMOKE-001",
                suite="Smoke",
                title="Install and cold-launch application",
                priority="critical",
                objective="Verify the uploaded build installs and reaches a stable foreground UI without an immediate crash.",
                steps=["Install uploaded APK on clean Android device", "Cold-launch the application", "Wait for first stable foreground screen", "Capture screenshot, UI hierarchy and device state"],
                expected=["Installation succeeds", "Application becomes foreground process", "No immediate fatal crash is detected", "A readable UI hierarchy or rendered screen is available"],
            ),
            AutopilotTest(
                id="QT-AUTO-SMOKE-002",
                suite="Smoke",
                title="Background and foreground recovery",
                priority="high",
                objective="Verify the app survives a basic lifecycle interruption.",
                steps=["Launch application", "Send application to background", "Wait briefly", "Restore application to foreground"],
                expected=["Application remains responsive", "No unexpected logout or crash occurs unless explicitly designed"],
            ),
            AutopilotTest(
                id="QT-AUTO-UX-001",
                suite="Accessibility",
                title="Initial-screen accessibility and semantic control scan",
                priority="medium",
                objective="Identify missing labels, inaccessible controls and obvious semantic UI defects on discovered entry screens.",
                steps=["Capture UI hierarchy", "Enumerate interactive controls", "Check labels/content descriptions and enabled states"],
                expected=["Critical interactive controls are discoverable and semantically labelled"],
            ),
            AutopilotTest(
                id="QT-AUTO-SEC-001",
                suite="Security",
                title="Application package security posture baseline",
                priority="high",
                objective="Baseline manifest exposure, requested permissions and debug posture before deeper dynamic security testing.",
                steps=["Inspect Android manifest", "Inventory permissions, exported components and debug posture", "Flag high-risk configuration for review"],
                expected=["No unexplained high-risk package configuration remains unreviewed"],
            ),
        ]
        if "android.permission.INTERNET" in meta.get("permissions", []):
            tests.append(
                AutopilotTest(
                    id="QT-AUTO-NET-001",
                    suite="Resilience",
                    title="Network loss and recovery behavior",
                    priority="high",
                    objective="Verify graceful behavior when connectivity is interrupted and restored.",
                    steps=["Launch app online", "Interrupt connectivity at a safe non-transactional state", "Observe error handling", "Restore connectivity"],
                    expected=["User receives controlled feedback", "App does not crash", "App recovers without corrupting state"],
                )
            )
        for permission, (label, objective) in _DANGEROUS_PERMISSION_HINTS.items():
            if permission in meta.get("permissions", []):
                slug = re.sub(r"\W+", "-", label.upper()).strip("-")
                tests.append(
                    AutopilotTest(
                        id=f"QT-AUTO-PERM-{slug}",
                        suite="Permissions",
                        title=f"{label} permission grant and denial",
                        priority="medium",
                        objective=objective,
                        steps=[f"Navigate to a non-destructive feature requiring {label.lower()} access", "Deny permission", "Verify controlled fallback", "Grant permission and retry"],
                        expected=["Denial is handled without crash", "Permission rationale is understandable when required", "Feature recovers after permission is granted"],
                    )
                )
        if meta.get("debuggable") is True:
            tests.append(
                AutopilotTest(
                    id="QT-AUTO-SEC-DEBUG",
                    suite="Security",
                    title="Debuggable production-build finding",
                    priority="high",
                    objective="Confirm whether android:debuggable=true is intentional for this environment.",
                    steps=["Inspect application debug flag", "Compare with declared test environment"],
                    expected=["Production/release builds are not debuggable unless an approved exception exists"],
                )
            )
        return tests

    async def _enrich_with_ai(self, meta: Dict[str, Any], context: str) -> Dict[str, Any]:
        try:
            provider = get_llm_provider()
            prompt = {
                "artifact": {
                    "app_name": meta.get("app_name"),
                    "package": meta.get("package_name"),
                    "main_activity": meta.get("main_activity"),
                    "permissions": meta.get("permissions", [])[:80],
                    "activities": meta.get("activities", [])[:80],
                    "services": meta.get("services", [])[:40],
                    "receivers": meta.get("receivers", [])[:40],
                    "target_sdk": meta.get("target_sdk"),
                    "debuggable": meta.get("debuggable"),
                },
                "user_context": context[:8000],
            }
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are the QTXpert Autonomous Mobile QA Architect. Infer only what the evidence supports. "
                        "Return strict JSON with keys: app_summary (string), inferred_domain (string), "
                        "critical_journeys (array of short strings), clarification_questions (max 6 array), "
                        "release_risks (array), tests (array). Each test must contain title, suite, priority, "
                        "objective, steps, expected, destructive. Prefer high-value mobile tests that can be "
                        "derived from the artifact. Never assume credentials or real transaction permission."
                    ),
                ),
                LLMMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
            ]
            response = await provider.complete(messages, temperature=0.1, max_tokens=2800, response_format_json=True)
            data = json.loads(response.content)
            parsed_tests: list[AutopilotTest] = []
            for index, raw in enumerate(data.get("tests", [])[:30], start=1):
                if not isinstance(raw, dict) or not raw.get("title"):
                    continue
                priority = str(raw.get("priority", "medium")).lower()
                if priority not in {"critical", "high", "medium", "low"}:
                    priority = "medium"
                parsed_tests.append(
                    AutopilotTest(
                        id=f"QT-AI-{index:03d}",
                        suite=str(raw.get("suite") or "AI Discovery")[:80],
                        title=str(raw["title"])[:240],
                        priority=priority,
                        objective=str(raw.get("objective") or raw["title"])[:700],
                        steps=[str(x)[:500] for x in raw.get("steps", [])[:12]],
                        expected=[str(x)[:500] for x in raw.get("expected", [])[:8]],
                        autonomous=not bool(raw.get("destructive", False)),
                        destructive=bool(raw.get("destructive", False)),
                        source="ai",
                    )
                )
            return {
                "app_summary": str(data.get("app_summary") or "")[:1200],
                "inferred_domain": str(data.get("inferred_domain") or "")[:200],
                "critical_journeys": self._string_list(data.get("critical_journeys"), 12),
                "clarification_questions": self._string_list(data.get("clarification_questions"), 6),
                "release_risks": self._string_list(data.get("release_risks"), 12),
                "tests": parsed_tests,
            }
        except Exception:
            return {}

    @staticmethod
    def _string_list(value: Any, limit: int) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:500] for item in value[:limit] if str(item).strip()]

    def _infer_domain(self, meta: Dict[str, Any], context: str) -> str:
        haystack = " ".join(
            [str(meta.get("app_name") or ""), str(meta.get("package_name") or ""), context]
        ).lower()
        rules = [
            (("bank", "finance", "wallet", "payment", "invest", "loan"), "Banking / Financial Services"),
            (("shop", "retail", "cart", "store", "commerce"), "Retail / E-commerce"),
            (("health", "clinic", "medical", "patient"), "Healthcare"),
            (("travel", "flight", "hotel", "booking"), "Travel / Hospitality"),
        ]
        for terms, label in rules:
            if any(term in haystack for term in terms):
                return label
        return "General mobile application"

    @staticmethod
    def _fallback_summary(meta: Dict[str, Any]) -> str:
        name = meta.get("app_name") or meta.get("package_name") or "Android application"
        return (
            f"QTXpert identified {name} as an Android application with "
            f"{len(meta.get('activities', []))} activities, {len(meta.get('services', []))} services and "
            f"{len(meta.get('permissions', []))} declared permissions. The first Autopilot pass will remain "
            "non-destructive until test credentials and permitted business actions are supplied."
        )

    @staticmethod
    def _fallback_journeys(meta: Dict[str, Any]) -> List[str]:
        journeys = ["Install and cold launch", "First-screen rendering", "Background/foreground recovery"]
        if "android.permission.INTERNET" in meta.get("permissions", []):
            journeys.append("Network-dependent user journey and recovery")
        if meta.get("main_activity"):
            journeys.append(f"Entry journey through {meta['main_activity'].split('.')[-1]}")
        return journeys

    @staticmethod
    def _fallback_questions(meta: Dict[str, Any]) -> List[str]:
        questions = [
            "Which environment may QTXpert test (dev, QA, UAT, staging or production)?",
            "Provide non-production test credentials/roles needed to access authenticated journeys.",
            "Which actions are prohibited or require explicit approval (payments, deletion, notifications, real OTP, etc.)?",
            "Which business journeys are release-critical?",
        ]
        if "android.permission.INTERNET" in meta.get("permissions", []):
            questions.append("Which external APIs/integrated systems should be validated end to end?")
        return questions[:6]

    @staticmethod
    def _fallback_risks(meta: Dict[str, Any]) -> List[str]:
        risks = []
        if meta.get("debuggable") is True:
            risks.append("Application is marked debuggable; validate that this is not a production/release artifact.")
        if len(meta.get("permissions", [])) > 15:
            risks.append("Large permission footprint; review least-privilege and permission-denial behavior.")
        if "android.permission.INTERNET" in meta.get("permissions", []):
            risks.append("Backend/API dependencies require environment-aware validation; APK-only evidence cannot prove business correctness.")
        return risks or ["Business-rule assertions require customer context or trusted backend/oracle data."]

    @staticmethod
    def _capabilities(meta: Dict[str, Any]) -> Dict[str, bool]:
        permissions = set(meta.get("permissions", []))
        return {
            "static_apk_analysis": True,
            "appium_smoke_execution": True,
            "network_test_candidate": "android.permission.INTERNET" in permissions,
            "camera_test_candidate": "android.permission.CAMERA" in permissions,
            "location_test_candidate": bool({"android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"} & permissions),
            "notification_test_candidate": "android.permission.POST_NOTIFICATIONS" in permissions,
            "ai_test_design": True,
        }

    async def _browserstack_app_url(self, job_id: str, apk_path: Path, sha256: str) -> str:
        if not self.settings.browserstack_configured:
            raise RuntimeError(
                "BrowserStack is not configured. Set BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY as backend secrets."
            )

        cache_path = self._job_dir(job_id) / "browserstack.json"
        if cache_path.exists():
            try:
                cached = json.loads(await asyncio.to_thread(cache_path.read_text, "utf-8"))
                if cached.get("sha256") == sha256 and cached.get("app_url"):
                    return str(cached["app_url"])
            except Exception:
                pass

        custom_id = f"qtxpert-{sha256[:24]}"
        timeout = httpx.Timeout(
            float(self.settings.AUTOPILOT_BROWSERSTACK_UPLOAD_TIMEOUT_SECONDS),
            connect=30.0,
        )
        async with httpx.AsyncClient(
            auth=(self.settings.BROWSERSTACK_USERNAME or "", self.settings.BROWSERSTACK_ACCESS_KEY or ""),
            timeout=timeout,
        ) as client:
            with apk_path.open("rb") as handle:
                response = await client.post(
                    self.settings.BROWSERSTACK_UPLOAD_URL,
                    files={
                        "file": (
                            apk_path.name,
                            handle,
                            "application/vnd.android.package-archive",
                        )
                    },
                    data={"custom_id": custom_id},
                )
            if response.status_code >= 400:
                detail = response.text[:500]
                raise RuntimeError(f"BrowserStack app upload failed ({response.status_code}): {detail}")
            payload = response.json()

        app_url = payload.get("app_url")
        if not app_url:
            raise RuntimeError("BrowserStack app upload did not return an app_url")
        cache = {
            "sha256": sha256,
            "app_url": app_url,
            "custom_id": payload.get("custom_id") or custom_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.to_thread(cache_path.write_text, json.dumps(cache, indent=2), "utf-8")
        return str(app_url)

    async def execute_smoke(self, job_id: str, request: AutopilotExecutionRequest) -> AutopilotExecutionResult:
        job = await self.load_job(job_id)
        analysis = await self.load_analysis(job_id)
        started = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        execution_id = uuid4()
        evidence_dir = self._job_dir(job_id) / "evidence" / str(execution_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = evidence_dir / "launch.png"
        source_path = evidence_dir / "page-source.xml"

        try:
            apk_path = Path(job.get("apk_path") or "")
            if not apk_path.is_file() and not request.appium_app:
                raise RuntimeError(
                    "The uploaded APK artifact is unavailable after a service restart. "
                    "Upload the APK again before running smoke execution."
                )
            app_reference = request.appium_app or str(apk_path)
            appium_url = request.appium_url or "http://127.0.0.1:4723"
            browserstack_options: Dict[str, Any] | None = None

            if request.provider == "browserstack":
                app_reference = await self._browserstack_app_url(job_id, apk_path, analysis.sha256)
                appium_url = self.settings.BROWSERSTACK_HUB_URL
                browserstack_options = {
                    "userName": self.settings.BROWSERSTACK_USERNAME,
                    "accessKey": self.settings.BROWSERSTACK_ACCESS_KEY,
                    "projectName": self.settings.BROWSERSTACK_PROJECT_NAME,
                    "buildName": f"Autopilot {analysis.app_name or analysis.package_name or job['filename']}",
                    "sessionName": f"Safe Smoke {job_id[:8]}",
                    "debug": True,
                    "networkLogs": True,
                }

            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._execute_appium_sync,
                    appium_url,
                    app_reference,
                    request,
                    screenshot_path,
                    source_path,
                    browserstack_options,
                    self.settings.AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS * 1000,
                    self.settings.AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS * 1000,
                    analysis.package_name,
                ),
                timeout=self.settings.AUTOPILOT_SMOKE_TIMEOUT_SECONDS,
            )
            result["provider"] = request.provider
            if request.provider == "browserstack":
                result["cloud_app_reference"] = app_reference
            execution_status = "passed"
            error = None
        except Exception as exc:
            result = {"provider": request.provider}
            execution_status = "blocked" if self._looks_like_connector_problem(exc) else "failed"
            error = f"{type(exc).__name__}: {exc}"

        finished = datetime.now(timezone.utc)
        execution = AutopilotExecutionResult(
            execution_id=execution_id,
            job_id=job_id,
            status=execution_status,
            provider=request.provider,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(time.perf_counter() - start_perf, 2),
            device_name=request.device_name,
            current_package=result.get("current_package"),
            current_activity=result.get("current_activity"),
            screenshot_path=str(screenshot_path) if screenshot_path.exists() else None,
            page_source_path=str(source_path) if source_path.exists() else None,
            error=error,
            evidence=result,
        )
        await self._persist_execution_file(execution, request)
        return execution

    @staticmethod
    def _execute_appium_sync(
        appium_url: str,
        app_reference: str,
        request: AutopilotExecutionRequest,
        screenshot_path: Path,
        source_path: Path,
        browserstack_options: Dict[str, Any] | None = None,
        install_timeout_ms: int = 300_000,
        server_launch_timeout_ms: int = 120_000,
        adb_exec_timeout_ms: int = 120_000,
        expected_package: str | None = None,
    ) -> Dict[str, Any]:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        capabilities: Dict[str, Any] = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:autoGrantPermissions": request.auto_grant_permissions,
            "appium:newCommandTimeout": 120,
            "appium:androidInstallTimeout": install_timeout_ms,
            "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
            "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
            "appium:adbExecTimeout": adb_exec_timeout_ms,
            "appium:appWaitDuration": adb_exec_timeout_ms,
        }
        if request.platform_version:
            capabilities["appium:platformVersion"] = request.platform_version
        if browserstack_options:
            capabilities["bstack:options"] = browserstack_options

        options = UiAutomator2Options().load_capabilities(capabilities)
        driver = webdriver.Remote(appium_url, options=options)
        try:
            time.sleep(3)
            driver.get_screenshot_as_file(str(screenshot_path))
            page_source = driver.page_source or ""
            source_path.write_text(page_source, encoding="utf-8")
            current_package = getattr(driver, "current_package", None)
            current_activity = getattr(driver, "current_activity", None)
            AutopilotPrototypeService._validate_runtime_state(
                page_source,
                current_package,
                expected_package,
            )
            return {
                "session_id": driver.session_id,
                "current_package": current_package,
                "current_activity": current_activity,
                "orientation": getattr(driver, "orientation", None),
                "page_source_chars": source_path.stat().st_size if source_path.exists() else 0,
                "expected_package": expected_package,
            }
        finally:
            driver.quit()

    @staticmethod
    def _validate_runtime_state(
        page_source: str,
        current_package: str | None,
        expected_package: str | None,
    ) -> None:
        """Reject false-positive passes caused by Android system dialogs or another app."""
        if not page_source.strip():
            raise RuntimeError("Appium returned an empty UI hierarchy after launch")

        lowered = page_source.lower()
        system_failure_markers = (
            "isn't responding",
            "is not responding",
            "has stopped",
            "keeps stopping",
            "application error",
            "android:id/aerr_close",
            "android:id/aerr_restart",
        )
        if any(marker in lowered for marker in system_failure_markers):
            raise RuntimeError(
                "Android displayed a crash or ANR dialog instead of a stable application screen"
            )

        if not expected_package:
            return
        package_in_hierarchy = (
            f'package="{expected_package}"' in page_source
            or f"package='{expected_package}'" in page_source
        )
        if current_package != expected_package and not package_in_hierarchy:
            actual = current_package or "unknown"
            raise RuntimeError(
                f"Smoke reached foreground package {actual!r}; expected {expected_package!r}"
            )

    @staticmethod
    def _looks_like_connector_problem(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "connection refused",
                "max retries",
                "could not connect",
                "invalid argument: app",
                "browserstack is not configured",
                "browserstack app upload failed (401)",
                "browserstack app upload failed (403)",
                "uploaded apk artifact is unavailable",
                "uploaded apk artifact",
                "unauthorized",
                "authentication",
            )
        )
