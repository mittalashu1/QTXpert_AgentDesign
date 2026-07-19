"""User and role-based access models."""
import enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.project import Project
    from app.database.models.config_and_audit import AuditLog


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    QA_LEAD = "qa_lead"
    QA_ENGINEER = "qa_engineer"
    BUSINESS_ANALYST = "business_analyst"
    AUTOMATION_ENGINEER = "automation_engineer"
    VIEWER = "viewer"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
    Enum(UserRole, name="user_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
    nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_sso_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entra_object_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    projects: Mapped[List["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")
