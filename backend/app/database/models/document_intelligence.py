"""AI Document Intelligence persistence models.

Document Intelligence is intentionally separate from raw file storage and from
Test Design. UploadRepository owns bytes; these models own analysis state,
quality/readiness scores, evidence-backed findings and human review status.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


class DocumentAnalysisRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One AI review of a project's selected documentation baseline."""

    __tablename__ = "document_analysis_runs"
    __table_args__ = (
        Index("ix_document_analysis_project_created", "project_id", "created_at"),
        Index("ix_document_analysis_requester_created", "requested_by_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    profile: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    asset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # AI/deterministic outputs. JSON is intentional because the intelligence
    # schema will evolve faster than the relational core during the prototype.
    document_inventory: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    knowledge_model: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    missing_documents: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    readiness_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_analyzed")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_requirement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )

    findings: Mapped[list["DocumentFinding"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentFinding.created_at",
    )


class DocumentFinding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One evidence-backed documentation gap, inconsistency or improvement."""

    __tablename__ = "document_findings"
    __table_args__ = (
        Index("ix_document_findings_run_severity", "run_id", "severity"),
        Index("ix_document_findings_asset", "asset_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("uploaded_assets.id", ondelete="SET NULL"), nullable=True
    )
    finding_key: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    testing_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_refinement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped[DocumentAnalysisRun] = relationship(back_populates="findings")
