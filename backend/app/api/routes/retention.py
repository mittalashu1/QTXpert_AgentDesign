"""Administrator-controlled retention for generated QTXpert data."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import require_roles
from app.config import Settings, get_settings
from app.database.models.config_and_audit import AuditLog
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.schemas.retention import RetentionCleanupRequest, RetentionSummaryOut
from app.services.data_retention import cleanup_generated_data

router = APIRouter(prefix="/admin/retention", tags=["admin"])


@router.get("/preview", response_model=RetentionSummaryOut)
async def preview_retention(
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Return the rows/assets eligible for cleanup without changing state."""
    del admin
    summary = await cleanup_generated_data(db, settings, dry_run=True)
    return RetentionSummaryOut.from_summary(summary)

@router.post("/cleanup", response_model=RetentionSummaryOut)
async def run_retention_cleanup(
    payload: RetentionCleanupRequest,
    request: Request,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Execute retention only after an administrator explicitly confirms it."""
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set confirm=true after reviewing GET /admin/retention/preview.",
        )
    summary = await cleanup_generated_data(
        db,
        settings,
        dry_run=False,
        days=payload.days,
        keep_latest=payload.keep_latest,
    )
    db.add(
        AuditLog(
            user_id=admin.id,
            action="generated_data_retention_cleanup",
            resource_type="retention",
            resource_id=None,
            detail={
                **summary.as_dict(),
                "request_path": request.url.path,
            },
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return RetentionSummaryOut.from_summary(summary)
