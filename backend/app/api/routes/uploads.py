"""Project-scoped Upload Repository APIs shared by QTXpert modules."""
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import AsyncSessionLocal, get_db_session
from app.schemas.upload_repository import UploadedAssetOut
from app.services.upload_repository import (
    UploadRepositoryInvalid,
    UploadRepositoryService,
    UploadRepositoryTooLarge,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


async def _resolve_project(
    db: AsyncSession,
    owner_id: UUID,
    explicit_project_id: Optional[UUID],
    header_project_id: Optional[str],
) -> UUID:
    project_id = explicit_project_id
    if project_id is None and header_project_id:
        try:
            project_id = UUID(header_project_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project context") from exc
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a project before using the Upload Repository")
    if await ProjectRepository(db).get_for_owner(project_id, owner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project_id


async def _owned_project_asset(db: AsyncSession, asset_id: UUID, owner_id: UUID, project_id: UUID):
    asset = await UploadRepositoryService.get_owned(db, asset_id, owner_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found in this project")
    return asset


@router.get("", response_model=list[UploadedAssetOut])
async def list_uploads(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    category: Optional[str] = None,
    extension: Optional[str] = None,
    project_id: Optional[UUID] = None,
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """List reusable files for the active project only."""
    active_project_id = await _resolve_project(db, user.id, project_id, x_qtxpert_project_id)
    return await UploadRepositoryService.list_owned(
        db,
        user.id,
        category=category,
        extension=extension,
        project_id=active_project_id,
    )


@router.post("", response_model=UploadedAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_to_repository(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    project_id: Optional[UUID] = Form(default=None),
    source_module: str = Form(default="test_data"),
    category: Optional[str] = Form(default=None),
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Store a reusable file in the active project's repository."""
    active_project_id = await _resolve_project(db, user.id, project_id, x_qtxpert_project_id)
    filename = Path(file.filename or "upload").name
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in settings.allowed_upload_extensions_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    is_mobile_binary = extension in {"apk", "ipa"}
    max_mb = settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB if is_mobile_binary else settings.MAX_UPLOAD_SIZE_MB
    try:
        return await UploadRepositoryService.create_from_upload(
            db,
            file,
            user.id,
            project_id=active_project_id,
            source_module=source_module,
            category=category,
            max_bytes=max_mb * 1024 * 1024,
            minimum_bytes=1024 if is_mobile_binary else 1,
        )
    except UploadRepositoryTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    except UploadRepositoryInvalid as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{asset_id}/content")
async def download_upload(
    asset_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    active_project_id = await _resolve_project(db, user.id, None, x_qtxpert_project_id)
    asset = await _owned_project_asset(db, asset_id, user.id, active_project_id)
    filename = asset.filename
    content_type = asset.content_type or "application/octet-stream"
    owner_id = user.id

    async def body():
        async with AsyncSessionLocal() as session:
            owned = await UploadRepositoryService.get_owned(session, asset_id, owner_id)
            if owned is None or owned.project_id != active_project_id:
                return
            async for chunk in UploadRepositoryService.iter_content(session, asset_id):
                yield chunk

    safe_filename = filename.replace('"', "")
    return StreamingResponse(
        body(),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    asset_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    active_project_id = await _resolve_project(db, user.id, None, x_qtxpert_project_id)
    await _owned_project_asset(db, asset_id, user.id, active_project_id)
    deleted = await UploadRepositoryService.delete_owned(db, asset_id, user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
