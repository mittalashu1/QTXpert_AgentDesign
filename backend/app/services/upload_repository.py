"""Durable file repository shared by Design, Test Data and Autopilot.

The first storage backend uses bounded PostgreSQL binary chunks. That gives the
existing Render deployment durable reuse immediately without requiring another
cloud account. The metadata explicitly records the backend so the chunk store
can later be replaced by Azure Blob/S3 without changing module APIs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.uploaded_asset import UploadedAsset, UploadedAssetChunk


class UploadRepositoryError(ValueError):
    pass


class UploadRepositoryTooLarge(UploadRepositoryError):
    pass


class UploadRepositoryInvalid(UploadRepositoryError):
    pass


class UploadRepositoryService:
    CHUNK_SIZE = 1024 * 1024

    DOCUMENT_EXTENSIONS = {"pdf", "docx", "txt", "md", "json", "csv"}
    TEST_DATA_EXTENSIONS = {"xlsx", "xls", "xml", "yaml", "yml"}
    MOBILE_EXTENSIONS = {"apk", "ipa"}
    MEDIA_EXTENSIONS = {"mp4", "mov", "webm", "png", "jpg", "jpeg"}

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
    ) -> UploadedAsset:
        filename = Path(upload.filename or "upload").name
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
    ) -> UploadedAsset:
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
    ) -> UploadedAsset:
        if max_bytes and len(data) > max_bytes:
            raise UploadRepositoryTooLarge(
                f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
            )
        if not data:
            raise UploadRepositoryInvalid("Uploaded file is empty or invalid")

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
        await db.commit()
        await db.refresh(asset)
        return asset

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

    @staticmethod
    async def delete_owned(db: AsyncSession, asset_id: UUID, owner_id: UUID) -> bool:
        result = await db.execute(
            delete(UploadedAsset).where(
                UploadedAsset.id == asset_id,
                UploadedAsset.owner_id == owner_id,
            )
        )
        await db.commit()
        return bool(result.rowcount)

    @staticmethod
    async def iter_content(db: AsyncSession, asset_id: UUID) -> AsyncIterator[bytes]:
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
    ) -> UploadedAsset:
        asset = await cls.get_owned(db, asset_id, owner_id)
        if asset is None:
            raise FileNotFoundError(str(asset_id))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_suffix(target_path.suffix + ".part")
        try:
            with temporary.open("wb") as handle:
                async for chunk in cls.iter_content(db, asset.id):
                    handle.write(chunk)
            temporary.replace(target_path)
            return asset
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
