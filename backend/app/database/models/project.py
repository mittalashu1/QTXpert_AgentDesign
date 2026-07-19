"""Project model - the top-level container for requirements and test cases."""
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.requirement import Requirement
    from app.database.models.generation_run import GenerationRun


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    requirements: Mapped[List["Requirement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    generation_runs: Mapped[List["GenerationRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
