"""Requirement model - normalized representation of any input source."""
import enum
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.project import Project


class RequirementSource(str, enum.Enum):
    BRD_UPLOAD = "brd_upload"
    JIRA_EXPORT = "jira_export"
    JIRA_LIVE = "jira_live"
    CONFLUENCE = "confluence"
    DIRECT_PROMPT = "direct_prompt"


class RequirementStatus(str, enum.Enum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    FAILED = "failed"


class Requirement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "requirements"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    external_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[RequirementSource] = mapped_column(
        Enum(RequirementSource, name="requirement_source"), nullable=False
    )
    status: Mapped[RequirementStatus] = mapped_column(
        Enum(RequirementStatus, name="requirement_status"),
        default=RequirementStatus.RECEIVED,
        nullable=False,
    )
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Structured extraction result: business rules, actors, acceptance
    # criteria, integrations, dependencies, validation & NFRs. Stored as
    # JSON so the shape can evolve without a migration.
    extracted_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    source_file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="requirements")
