"""Autonomous QA service for websites, Android APKs and iOS IPAs.

The prototype separates deterministic binary/runtime analysis from LLM enrichment.
If the configured LLM is unavailable, QTXpert still returns a useful test plan.
Real-device smoke execution can use BrowserStack App Automate when credentials are
configured, while a generic Appium endpoint remains available for local/private labs;
web targets use a bounded Playwright adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import html.parser
import ipaddress
import json
import logging
import plistlib
import re
import shutil
import socket
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database.models.autopilot_job import AutopilotJob
from app.database.session import AsyncSessionLocal
from app.llm.base import LLMMessage
from app.llm.factory import get_llm_provider
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotContextRequest,
    AutopilotContextResponse,
    AutopilotExecutionRequest,
    AutopilotExecutionResult,
    AutopilotJobStatus,
    AutopilotTest,
)
from app.services.appium_compat import safe_app_identity, safe_page_source, safe_quit
from app.services.autopilot_context import default_context, get_profile

logger = logging.getLogger(__name__)
_MISSING = object()


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False

# APK parsers can briefly use hundreds of MiB for resource tables. Render's
# low-cost instance has a small memory envelope, so serialize the expensive
# analysis section across requests and restart recovery. The semaphore lives
# at process scope and is acquired from a worker thread so it never blocks the
# async event loop.
_ANALYSIS_SLOT = threading.BoundedSemaphore(1)


class _WebSurfaceParser(html.parser.HTMLParser):
    """Small, dependency-free parser for bounded website reconnaissance."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms = 0
        self.inputs = 0
        self.buttons = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "a" and values.get("href"):
            self.links.append({"href": values["href"][:2048], "text": values.get("aria-label") or values.get("title") or ""})
        elif tag == "form":
            self.forms += 1
        elif tag in {"input", "select", "textarea"}:
            self.inputs += 1
        elif tag in {"button", "summary"}:
            self.buttons += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


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

    @staticmethod
    def validate_web_url(value: str, *, allow_private: bool = False) -> str:
        """Normalize a URL and reject credential-bearing/unsafe targets.

        Autopilot fetches a user-supplied URL from a hosted worker, so embedded
        credentials and private-network destinations are rejected. Localhost
        remains available for local development and tests only.
        """
        raw = (value or "").strip()
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Website target must be a valid HTTP(S) URL.")
        if parsed.username or parsed.password:
            raise ValueError("Do not embed website credentials in the URL; use the secure setup reference.")
        hostname = parsed.hostname.lower().rstrip(".")
        if not allow_private and hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Hosted Autopilot cannot access localhost; use a reachable HTTPS environment URL.")
        if not allow_private:
            try:
                addresses = {
                    ipaddress.ip_address(item[4][0])
                    for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
                }
                if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved for address in addresses):
                    raise ValueError("Private-network website targets are disabled for hosted Autopilot.")
            except socket.gaierror as exc:
                raise ValueError("Website target hostname could not be resolved.") from exc
        return raw.rstrip("/") or raw

    async def generate_context(self, request: AutopilotContextRequest) -> AutopilotContextResponse:
        """Generate a safe business profile, with a deterministic fallback.

        Context generation is intentionally independent from APK analysis so a
        user can prepare/refine the profile before starting a run. The LLM is
        asked to preserve unknowns as placeholders and never to manufacture
        metrics, credentials or compliance evidence.
        """
        profile = get_profile(request.profile_id)
        baseline = default_context(request.application_name, request.platform, profile.id)
        if request.mode == "default":
            return AutopilotContextResponse(context=baseline, source="default", profile_id=profile.id)

        current = request.current_context.strip()
        prompt = {
            "application_name": request.application_name,
            "package_name": request.package_name,
            "platform": request.platform,
            "focus": request.focus,
            "profile_id": profile.id,
            "profile_name": profile.name,
            "profile_description": profile.description,
            "profile_brief": profile.brief_context,
            "current_context": current[:8000],
            "default_profile": baseline,
        }
        try:
            provider = get_llm_provider()
            response = await provider.complete(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "You are a senior QA and domain-compliance context editor for a website or mobile app. "
                            "Return strict JSON with one key, context, containing a concise (under 1,800 "
                            "characters) but complete "
                            "test context for an autonomous QA agent. Preserve facts supplied by the user, "
                            "use [TO CONFIRM] for unknowns, and never invent metrics, defects, credentials, "
                            "penetration-test results, regulatory approvals or data-residency evidence. "
                            "Keep payments, transfers, OTP and destructive actions approval-gated. Include "
                            "application overview, critical journeys, environment/device scope, test data and "
                            "compliance/reporting expectations."
                        ),
                    ),
                    LLMMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
                ],
                temperature=0.1,
                max_tokens=2200,
                response_format_json=True,
            )
            data = json.loads(response.content)
            generated = str(data.get("context") or "").strip()
            if generated:
                if not generated.lower().startswith("profile category:"):
                    generated = f"Profile category: {profile.name}\n{generated}"
                return AutopilotContextResponse(context=generated[:2400], source="ai", profile_id=profile.id)
        except Exception as exc:  # pragma: no cover - provider availability is environment-specific
            logger.info("Autopilot context AI generation unavailable: %s", exc)

        # For an "improve" request keep the user's text rather than silently
        # replacing it. For a blank request return the ready-to-use profile.
        fallback = current or baseline
        if current and not current.lower().startswith("profile category:"):
            fallback = f"Profile category: {profile.name}\n{current}"
        return AutopilotContextResponse(
            context=fallback[:2400],
            source="fallback",
            profile_id=profile.id,
            warning="AI context generation was unavailable; a safe deterministic profile was applied.",
        )

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
                        project_id=uuid.UUID(str(job["project_id"])) if job.get("project_id") else None,
                        created_at=created_at,
                    )
                    session.add(record)
                record.filename = str(job.get("filename", record.filename))
                record.owner_id = owner_id
                record.project_id = uuid.UUID(str(job["project_id"])) if job.get("project_id") else record.project_id
                record.target_kind = str(job.get("target_kind", getattr(record, "target_kind", "android")))
                record.target_url = job.get("target_url")
                repository_asset_id = job.get("repository_asset_id")
                record.repository_asset_id = (
                    uuid.UUID(str(repository_asset_id)) if repository_asset_id else None
                )
                record.context = str(job.get("context", ""))[:8000]
                document_asset_ids = job.get("document_asset_ids")
                record.document_asset_ids = [str(value) for value in (document_asset_ids or [])][:20]
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
                    "project_id": str(record.project_id) if record.project_id else None,
                    "repository_asset_id": str(record.repository_asset_id)
                    if record.repository_asset_id
                    else None,
                    "filename": record.filename,
                    "target_kind": record.target_kind or "android",
                    "target_url": record.target_url,
                    "context": record.context or "",
                    "document_asset_ids": list(getattr(record, "document_asset_ids", None) or []),
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

    async def save_upload(
        self,
        filename: str,
        data: bytes,
        owner_id: str,
        context: str = "",
        *,
        target_kind: str | None = None,
        project_id: str | None = None,
        document_asset_ids: list[str] | None = None,
    ) -> tuple[str, Path]:
        job_id = str(uuid4())
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        safe_name = Path(filename).name or "application.apk"
        artifact_path = job_dir / safe_name
        await asyncio.to_thread(artifact_path.write_bytes, data)
        kind = target_kind or ("ios" if safe_name.lower().endswith(".ipa") else "android")
        seed = {
            "job_id": job_id,
            "owner_id": owner_id,
            "project_id": project_id,
            "filename": safe_name,
            "target_kind": kind,
            "target_url": None,
            "context": context[:8000],
            "document_asset_ids": [str(value) for value in (document_asset_ids or [])][:20],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "apk_path": str(artifact_path),
            "status": "uploaded",
            "stage": "queued",
            "progress": 5,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.to_thread((job_dir / "job.json").write_text, json.dumps(seed, indent=2), "utf-8")
        await self._persist_job(seed)
        return job_id, artifact_path

    async def save_upload_stream(
        self,
        filename: str,
        upload: Any,
        owner_id: str,
        context: str = "",
        max_bytes: int = 0,
        *,
        target_kind: str | None = None,
        project_id: str | None = None,
        document_asset_ids: list[str] | None = None,
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
        artifact_path = job_dir / safe_name
        kind = target_kind or ("ios" if safe_name.lower().endswith(".ipa") else "android")
        total = 0
        handle = None
        try:
            handle = await asyncio.to_thread(artifact_path.open, "wb")
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
                "project_id": project_id,
                "filename": safe_name,
                "target_kind": kind,
                "target_url": None,
                "context": context[:8000],
                "document_asset_ids": [str(value) for value in (document_asset_ids or [])][:20],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "apk_path": str(artifact_path),
                "status": "uploaded",
                "stage": "queued",
                "progress": 5,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await asyncio.to_thread((job_dir / "job.json").write_text, json.dumps(seed, indent=2), "utf-8")
            await self._persist_job(seed)
            return job_id, artifact_path
        except Exception:
            if handle is not None:
                await asyncio.to_thread(handle.close)
                handle = None
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)
            raise
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)

    async def save_web_target(
        self,
        target_url: str,
        owner_id: str,
        context: str = "",
        *,
        project_id: str | None = None,
        document_asset_ids: list[str] | None = None,
    ) -> str:
        """Create a durable URL job without copying website data to storage."""
        url = self.validate_web_url(target_url, allow_private=self.settings.APP_ENV == "local")
        job_id = str(uuid4())
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        parsed = urlparse(url)
        filename = (parsed.hostname or "website")[:240]
        seed = {
            "job_id": job_id,
            "owner_id": owner_id,
            "project_id": project_id,
            "filename": filename,
            "target_kind": "web",
            "target_url": url,
            "context": context[:8000],
            "document_asset_ids": [str(value) for value in (document_asset_ids or [])][:20],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "uploaded",
            "stage": "queued",
            "progress": 5,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.to_thread((job_dir / "job.json").write_text, json.dumps(seed, indent=2), "utf-8")
        await self._persist_job(seed)
        return job_id

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
        target_kind = str(job.get("target_kind") or ("ios" if str(job.get("filename", "")).lower().endswith(".ipa") else "android"))
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
            target_available = bool(job.get("target_url")) if target_kind == "web" else bool(apk_path and Path(apk_path).is_file())
            if not target_available:
                await self.update_job(
                    job_id,
                    status="failed",
                    stage="failed",
                    progress=100,
                    error=(
                        "The website target is no longer available after a service restart. Please submit the URL again."
                        if target_kind == "web"
                        else "The uploaded mobile artifact is no longer available after a service restart. Please upload it again."
                    ),
                )
                job = await self.load_job(job_id)
        artifact_path = job.get("apk_path")
        document_asset_ids: list[uuid.UUID] = []
        for value in job.get("document_asset_ids", []) or []:
            try:
                document_asset_ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return AutopilotJobStatus(
            job_id=job_id,
            filename=job["filename"],
            status=job.get("status", "uploaded"),
            target_kind=target_kind,
            target_url=job.get("target_url"),
            stage=job.get("stage", "queued"),
            progress=int(job.get("progress", 0)),
            created_at=job["created_at"],
            updated_at=job.get("updated_at", job["created_at"]),
            context=str(job.get("context", "")),
            document_asset_ids=document_asset_ids,
            artifact_available=(bool(job.get("target_url")) if target_kind == "web" else bool(artifact_path and Path(artifact_path).is_file())),
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
        acquired = False
        try:
            await asyncio.to_thread(_ANALYSIS_SLOT.acquire)
            acquired = True
            job = await self.load_job(job_id)
            target_kind = str(job.get("target_kind") or "android")
            await self.update_job(
                job_id,
                status="analyzing",
                stage="fetching_website" if target_kind == "web" else "reading_mobile_artifact",
                progress=15,
                error=None,
            )
            await asyncio.wait_for(self.analyze(job_id), timeout=self.settings.AUTOPILOT_ANALYSIS_TIMEOUT_SECONDS)
            await self.update_job(job_id, status="analyzed", stage="complete", progress=100)
            logger.info("Autopilot analysis completed job_id=%s duration_seconds=%.2f", job_id, time.perf_counter() - started)
        except asyncio.TimeoutError:
            message = (
                f"Autopilot analysis exceeded {self.settings.AUTOPILOT_ANALYSIS_TIMEOUT_SECONDS}s. "
                "The job was stopped safely; retry with a bounded website target or a smaller/deep-parse-safe artifact."
            )
            logger.error("Autopilot analysis timed out job_id=%s after %.2fs", job_id, time.perf_counter() - started)
            await self.update_job(job_id, status="failed", stage="failed", progress=100, error=message)
        except Exception as exc:
            logger.exception("Autopilot analysis failed job_id=%s", job_id)
            await self.update_job(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
        finally:
            if acquired:
                _ANALYSIS_SLOT.release()

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
        context_text = str(job.get("context") or "").strip()
        target_kind = str(job.get("target_kind") or ("ios" if str(job.get("filename", "")).lower().endswith(".ipa") else "android"))
        if target_kind == "web":
            metadata = await self._analyze_web(str(job.get("target_url") or ""))
        elif target_kind == "ios":
            metadata = await asyncio.to_thread(self._analyze_ipa_sync, Path(job["apk_path"]))
        else:
            metadata = await asyncio.to_thread(self._analyze_apk_sync, Path(job["apk_path"]))
        await self.update_job(job_id, status="analyzing", stage="designing_tests", progress=65)
        deterministic_tests = self._build_deterministic_tests(metadata)
        enrichment = await self._enrich_with_ai(metadata, context_text)
        ai_enrichment_used = bool(enrichment.pop("_ai_used", False))
        await self.update_job(job_id, status="analyzing", stage="finalizing", progress=90)

        tests = deterministic_tests + enrichment.get("tests", [])
        deduped: list[AutopilotTest] = []
        seen: set[str] = set()
        for test in tests:
            key = re.sub(r"\W+", " ", test.title.lower()).strip()
            if key and key not in seen:
                deduped.append(test)
                seen.add(key)

        document_asset_ids = [
            uuid.UUID(str(value))
            for value in (job.get("document_asset_ids", []) or [])
            if _is_uuid(value)
        ]
        analysis_basis = [
            "Observed target metadata and bounded runtime/HTML evidence",
            (
                "Selected profile and user-supplied context used as analysis scope"
                if context_text
                else "No user context supplied; profile scope was unavailable"
            ),
            "Deterministic coverage and safety rules",
            "LLM enrichment applied to context-aware journeys and test design"
            if ai_enrichment_used
            else "LLM enrichment unavailable; deterministic fallback retained the selected scope",
        ]
        if document_asset_ids:
            analysis_basis.append(
                f"{len(document_asset_ids)} selected repository document(s) supplied bounded, redacted context"
            )

        analysis = AutopilotAnalysis(
            job_id=job_id,
            filename=job["filename"],
            platform=target_kind,
            target_kind=target_kind,
            target_url=job.get("target_url"),
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
            inferred_domain=enrichment.get("inferred_domain") or self._infer_domain(metadata, context_text),
            app_summary=enrichment.get("app_summary") or self._fallback_summary(metadata),
            critical_journeys=enrichment.get("critical_journeys") or self._fallback_journeys(metadata),
            clarification_questions=enrichment.get("clarification_questions") or self._fallback_questions(metadata),
            tests=deduped[:80],
            release_risks=enrichment.get("release_risks") or self._fallback_risks(metadata),
            warnings=metadata.get("warnings", []),
            capabilities=self._capabilities(metadata),
            context_considered=bool(context_text),
            ai_enrichment_used=ai_enrichment_used,
            analysis_basis=analysis_basis,
            document_asset_ids=document_asset_ids,
        )
        await asyncio.to_thread(self._metadata_path(job_id).write_text, analysis.model_dump_json(indent=2), "utf-8")
        await self._persist_job(job, analysis=analysis.model_dump(mode="json"))
        return analysis

    async def _analyze_web(self, target_url: str) -> Dict[str, Any]:
        """Inspect a bounded public website surface without executing writes.

        This first pass intentionally gathers HTTP/HTML evidence only. Login,
        authenticated journeys and business assertions remain pending until the
        user supplies an approved credential/data reference through Setup.
        """
        url = self.validate_web_url(target_url, allow_private=self.settings.APP_ENV == "local")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        result: Dict[str, Any] = {
            "platform": "web",
            "sha256": digest,
            "size_bytes": 0,
            "warnings": [],
            "activities": [],
            "services": [],
            "receivers": [],
            "permissions": [],
            "file_count": 0,
            "app_name": urlparse(url).hostname or "Website",
            "package_name": None,
            "main_activity": None,
            "web_url": url,
            "web_status_code": None,
            "web_final_url": url,
            "web_title": None,
            "web_link_count": 0,
            "web_form_count": 0,
            "web_input_count": 0,
            "web_button_count": 0,
            "web_links": [],
        }
        timeout = httpx.Timeout(float(self.settings.AUTOPILOT_WEB_TIMEOUT_SECONDS), connect=10.0)
        try:
            # Do not let a public open-redirect turn the reconnaissance worker
            # into an SSRF proxy. Validate every redirect hop before following
            # it and keep the chain deliberately short.
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                headers={"User-Agent": "QTXpert-Autopilot/1.0 (safe reconnaissance)"},
            ) as client:
                request_url = url
                response = None
                for _ in range(5):
                    response = await client.get(request_url)
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location")
                    if not location:
                        break
                    request_url = self.validate_web_url(
                        urljoin(request_url, location),
                        allow_private=self.settings.APP_ENV == "local",
                    )
                if response is None:
                    raise RuntimeError("Website returned no HTTP response")
            result["web_status_code"] = response.status_code
            result["web_final_url"] = request_url
            content = response.text[:2_000_000]
            parser = _WebSurfaceParser()
            parser.feed(content)
            result.update(
                {
                    "web_title": " ".join(parser.title_parts)[:300] or None,
                    "web_link_count": len(parser.links),
                    "web_form_count": parser.forms,
                    "web_input_count": parser.inputs,
                    "web_button_count": parser.buttons,
                    "web_links": parser.links[: self.settings.AUTOPILOT_WEB_MAX_PAGES * 3],
                    "size_bytes": len(response.content),
                }
            )
            if response.status_code >= 400:
                result["warnings"].append(f"Website returned HTTP {response.status_code}; functional evidence is pending.")
            if "text/html" not in response.headers.get("content-type", "").lower():
                result["warnings"].append("Website target did not return HTML; runtime UI discovery may be limited.")
        except Exception as exc:
            # Keep the job analyzable with a clear blocked dependency rather
            # than allowing a transient target outage to become a hung job.
            result["warnings"].append(f"Website surface fetch was partial: {type(exc).__name__}: {str(exc)[:240]}")
        return result

    def _analyze_ipa_sync(self, ipa_path: Path) -> Dict[str, Any]:
        """Read iOS bundle metadata without unpacking the entire IPA."""
        digest = hashlib.sha256()
        with ipa_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result: Dict[str, Any] = {
            "platform": "ios",
            "sha256": digest.hexdigest(),
            "size_bytes": ipa_path.stat().st_size,
            "warnings": [],
            "activities": [],
            "services": [],
            "receivers": [],
            "permissions": [],
            "file_count": 0,
            "app_name": None,
            "package_name": None,
            "version_name": None,
            "version_code": None,
            "min_sdk": None,
            "target_sdk": None,
            "main_activity": None,
            "debuggable": None,
        }
        try:
            with zipfile.ZipFile(ipa_path) as archive:
                infos = archive.infolist()
                result["file_count"] = len(infos)
                plist_name = next(
                    (info.filename for info in infos if re.match(r"Payload/[^/]+\.app/Info\.plist$", info.filename)),
                    None,
                )
                if not plist_name:
                    result["warnings"].append("IPA does not contain a standard Payload/*.app/Info.plist bundle metadata file.")
                    return result
                with archive.open(plist_name) as handle:
                    plist = plistlib.load(handle)
                result.update(
                    {
                        "app_name": plist.get("CFBundleDisplayName") or plist.get("CFBundleName"),
                        "package_name": plist.get("CFBundleIdentifier"),
                        "version_name": plist.get("CFBundleShortVersionString"),
                        "version_code": str(plist.get("CFBundleVersion")) if plist.get("CFBundleVersion") is not None else None,
                    }
                )
        except Exception as exc:
            result["warnings"].append(f"IPA metadata parsing was partial: {type(exc).__name__}: {str(exc)[:240]}")
        return result

    def _analyze_apk_sync(self, apk_path: Path) -> Dict[str, Any]:
        digest = hashlib.sha256()
        with apk_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        result: Dict[str, Any] = {
            "platform": "android",
            "sha256": digest.hexdigest(),
            "size_bytes": apk_path.stat().st_size,
            "warnings": [],
            "activities": [],
            "services": [],
            "receivers": [],
            "permissions": [],
            "file_count": 0,
        }
        deep_parse_limit = self.settings.AUTOPILOT_DEEP_PARSE_MAX_MB * 1024 * 1024
        if result["size_bytes"] > deep_parse_limit:
            result["warnings"].append(
                f"Deep APK parsing skipped for this {result['size_bytes'] / (1024 * 1024):.1f}MB artifact "
                f"(limit {self.settings.AUTOPILOT_DEEP_PARSE_MAX_MB}MB) to protect the analysis worker memory budget."
            )
            try:
                with zipfile.ZipFile(apk_path) as archive:
                    result["file_count"] = len(archive.infolist())
            except Exception as exc:
                result["warnings"].append(f"APK ZIP inventory was unavailable: {type(exc).__name__}")
            return result
        try:
            # Androguard 4.x uses Loguru for resource-table diagnostics. Its
            # DEBUG stream can contain tens of thousands of lines for a normal
            # APK and can exhaust Render's log/memory budget. Suppress only the
            # third-party namespace; Autopilot's warnings and exceptions remain
            # visible through the application logger.
            try:
                from loguru import logger as androguard_logger

                androguard_logger.disable("androguard")
            except Exception:
                pass
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
        if meta.get("platform") == "web":
            return self._build_web_tests(meta)
        tests: list[AutopilotTest] = [
            AutopilotTest(
                id="QT-AUTO-SMOKE-001",
                suite="Smoke",
                bucket="installation",
                title="Install and cold-launch application",
                priority="critical",
                objective="Verify the uploaded build installs and reaches a stable foreground UI without an immediate crash.",
                steps=["Install uploaded APK on clean Android device", "Cold-launch the application", "Wait for first stable foreground screen", "Capture screenshot, UI hierarchy and device state"],
                expected=["Installation succeeds", "Application becomes foreground process", "No immediate fatal crash is detected", "A readable UI hierarchy or rendered screen is available"],
            ),
            AutopilotTest(
                id="QT-AUTO-SMOKE-002",
                suite="Smoke",
                bucket="resilience",
                title="Background and foreground recovery",
                priority="high",
                objective="Verify the app survives a basic lifecycle interruption.",
                steps=["Launch application", "Send application to background", "Wait briefly", "Restore application to foreground"],
                expected=["Application remains responsive", "No unexpected logout or crash occurs unless explicitly designed"],
            ),
            AutopilotTest(
                id="QT-AUTO-UX-001",
                suite="Accessibility",
                bucket="accessibility",
                title="Initial-screen accessibility and semantic control scan",
                priority="medium",
                objective="Identify missing labels, inaccessible controls and obvious semantic UI defects on discovered entry screens.",
                steps=["Capture UI hierarchy", "Enumerate interactive controls", "Check labels/content descriptions and enabled states"],
                expected=["Critical interactive controls are discoverable and semantically labelled"],
            ),
            AutopilotTest(
                id="QT-AUTO-SEC-001",
                suite="Security",
                bucket="security",
                title="Application package security posture baseline",
                priority="high",
                objective="Baseline manifest exposure, requested permissions and debug posture before deeper dynamic security testing.",
                steps=["Inspect Android manifest", "Inventory permissions, exported components and debug posture", "Flag high-risk configuration for review"],
                expected=["No unexplained high-risk package configuration remains unreviewed"],
            ),
            AutopilotTest(
                id="QT-AUTO-PAGE-001",
                suite="Page-level",
                bucket="page_level",
                title="Screen inventory and navigation coverage",
                priority="high",
                objective="Discover every safely reachable screen and maintain an evidence-backed navigation map.",
                steps=["Inventory runtime screens", "Map safe navigation controls and transitions", "Record unreachable or approval-gated pages"],
                expected=["Each discovered screen has a stable identity, entry path and captured UI hierarchy"],
                dependency="Runtime screen discovery and an approved navigation map are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-FUNC-001",
                suite="Functional",
                bucket="functional",
                title="Authenticated end-to-end functional journey",
                priority="critical",
                objective="Validate a complete release-critical business journey from authentication through its safe terminal state.",
                steps=["Authenticate with an approved non-production account", "Execute the configured critical journey", "Verify business and API outcomes", "Run approved cleanup"],
                expected=["The journey completes with correct state, messages, persistence and integration outcomes"],
                requires_auth=True,
                requires_test_data=True,
                dependency="A secure non-production credential reference, role permissions, seeded test data, environment URL and reset hook are required.",
                evidence_required=["journey screenshots", "API or business oracle", "cleanup result"],
            ),
            AutopilotTest(
                id="QT-AUTO-FUNC-002",
                suite="Functional negative paths",
                bucket="functional",
                title="Validation, negative and recovery paths",
                priority="high",
                objective="Verify boundary, invalid-input, backend-error and retry behavior without using production data.",
                steps=["Load representative synthetic data", "Exercise approved negative and boundary conditions", "Observe error and recovery behavior", "Verify no invalid state is persisted"],
                expected=["Validation is specific and controlled, recovery is possible and invalid state is not committed"],
                requires_test_data=True,
                dependency="Approved acceptance criteria, representative synthetic data and backend error/oracle access are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-UAT-001",
                suite="UAT",
                bucket="uat",
                title="Business acceptance journey",
                priority="critical",
                objective="Validate signed-off user acceptance criteria for the primary business role and journey.",
                steps=["Load signed-off acceptance criteria", "Authenticate as the approved UAT role", "Execute the primary business scenario with synthetic data", "Compare the outcome with acceptance evidence"],
                expected=["Every acceptance criterion has a conclusive pass/fail result with traceable evidence"],
                requires_auth=True,
                requires_test_data=True,
                dependency="Signed-off acceptance criteria, a non-production role, test data, an environment and cleanup hook are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-UI-001",
                suite="UI",
                bucket="ui",
                title="Page-level UI visual and interaction baseline",
                priority="medium",
                objective="Capture an initial evidence baseline for layout, labels, viewport behavior and safe interactions.",
                steps=["Inspect the current page layout and controls", "Capture screenshot and UI hierarchy", "Compare against approved device and visual baselines"],
                expected=["The visible page has no obvious clipping, overlap, unreadable labels or inaccessible safe controls"],
                dependency="Runtime screen discovery, supported viewport matrix and approved visual baselines are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-INTEGRATION-001",
                suite="Integration",
                bucket="integration",
                title="Backend API and third-party integration contracts",
                priority="high",
                objective="Validate configured backend and third-party contracts across approved app journeys.",
                steps=["Exercise approved API-backed journeys", "Correlate UI outcome with the trusted API oracle", "Verify timeout, error and retry contracts"],
                expected=["UI and backend outcomes agree and integration failures are handled without data corruption"],
                requires_test_data=True,
                dependency="Non-production endpoints, API/oracle access, synthetic data and reset capability are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-PERF-001",
                suite="Performance",
                bucket="performance",
                title="Startup, responsiveness and resource footprint",
                priority="high",
                objective="Measure startup and key interaction responsiveness on the approved device matrix.",
                steps=["Measure cold and warm startup", "Measure key interaction latency", "Capture CPU, memory, network and battery indicators"],
                expected=["Observed measurements are reported against approved thresholds without inventing a pass decision"],
                dependency="Performance thresholds, representative devices and an approved measurement environment are required.",
            ),
            AutopilotTest(
                id="QT-AUTO-COMPAT-001",
                suite="Compatibility",
                bucket="compatibility",
                title="Supported Android and iOS device matrix",
                priority="high",
                objective="Validate installation, launch and primary safe journeys across the supported OS/device matrix.",
                steps=["Install the release build on each approved device and OS", "Run launch and safe navigation checks", "Record platform-specific differences"],
                expected=["Compatibility outcomes are traceable by device, OS and application version"],
                dependency="A signed iOS build is required for iOS coverage; Android APK evidence applies only to Android.",
            ),
            AutopilotTest(
                id="QT-AUTO-REG-001",
                suite="Regression",
                bucket="regression",
                title="Repeatable release regression pack",
                priority="high",
                objective="Re-execute an approved baseline and compare the current build with the previous release.",
                steps=["Load the selected baseline suite", "Execute eligible safe checks", "Compare results and evidence with the prior build", "Flag new or changed failures"],
                expected=["Every baseline case has a current outcome and version-to-version comparison"],
                requires_test_data=True,
                dependency="A selected baseline, stable synthetic data and reset/cleanup reference are required.",
            ),
        ]
        if "android.permission.INTERNET" in meta.get("permissions", []):
            tests.append(
                AutopilotTest(
                    id="QT-AUTO-NET-001",
                    suite="Resilience",
                    bucket="resilience",
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
                        bucket="permissions",
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
                    bucket="security",
                    title="Debuggable production-build finding",
                    priority="high",
                    objective="Confirm whether android:debuggable=true is intentional for this environment.",
                    steps=["Inspect application debug flag", "Compare with declared test environment"],
                    expected=["Production/release builds are not debuggable unless an approved exception exists"],
                )
            )
        return tests

    @staticmethod
    def _build_web_tests(meta: Dict[str, Any]) -> List[AutopilotTest]:
        """Create a complete, honest website coverage plan from HTML evidence."""
        form_note = (
            "The target exposes HTML forms; an approved non-production credential/data reference is required for authenticated journeys."
            if meta.get("web_form_count")
            else "No HTML forms were observed on the initial public page; authenticated journeys still require explicit setup."
        )
        return [
            AutopilotTest(
                id="QT-WEB-SMOKE-001",
                suite="Smoke",
                bucket="page_level",
                title="Load website and verify first render",
                priority="critical",
                objective="Verify the target responds over HTTP(S) and renders a usable first page.",
                steps=["Open the configured website URL", "Wait for DOM content", "Capture screenshot, HTML and response metadata"],
                expected=["The target responds successfully", "A readable document is rendered", "No unhandled browser error is observed"],
            ),
            AutopilotTest(
                id="QT-WEB-PAGE-001",
                suite="Page-level",
                bucket="page_level",
                title="Discover same-origin pages and navigation surface",
                priority="high",
                objective="Build a bounded, evidence-backed map of same-origin pages reachable from the public entry point.",
                steps=["Crawl same-origin links within the configured bound", "Capture page title, URL and interactive controls", "Record blocked or unreachable links"],
                expected=["Each discovered page has a stable URL and captured evidence"],
            ),
            AutopilotTest(
                id="QT-WEB-UI-001",
                suite="UI",
                bucket="ui",
                title="Visual layout and responsive UI baseline",
                priority="medium",
                objective="Capture a visual baseline for the public pages at supported viewport sizes.",
                steps=["Render the page at desktop and mobile viewports", "Capture screenshots", "Check for overflow, clipping and unreadable controls"],
                expected=["No obvious layout breakage is observed at the approved viewports"],
                dependency="Approved viewport matrix and visual baselines are required.",
            ),
            AutopilotTest(
                id="QT-WEB-A11Y-001",
                suite="Accessibility",
                bucket="accessibility",
                title="Semantic controls and accessibility baseline",
                priority="high",
                objective="Inventory interactive controls and identify missing accessible names or keyboard reachability.",
                steps=["Inspect links, buttons, inputs and headings", "Check accessible names and enabled states", "Capture DOM evidence for review"],
                expected=["Critical controls have deterministic accessible names and can be reached safely"],
            ),
            AutopilotTest(
                id="QT-WEB-SEC-001",
                suite="Security",
                bucket="security",
                title="HTTP security headers and transport baseline",
                priority="high",
                objective="Record transport and security-header posture for the target response without attempting exploitation.",
                steps=["Inspect HTTPS redirect and response headers", "Check content-security and framing directives", "Capture headers as evidence"],
                expected=["Transport and security-header posture is documented for review"],
                dependency="Approved security-header policy and dynamic security assessment are required for a conclusive decision.",
            ),
            AutopilotTest(
                id="QT-WEB-FUNC-001",
                suite="Functional / UAT",
                bucket="functional",
                title="Authenticated end-to-end business journey",
                priority="critical",
                objective="Validate the release-critical user journey through authenticated, non-production pages and integrations.",
                steps=["Authenticate with an approved non-production account", "Execute the configured business journey", "Verify UI and API/oracle outcomes", "Run approved cleanup"],
                expected=["The journey completes with correct state and traceable evidence"],
                requires_auth=True,
                requires_test_data=True,
                dependency=f"{form_note} Provide credential, role, test-data, environment and reset references.",
                evidence_required=["journey screenshots", "API or business oracle", "cleanup result"],
            ),
            AutopilotTest(
                id="QT-WEB-PERF-001",
                suite="Performance",
                bucket="performance",
                title="Page responsiveness and network timing baseline",
                priority="high",
                objective="Measure page load and key navigation timings against approved thresholds.",
                steps=["Capture navigation timing", "Measure key public pages", "Record errors and resource failures"],
                expected=["Observed timing and error metrics are reported against approved thresholds"],
                dependency="Performance thresholds, representative browsers and an approved load environment are required.",
            ),
            AutopilotTest(
                id="QT-WEB-REG-001",
                suite="Regression",
                bucket="regression",
                title="Repeatable public-surface regression pack",
                priority="high",
                objective="Re-run the discovered safe public checks and compare the current evidence with a prior run.",
                steps=["Load the previous approved baseline", "Re-run safe page, UI and accessibility checks", "Compare evidence and flag changed outcomes"],
                expected=["Current results are traceable to the selected baseline"],
                dependency="A prior completed baseline run is required.",
            ),
        ]

    async def _enrich_with_ai(self, meta: Dict[str, Any], context: str) -> Dict[str, Any]:
        try:
            provider = get_llm_provider()
            prompt = {
                "platform": meta.get("platform", "android"),
                "target_url": meta.get("web_url"),
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
                "context_role": (
                    "Treat user_context as a first-class testing scope. Derive relevant journeys, controls, "
                    "risks and clarification questions from it, while labeling its claims as user-supplied "
                    "until target or runtime evidence confirms them."
                ),
            }
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are the QTXpert Autonomous QA Architect for a website or mobile application. Infer only what the evidence supports. "
                        "Treat the supplied user context as a first-class scope input: context-mentioned journeys and controls "
                        "must influence the generated plan or clarification questions, but context claims are not observed evidence. "
                        "Return strict JSON with keys: app_summary (string), inferred_domain (string), "
                        "critical_journeys (array of short strings), clarification_questions (max 6 array), "
                        "release_risks (array), tests (array). Each test must contain title, suite, priority, "
                        "objective, steps, expected, destructive. Prefer high-value tests that can be "
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
                suite = str(raw.get("suite") or "AI Discovery")[:80]
                title = str(raw["title"])[:240]
                objective = str(raw.get("objective") or raw["title"])[:700]
                steps = [str(x)[:500] for x in raw.get("steps", [])[:12]]
                semantic_text = " ".join([suite, title, objective, *steps]).lower()
                bucket = self._classify_test_bucket(suite, semantic_text)
                requires_auth = any(
                    token in semantic_text
                    for token in ("authenticate", "authenticated", "authentication", "sign in", "signin", "login", "log in", "kyc", "account role")
                )
                requires_test_data = any(
                    token in semantic_text
                    for token in ("test data", "input", "form", "payment", "transfer", "transaction", "checkout", "portfolio", "credit card", "order", "seeded data")
                )
                destructive = bool(raw.get("destructive", False))
                parsed_tests.append(
                    AutopilotTest(
                        id=f"QT-AI-{index:03d}",
                        suite=suite,
                        bucket=bucket,
                        title=title,
                        priority=priority,
                        objective=objective,
                        steps=steps,
                        expected=[str(x)[:500] for x in raw.get("expected", [])[:8]],
                        autonomous=not destructive,
                        destructive=destructive,
                        source="ai",
                        requires_auth=requires_auth,
                        requires_test_data=requires_test_data,
                        dependency=self._ai_dependency(bucket, requires_auth, requires_test_data, destructive),
                    )
                )
            return {
                "_ai_used": True,
                "app_summary": str(data.get("app_summary") or "")[:1200],
                "inferred_domain": str(data.get("inferred_domain") or "")[:200],
                "critical_journeys": self._string_list(data.get("critical_journeys"), 12),
                "clarification_questions": self._string_list(data.get("clarification_questions"), 6),
                "release_risks": self._string_list(data.get("release_risks"), 12),
                "tests": parsed_tests,
            }
        except Exception as exc:
            # The deterministic plan remains valid when an LLM is unavailable;
            # keep the reason in server logs without exposing it to the user.
            logger.info("Autopilot AI enrichment unavailable: %s", exc)
            return {"_ai_used": False}

    @staticmethod
    def _classify_test_bucket(suite: str, semantic_text: str):
        """Map variable AI suite labels to QTXpert's stable coverage taxonomy."""
        suite_text = suite.lower()
        rules = (
            ("installation", ("install", "upgrade", "cold launch", "package deployment")),
            ("uat", ("uat", "user acceptance", "acceptance criteria")),
            ("accessibility", ("accessibility", "a11y", "screen reader", "wcag")),
            ("performance", ("performance", "load", "latency", "throughput", "resource footprint", "startup time")),
            ("security", ("security", "penetration", "vulnerability", "encryption", "tls", "data protection")),
            ("integration", ("integration", "api", "backend", "third-party", "webhook", "contract")),
            ("compatibility", ("compatibility", "device matrix", "os matrix", "cross-platform")),
            ("permissions", ("permission", "privacy consent")),
            ("regression", ("regression", "baseline comparison")),
            ("resilience", ("resilience", "recovery", "offline", "network loss", "background", "interruption", "retry")),
            ("page_level", ("page-level", "page level", "screen inventory", "screen coverage")),
            ("ui", ("visual", "layout", "responsive ui", "user interface", "ui test")),
        )
        for bucket, signals in rules:
            if any(signal in suite_text for signal in signals):
                return bucket
        for bucket, signals in rules:
            if any(signal in semantic_text for signal in signals):
                return bucket
        return "functional"

    @staticmethod
    def _ai_dependency(bucket: str, requires_auth: bool, requires_test_data: bool, destructive: bool) -> str | None:
        needs: list[str] = []
        if requires_auth:
            needs.extend(["an approved non-production credential reference", "account role", "safe authentication approval"])
        if requires_test_data:
            needs.extend(["synthetic test data", "reset/cleanup reference"])
        if bucket == "uat":
            needs.append("signed-off acceptance criteria")
        if bucket == "integration":
            needs.append("API/oracle reference")
        if destructive:
            needs.append("explicit supervised-run approval")
        if not needs:
            return None
        return "Required: " + ", ".join(dict.fromkeys(needs)) + "."

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
        return "General web application" if meta.get("platform") == "web" else "General mobile application"

    @staticmethod
    def _fallback_summary(meta: Dict[str, Any]) -> str:
        if meta.get("platform") == "web":
            name = meta.get("web_title") or meta.get("app_name") or "Website"
            return (
                f"QTXpert inspected the public surface of {name}. The initial target returned "
                f"HTTP {meta.get('web_status_code') or 'unknown'} with {meta.get('web_link_count', 0)} link(s), "
                f"{meta.get('web_form_count', 0)} form(s) and {meta.get('web_input_count', 0)} input control(s). "
                "Authenticated and business-critical outcomes remain pending until approved test setup is provided."
            )
        name = meta.get("app_name") or meta.get("package_name") or ("iOS application" if meta.get("platform") == "ios" else "Android application")
        return (
            f"QTXpert identified {name} as an {('iOS' if meta.get('platform') == 'ios' else 'Android')} application with "
            f"{len(meta.get('activities', []))} activities, {len(meta.get('services', []))} services and "
            f"{len(meta.get('permissions', []))} declared permissions. The first Autopilot pass will remain "
            "non-destructive until test credentials and permitted business actions are supplied."
        )

    @staticmethod
    def _fallback_journeys(meta: Dict[str, Any]) -> List[str]:
        if meta.get("platform") == "web":
            journeys = ["Public entry-page render", "Same-origin navigation surface", "Semantic control and accessibility scan"]
            if meta.get("web_form_count"):
                journeys.append("Authenticated form and business journey (setup required)")
            return journeys
        journeys = ["Install and cold launch", "First-screen rendering", "Background/foreground recovery"]
        if "android.permission.INTERNET" in meta.get("permissions", []):
            journeys.append("Network-dependent user journey and recovery")
        if meta.get("main_activity"):
            journeys.append(f"Entry journey through {meta['main_activity'].split('.')[-1]}")
        return journeys

    @staticmethod
    def _fallback_questions(meta: Dict[str, Any]) -> List[str]:
        if meta.get("platform") == "web":
            return [
                "Which non-production environment and approved URL may QTXpert test?",
                "Provide a vault/credential reference and account role for authenticated journeys.",
                "Which business actions are prohibited or require explicit approval?",
                "Which pages and integrations are release-critical?",
                "Provide synthetic test data and a reset/cleanup reference.",
                "Which browsers, viewport sizes and performance thresholds are in scope?",
            ]
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
        if meta.get("platform") == "web":
            risks = []
            if meta.get("web_status_code", 200) >= 400:
                risks.append(f"Initial website request returned HTTP {meta.get('web_status_code')}; availability requires investigation.")
            if meta.get("web_form_count"):
                risks.append("Authenticated and form-driven journeys were discovered but not executed without approved credentials and synthetic data.")
            return risks or ["Business rules, authenticated journeys and backend integrations require approved setup and runtime evidence."]
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
        if meta.get("platform") == "web":
            return {
                "static_web_surface_analysis": True,
                "playwright_smoke_execution": True,
                "runtime_web_discovery": True,
                "authenticated_journey_execution": False,
                "ai_test_design": True,
            }
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
                            "application/octet-stream" if apk_path.suffix.lower() == ".ipa" else "application/vnd.android.package-archive",
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

    def resolve_appium_url(self, request: AutopilotExecutionRequest) -> str:
        """Resolve and validate a custom Appium endpoint before opening a session.

        The previous fallback to ``127.0.0.1:4723`` made every hosted Render
        run fail with a low-level connection error because that address points
        at the Render container, not the customer's laptop.  Keep that
        convenience only for the local development server; hosted runs must
        provide an explicit reachable endpoint (or use BrowserStack).
        """
        configured = (self.settings.AUTOPILOT_CUSTOM_APPIUM_URL or "").strip()
        supplied = (request.appium_url or "").strip()
        value = supplied or configured
        if not value and self.settings.APP_ENV == "local":
            value = "http://127.0.0.1:4723"
        if not value:
            raise RuntimeError(
                "Custom Appium is not configured for this hosted service. "
                "Choose BrowserStack or provide a reachable HTTPS Appium endpoint."
            )

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("Custom Appium endpoint must be a valid HTTP(S) URL.")
        if parsed.username or parsed.password:
            raise RuntimeError(
                "Do not embed Appium credentials in the URL; configure authentication at the tunnel or service layer."
            )
        hostname = parsed.hostname.lower()
        if self.settings.APP_ENV != "local" and hostname in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(
                "Hosted Autopilot cannot reach a laptop Appium server at 127.0.0.1. "
                "Use BrowserStack or an authenticated, reachable HTTPS Appium endpoint."
            )
        return value.rstrip("/")

    async def execute_smoke(self, job_id: str, request: AutopilotExecutionRequest) -> AutopilotExecutionResult:
        job = await self.load_job(job_id)
        analysis = await self.load_analysis(job_id)
        job_target_kind = str(job.get("target_kind") or analysis.target_kind or "android")
        target_kind = job_target_kind if job_target_kind != "android" and request.target_kind == "android" else request.target_kind
        if target_kind == "web":
            request = request.model_copy(update={
                "target_kind": "web",
                "provider": "playwright",
                "target_url": request.target_url or job.get("target_url"),
            })
        elif request.target_kind != target_kind:
            # A caller may reuse the Android-shaped default payload for an IPA
            # job. Normalize it from the durable job so Appium selects XCUITest
            # and the result remains truthful.
            request = request.model_copy(update={"target_kind": target_kind})
        started = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        execution_id = uuid4()
        evidence_dir = self._job_dir(job_id) / "evidence" / str(execution_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = evidence_dir / "launch.png"
        source_path = evidence_dir / ("page-source.html" if target_kind == "web" else "page-source.xml")

        try:
            if target_kind == "web":
                from app.services.autopilot_web import AutopilotWebService

                web_result = await AutopilotWebService(self.settings, self).smoke(job_id, request)
                result = dict(web_result.get("evidence") or {})
                result.update(
                    {
                        "provider": "playwright",
                        "target_kind": "web",
                        "target_url": web_result.get("target_url"),
                        "screenshot_path": web_result.get("screenshot_path"),
                        "page_source_path": web_result.get("page_source_path"),
                    }
                )
                execution_status = str(web_result.get("status") or "failed")
                error = web_result.get("error")
            else:
                apk_path = Path(job.get("apk_path") or "")
                if not apk_path.is_file() and not request.appium_app:
                    raise RuntimeError(
                        "The uploaded mobile artifact is unavailable after a service restart. "
                        "Upload the APK/IPA again before running smoke execution."
                    )
                app_reference = request.appium_app or str(apk_path)
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
                else:
                    # Hosted custom Appium must be explicitly configured/reachable.
                    appium_url = self.resolve_appium_url(request)

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
                result["target_kind"] = target_kind
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
            target_kind=target_kind,
            target_url=request.target_url or job.get("target_url"),
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
        is_ios = request.target_kind == "ios"
        capabilities: Dict[str, Any] = {
            "platformName": "iOS" if is_ios else "Android",
            "appium:automationName": "XCUITest" if is_ios else "UiAutomator2",
            "appium:deviceName": request.device_name,
            "appium:app": app_reference,
            "appium:noReset": request.no_reset,
            "appium:newCommandTimeout": 120,
        }
        if is_ios:
            capabilities.update(
                {
                    "appium:wdaLaunchTimeout": server_launch_timeout_ms,
                    "appium:wdaConnectionTimeout": adb_exec_timeout_ms,
                    "appium:useNewWDA": False,
                }
            )
        else:
            capabilities.update(
                {
                    "appium:autoGrantPermissions": request.auto_grant_permissions,
                    "appium:androidInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerInstallTimeout": install_timeout_ms,
                    "appium:uiautomator2ServerLaunchTimeout": server_launch_timeout_ms,
                    "appium:adbExecTimeout": adb_exec_timeout_ms,
                    "appium:appWaitDuration": adb_exec_timeout_ms,
                }
            )
        if request.platform_version:
            capabilities["appium:platformVersion"] = request.platform_version
        if browserstack_options:
            capabilities["bstack:options"] = browserstack_options

        if is_ios:
            from appium.options.ios import XCUITestOptions

            options = XCUITestOptions().load_capabilities(capabilities)
        else:
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options().load_capabilities(capabilities)
        driver = webdriver.Remote(appium_url, options=options)
        try:
            time.sleep(3)
            driver.get_screenshot_as_file(str(screenshot_path))
            page_source = safe_page_source(driver)
            source_path.write_text(page_source, encoding="utf-8")
            identity = safe_app_identity(
                driver,
                page_source=page_source,
                package_hint=expected_package,
            )
            current_package = identity.get("package")
            current_activity = identity.get("activity")
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
            safe_quit(driver)

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
                "custom appium is not configured",
                "custom appium endpoint",
                "hosted autopilot cannot reach",
                "unauthorized",
                "authentication",
            )
        )
