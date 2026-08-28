"""Migrate legacy PostgreSQL upload chunks to an S3-compatible bucket.

Run from ``backend/`` after setting ``UPLOAD_STORAGE_BACKEND=object_store`` and
the object-store credentials in the environment.  The default mode is
non-destructive: it verifies the uploaded object and changes only the asset
metadata.  Pass ``--delete-chunks`` in a separate, reviewed run to reclaim the
old PostgreSQL binary rows.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import tempfile
from pathlib import Path

from sqlalchemy import delete, select

from app.config import get_settings
from app.database.models.uploaded_asset import UploadedAsset, UploadedAssetChunk
from app.database.session import AsyncSessionLocal
from app.services.object_storage import ObjectStorageService
from app.services.upload_repository import UploadRepositoryService

logger = logging.getLogger("migrate_uploaded_assets")


async def _materialize_legacy(db, asset: UploadedAsset, target: Path) -> None:
    hasher = hashlib.sha256()
    total = 0
    stream = await db.stream_scalars(
        select(UploadedAssetChunk.data)
        .where(UploadedAssetChunk.asset_id == asset.id)
        .order_by(UploadedAssetChunk.chunk_index)
    )
    with target.open("wb") as handle:
        async for chunk in stream:
            data = bytes(chunk)
            handle.write(data)
            hasher.update(data)
            total += len(data)

    if asset.size_bytes and total != asset.size_bytes:
        raise ValueError(
            f"{asset.filename}: size mismatch (metadata={asset.size_bytes}, chunks={total})"
        )
    if asset.sha256 and hasher.hexdigest() != asset.sha256:
        raise ValueError(f"{asset.filename}: SHA-256 mismatch while reading legacy chunks")


async def migrate(*, limit: int | None, delete_chunks: bool) -> int:
    settings = get_settings()
    storage = ObjectStorageService(settings)
    migrated = 0

    async with AsyncSessionLocal() as db:
        query = (
            select(UploadedAsset)
            .where(UploadedAsset.storage_backend == "postgres_chunks")
            .order_by(UploadedAsset.created_at.asc())
        )
        if limit:
            query = query.limit(limit)
        assets = list((await db.scalars(query)).all())

        for asset in assets:
            object_key = UploadRepositoryService._object_key(settings, asset)
            temporary_path: Path | None = None
            try:
                with tempfile.TemporaryDirectory(prefix="qtxpert-migrate-") as directory:
                    temporary_path = Path(directory) / Path(asset.filename).name
                    await _materialize_legacy(db, asset, temporary_path)
                    await storage.upload_path(
                        temporary_path,
                        object_key,
                        content_type=asset.content_type,
                    )
                    metadata = await storage.head(object_key)
                    content_length = metadata.get("ContentLength")
                    if content_length is not None and int(content_length) != int(asset.size_bytes):
                        raise ValueError(
                            f"{asset.filename}: object size mismatch after upload "
                            f"(metadata={asset.size_bytes}, object={content_length})"
                        )

                asset.storage_backend = "object_store"
                asset.object_key = object_key
                if delete_chunks:
                    await db.execute(
                        delete(UploadedAssetChunk).where(UploadedAssetChunk.asset_id == asset.id)
                    )
                await db.commit()
                migrated += 1
                logger.info(
                    "Migrated asset=%s filename=%s delete_chunks=%s",
                    asset.id,
                    asset.filename,
                    delete_chunks,
                )
            except Exception:
                await db.rollback()
                try:
                    await storage.delete(object_key)
                except Exception:
                    # The object may not have been created; leave it for a
                    # later inventory/cleanup pass rather than masking the
                    # original verification error.
                    pass
                raise

    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Migrate at most N assets")
    parser.add_argument(
        "--delete-chunks",
        action="store_true",
        help="Delete verified PostgreSQL chunk rows after each successful migration",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import asyncio

    count = asyncio.run(migrate(limit=args.limit, delete_chunks=args.delete_chunks))
    logger.info("Migrated %s asset(s)", count)


if __name__ == "__main__":
    main()
