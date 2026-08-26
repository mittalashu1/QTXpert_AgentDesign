"""Durable, reusable file assets shared across QTXpert modules."""
import uuid
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


class UploadedAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Metadata for one original file uploaded to QTXpert."""

    __tablename__ = "uploaded_assets"
    __table_args__ = (
        Index("ix_uploaded_assets_owner_created", "owner_id", "created_at"),
        Index("ix_uploaded_assets_owner_category", "owner_id", "category"),
        Index("ix_uploaded_assets_project_created", "project_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    source_module: Mapped[str] = mapped_column(String(80), nullable=False, default="repository")
    storage_backend: Mapped[str] = mapped_column(String(30), nullable=False, default="postgres_chunks")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")

    chunks: Mapped[list["UploadedAssetChunk"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="UploadedAssetChunk.chunk_index",
    )


class UploadedAssetChunk(Base):
    """Bounded binary chunks keep large APK uploads out of process memory."""

    __tablename__ = "uploaded_asset_chunks"
    __table_args__ = (
        Index("ix_uploaded_asset_chunks_asset_order", "asset_id", "chunk_index"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    asset: Mapped[UploadedAsset] = relationship(back_populates="chunks")
