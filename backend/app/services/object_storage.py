"""S3-compatible object storage adapter for durable QTXpert artifacts.

The Upload Repository keeps relational metadata in PostgreSQL, but large
artifacts (APK/IPA binaries, screenshots, page sources and videos) belong in
object storage.  This adapter intentionally uses the S3 API so it works with
Amazon S3, Cloudflare R2, MinIO and other compatible providers without tying
the application to one vendor.

The adapter is optional.  When the provider is not configured the repository
continues to use its legacy PostgreSQL chunk backend, which keeps existing
deployments and old assets readable during migration.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aioboto3


class ObjectStorageConfigurationError(RuntimeError):
    """Raised when object storage is selected but its credentials are absent."""


class ObjectStorageService:
    """Small async S3 API wrapper with bounded transfer settings."""

    STREAM_CHUNK_SIZE = 1024 * 1024

    def __init__(self, settings: Any):
        self.settings = settings
        if not self.is_configured(settings):
            raise ObjectStorageConfigurationError(
                "Object storage is enabled but OBJECT_STORAGE_BUCKET, "
                "OBJECT_STORAGE_ACCESS_KEY_ID and OBJECT_STORAGE_SECRET_ACCESS_KEY "
                "are not configured"
            )

    @staticmethod
    def is_configured(settings: Any) -> bool:
        return bool(
            getattr(settings, "OBJECT_STORAGE_BUCKET", None)
            and getattr(settings, "OBJECT_STORAGE_ACCESS_KEY_ID", None)
            and getattr(settings, "OBJECT_STORAGE_SECRET_ACCESS_KEY", None)
        )

    @property
    def bucket(self) -> str:
        return str(self.settings.OBJECT_STORAGE_BUCKET)

    def _client(self):
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": str(getattr(self.settings, "OBJECT_STORAGE_REGION", "auto")),
            "aws_access_key_id": str(self.settings.OBJECT_STORAGE_ACCESS_KEY_ID),
            "aws_secret_access_key": str(self.settings.OBJECT_STORAGE_SECRET_ACCESS_KEY),
        }
        endpoint = getattr(self.settings, "OBJECT_STORAGE_ENDPOINT_URL", None)
        if endpoint:
            kwargs["endpoint_url"] = str(endpoint)
        return aioboto3.Session().client(**kwargs)

    async def upload_path(
        self,
        path: Path,
        object_key: str,
        *,
        content_type: Optional[str] = None,
    ) -> None:
        """Upload a local file using a bounded multipart transfer."""
        # boto3 is a transitive dependency of aioboto3.  Importing it lazily
        # keeps local/test environments that do not enable object storage
        # lightweight while preserving multipart support in production.
        from boto3.s3.transfer import TransferConfig

        threshold = int(getattr(self.settings, "OBJECT_STORAGE_MULTIPART_THRESHOLD_MB", 16)) * 1024 * 1024
        part_size = int(getattr(self.settings, "OBJECT_STORAGE_PART_SIZE_MB", 16)) * 1024 * 1024
        transfer_config = TransferConfig(
            multipart_threshold=threshold,
            multipart_chunksize=part_size,
            max_concurrency=2,
        )
        extra_args = {"ContentType": content_type} if content_type else None
        async with self._client() as client:
            await client.upload_file(
                str(path),
                self.bucket,
                object_key,
                ExtraArgs=extra_args,
                Config=transfer_config,
            )

    async def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        *,
        content_type: Optional[str] = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": object_key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        async with self._client() as client:
            await client.put_object(**kwargs)

    async def head(self, object_key: str) -> dict[str, Any]:
        async with self._client() as client:
            return await client.head_object(Bucket=self.bucket, Key=object_key)

    async def delete(self, object_key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=object_key)

    async def iter_content(self, object_key: str) -> AsyncIterator[bytes]:
        """Yield an object without loading it into process memory."""
        async with self._client() as client:
            response = await client.get_object(Bucket=self.bucket, Key=object_key)
            body = response["Body"]
            try:
                while True:
                    chunk = body.read(self.STREAM_CHUNK_SIZE)
                    if inspect.isawaitable(chunk):
                        chunk = await chunk
                    if not chunk:
                        break
                    yield bytes(chunk)
            finally:
                close = getattr(body, "close", None)
                if close:
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    async def presigned_upload_url(
        self,
        object_key: str,
        *,
        content_type: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> str:
        """Create a short-lived direct browser upload URL."""
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type
        ttl = int(
            expires_in
            if expires_in is not None
            else getattr(self.settings, "OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS", 900)
        )
        async with self._client() as client:
            value = client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=ttl,
            )
            if inspect.isawaitable(value):
                value = await value
            return str(value)

    async def presigned_download_url(
        self,
        object_key: str,
        *,
        expires_in: Optional[int] = None,
    ) -> str:
        """Create a short-lived download URL for an object."""
        ttl = int(
            expires_in
            if expires_in is not None
            else getattr(self.settings, "OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS", 900)
        )
        async with self._client() as client:
            value = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=ttl,
            )
            if inspect.isawaitable(value):
                value = await value
            return str(value)
