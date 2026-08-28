"""Durable file repository shared by Design, Test Data and Autopilot.

PostgreSQL chunks remain a backwards-compatible read path for existing assets.
New deployments can select the S3-compatible object-store backend so large
APKs, documents and evidence do not consume Neon database storage or transfer.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import tempfile
from typing import AsyncIterator, Optional
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.models.uploaded_asset import UploadedAsset, UploadedAssetChunk
from app.services.object_storage import (
    ObjectStorageConfigurationError,
    ObjectStorageService,
)

logger = logging.getLogger(__name__)


class UploadRepositoryError(ValueError):
    pass


class UploadRepositoryTooLarge(UploadRepositoryError):
    pass


class UploadRepositoryInvalid(UploadRepositoryError):
    pass


class UploadRepositoryStorageUnavailable(UploadRepositoryError):
    """Raised when the selected object store is unavailable or misconfigured."""


class UploadRepositoryService:
    CHUNK_SIZE = 1024 * 1024

    DOCUMENT_EXTENSIONS = {"pdf", "docx", "txt", "md", "json", "csv"}
    TEST_DATA_EXTENSIONS = {"xlsx", "xls", "xml", "yaml", "yml"}
    MOBILE_EXTENSIONS = {"apk", "ipa"}
    MEDIA_EXTENSIONS = {"mp4", "mov", "webm", "png", "jpg", "jpeg"}

    @staticmethod
    def _settings(settings: Optional[Settings]) -> Settings:
        return settings or get_settings()

    @classmethod
    def _object_storage(cls, settings: Optional[Settings]) -> Optional[ObjectStorageService]:
        resolved = cls._settings(settings)
        if resolved.UPLOAD_STORAGE_BACKEND != "object_store":
            return None
        try:
            return ObjectStorageService(resolved)
        except ObjectStorageConfigurationError as exc:
            raise UploadRepositoryStorageUnavailable(str(exc)) from exc

    @staticmethod
    def _object_key(settings: Settings, asset: UploadedAsset) -> str:
        prefix = str(settings.OBJECT_STORAGE_PREFIX or "qtxpert").strip("/") or "qtxpert"
        # The asset UUID makes the key immutable and prevents filename/path
        # collisions.  The user-visible name remains metadata only.
        safe_name = Path(asset.filename).name.replace("/", "_").replace("\\", "_")
        project = str(asset.project_id or "unscoped")
        return f"{prefix}/projects/{project}/assets/{asset.id}/{safe_name}"

    @classmethod
    def category_for_filename(cls, filename: str) -> str:
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension == "apk":
            return "apk"
        if extension == "ipa":
            return "ipa"
        if extension in cls.DOCUMENT_EXTENSIONS:
            return "document"
        if extension in cls.TEST_DATA_EXTENSIONS:
            return "test_data"
        if extension in cls.MEDIA_EXTENSIONS:
            return "media"
        return "other"

    @classmethod
    async def create_from_upload(
        cls,
        db: AsyncSession,
        upload: UploadFile,
        owner_id: UUID,
        *,
        project_id: Optional[UUID] = None,
        source_module: str = "repository",
        category: Optional[str] = None,
        max_bytes: int,
        minimum_bytes: int = 1,
        settings: Optional[Settings] = None,
    ) -> UploadedAsset:
        # For object storage, spool the incoming body to a short-lived local
        # file and upload it from there.  This avoids ever inserting binary
        # chunks into Neon while keeping memory bounded for 250MB APKs.  A
        # future direct-upload UI can use the adapter's presigned URL methods
        # to bypass the API hop entirely.
        storage = cls._object_storage(settings)
        filename = Path(upload.filename or "upload").name
        if storage is not None:
            suffix = Path(filename).suffix or ".upload"
            fd, temporary_name = tempfile.mkstemp(prefix="qtxpert-upload-", suffix=suffix)
            os.close(fd)
            temporary_path = Path(temporary_name)
            total = 0
            try:
                with temporary_path.open("wb") as handle:
                    while chunk := await upload.read(cls.CHUNK_SIZE):
                        total += len(chunk)
                        if max_bytes and total > max_bytes:
                            raise UploadRepositoryTooLarge(
                                f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
                            )
                        handle.write(chunk)
                if total < minimum_bytes:
                    raise UploadRepositoryInvalid("Uploaded file is empty or invalid")
                return await cls.create_from_path(
                    db,
                    temporary_path,
                    owner_id,
                    filename=filename,
                    content_type=upload.content_type,
                    project_id=project_id,
                    source_module=source_module,
                    category=category,
                    max_bytes=max_bytes,
                    minimum_bytes=minimum_bytes,
                    settings=settings,
                )
            finally:
                temporary_path.unlink(missing_ok=True)

        asset = cls._new_asset(
            owner_id,
            filename,
            upload.content_type,
            project_id=project_id,
            source_module=source_module,
            category=category,
        )
        db.add(asset)
        await db.flush()

        hasher = hashlib.sha256()
        total = 0
        index = 0
        try:
            while chunk := await upload.read(cls.CHUNK_SIZE):
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise UploadRepositoryTooLarge(
                        f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
                    )
                hasher.update(chunk)
                db.add(
                    UploadedAssetChunk(
                        asset_id=asset.id,
                        chunk_index=index,
                        data=chunk,
                        size_bytes=len(chunk),
                    )
                )
                index += 1
                if index % 12 == 0:
                    await db.flush()

            if total < minimum_bytes:
                raise UploadRepositoryInvalid("Uploaded file is empty or invalid")
            asset.size_bytes = total
            asset.sha256 = hasher.hexdigest()
            asset.status = "ready"
            await db.commit()
            await db.refresh(asset)
            return asset
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def create_from_path(
        cls,
        db: AsyncSession,
        path: Path,
        owner_id: UUID,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        project_id: Optional[UUID] = None,
        source_module: str = "repository",
        category: Optional[str] = None,
        max_bytes: int = 0,
        minimum_bytes: int = 1,
        settings: Optional[Settings] = None,
    ) -> UploadedAsset:
        resolved_settings = cls._settings(settings)
        storage = cls._object_storage(resolved_settings)
        safe_name = Path(filename or path.name).name
        asset = cls._new_asset(
            owner_id,
            safe_name,
            content_type,
            project_id=project_id,
            source_module=source_module,
            category=category,
        )
        db.add(asset)
        await db.flush()

        hasher = hashlib.sha256()
        total = 0
        index = 0
        object_key: Optional[str] = None
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(cls.CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise UploadRepositoryTooLarge(
                            f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
                        )
                    hasher.update(chunk)
                    if storage is None:
                        db.add(
                            UploadedAssetChunk(
                                asset_id=asset.id,
                                chunk_index=index,
                                data=chunk,
                                size_bytes=len(chunk),
                            )
                        )
                    index += 1
                    if storage is None and index % 12 == 0:
                        await db.flush()

            if total < minimum_bytes:
                raise UploadRepositoryInvalid("Uploaded file is empty or invalid")
            asset.size_bytes = total
            asset.sha256 = hasher.hexdigest()
            asset.status = "ready"
            if storage is not None:
                object_key = cls._object_key(resolved_settings, asset)
                try:
                    await storage.upload_path(
                        path,
                        object_key,
                        content_type=content_type,
                    )
                except Exception as exc:
                    raise UploadRepositoryStorageUnavailable(
                        f"Object storage upload failed for {safe_name}: {exc}"
                    ) from exc
                asset.storage_backend = "object_store"
                asset.object_key = object_key
            await db.commit()
            await db.refresh(asset)
            return asset
        except Exception:
            await db.rollback()
            if storage is not None and object_key:
                try:
                    await storage.delete(object_key)
                except Exception as cleanup_error:  # pragma: no cover - defensive cleanup
                    logger.warning("Object storage cleanup failed for %s: %s", object_key, cleanup_error)
            raise

    @classmethod
    async def create_from_bytes(
        cls,
        db: AsyncSession,
        data: bytes,
        owner_id: UUID,
        *,
        filename: str,
        content_type: Optional[str] = None,
        project_id: Optional[UUID] = None,
        source_module: str = "design",
        category: Optional[str] = None,
        max_bytes: int = 0,
        settings: Optional[Settings] = None,
    ) -> UploadedAsset:
        if max_bytes and len(data) > max_bytes:
            raise UploadRepositoryTooLarge(
                f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
            )
        if not data:
            raise UploadRepositoryInvalid("Uploaded file is empty or invalid")

        storage = cls._object_storage(settings)

        asset = cls._new_asset(
            owner_id,
            Path(filename).name,
            content_type,
            project_id=project_id,
            source_module=source_module,
            category=category,
        )
        asset.size_bytes = len(data)
        asset.sha256 = hashlib.sha256(data).hexdigest()
        asset.status = "ready"
        db.add(asset)
        await db.flush()
        object_key: Optional[str] = None
        try:
            if storage is None:
                for index, start in enumerate(range(0, len(data), cls.CHUNK_SIZE)):
                    chunk = data[start : start + cls.CHUNK_SIZE]
                    db.add(
                        UploadedAssetChunk(
                            asset_id=asset.id,
                            chunk_index=index,
                            data=chunk,
                            size_bytes=len(chunk),
                        )
                    )
            else:
                object_key = cls._object_key(cls._settings(settings), asset)
                try:
                    await storage.upload_bytes(
                        data,
                        object_key,
                        content_type=content_type,
                    )
                except Exception as exc:
                    raise UploadRepositoryStorageUnavailable(
                        f"Object storage upload failed for {asset.filename}: {exc}"
                    ) from exc
                asset.storage_backend = "object_store"
                asset.object_key = object_key
            await db.commit()
            await db.refresh(asset)
            return asset
        except Exception:
            await db.rollback()
            if storage is not None and object_key:
                try:
                    await storage.delete(object_key)
                except Exception as cleanup_error:  # pragma: no cover - defensive cleanup
                    logger.warning("Object storage cleanup failed for %s: %s", object_key, cleanup_error)
            raise

    @staticmethod
    def _new_asset(
        owner_id: UUID,
        filename: str,
        content_type: Optional[str],
        *,
        project_id: Optional[UUID],
        source_module: str,
        category: Optional[str],
    ) -> UploadedAsset:
        extension = Path(filename).suffix.lower().lstrip(".")
        return UploadedAsset(
            owner_id=owner_id,
            project_id=project_id,
            filename=filename,
            extension=extension,
            content_type=content_type,
            category=category or UploadRepositoryService.category_for_filename(filename),
            source_module=source_module[:80],
            storage_backend="postgres_chunks",
            size_bytes=0,
            sha256="",
            status="uploading",
        )

    @staticmethod
    async def get_owned(db: AsyncSession, asset_id: UUID, owner_id: UUID) -> Optional[UploadedAsset]:
        return await db.scalar(
            select(UploadedAsset).where(
                UploadedAsset.id == asset_id,
                UploadedAsset.owner_id == owner_id,
                UploadedAsset.status == "ready",
            )
        )

    @staticmethod
    async def list_owned(
        db: AsyncSession,
        owner_id: UUID,
        *,
        category: Optional[str] = None,
        extension: Optional[str] = None,
        project_id: Optional[UUID] = None,
        limit: int = 200,
    ) -> list[UploadedAsset]:
        query = select(UploadedAsset).where(
            UploadedAsset.owner_id == owner_id,
            UploadedAsset.status == "ready",
        )
        if category:
            query = query.where(UploadedAsset.category == category)
        if extension:
            query = query.where(UploadedAsset.extension == extension.lower().lstrip("."))
        if project_id:
            query = query.where(UploadedAsset.project_id == project_id)
        result = await db.scalars(query.order_by(UploadedAsset.created_at.desc()).limit(limit))
        return list(result.all())

    @classmethod
    async def delete_owned(
        cls,
        db: AsyncSession,
        asset_id: UUID,
        owner_id: UUID,
        *,
        settings: Optional[Settings] = None,
    ) -> bool:
        asset = await db.scalar(
            select(UploadedAsset).where(
                UploadedAsset.id == asset_id,
                UploadedAsset.owner_id == owner_id,
            )
        )
        if asset is None:
            return False

        storage: Optional[ObjectStorageService] = None
        if asset.storage_backend == "object_store":
            resolved_settings = cls._settings(settings)
            if resolved_settings.UPLOAD_STORAGE_BACKEND != "object_store":
                raise UploadRepositoryStorageUnavailable(
                    "The asset uses object storage but the object-store backend is disabled"
                )
            storage = cls._object_storage(resolved_settings)
        if storage is not None and asset.object_key:
            try:
                await storage.delete(asset.object_key)
            except Exception as exc:
                # Do not remove metadata while the object deletion is
                # uncertain; the caller can retry safely.
                raise UploadRepositoryStorageUnavailable(
                    f"Object storage deletion failed for {asset.filename}: {exc}"
                ) from exc
        await db.delete(asset)
        await db.commit()
        return True

    @classmethod
    async def iter_content(
        cls,
        db: AsyncSession,
        asset_id: UUID,
        *,
        settings: Optional[Settings] = None,
    ) -> AsyncIterator[bytes]:
        asset = await db.scalar(select(UploadedAsset).where(UploadedAsset.id == asset_id))
        if asset is None:
            return
        if asset.storage_backend == "object_store":
            if not asset.object_key:
                return
            storage = cls._object_storage(settings)
            if storage is None:  # pragma: no cover - metadata/config mismatch
                raise UploadRepositoryStorageUnavailable(
                    "The asset uses object storage but the object-store backend is disabled"
                )
            async for data in storage.iter_content(asset.object_key):
                yield data
            return

        stream = await db.stream_scalars(
            select(UploadedAssetChunk.data)
            .where(UploadedAssetChunk.asset_id == asset_id)
            .order_by(UploadedAssetChunk.chunk_index)
        )
        async for data in stream:
            yield bytes(data)

    @classmethod
    async def materialize(
        cls,
        db: AsyncSession,
        asset_id: UUID,
        owner_id: UUID,
        target_path: Path,
        settings: Optional[Settings] = None,
    ) -> UploadedAsset:
        asset = await cls.get_owned(db, asset_id, owner_id)
        if asset is None:
            raise FileNotFoundError(str(asset_id))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_suffix(target_path.suffix + ".part")
        try:
            with temporary.open("wb") as handle:
                async for chunk in cls.iter_content(db, asset.id, settings=settings):
                    handle.write(chunk)
            temporary.replace(target_path)
            return asset
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
