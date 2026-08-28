from pathlib import Path
from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user, require_roles
from app.config import Settings, get_settings
from app.database.models.requirement import RequirementSource
from app.database.models.user import User, UserRole
from app.database.repositories.requirement_repository import (
    ProjectRepository,
    RequirementRepository,
)
from app.database.session import get_db_session
from app.schemas.requirement import (
    DirectPromptRequest,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    RequirementOut,
)
from app.services.document_processor import UnsupportedDocumentTypeError, extract_text
from app.services.upload_repository import UploadRepositoryService, UploadRepositoryStorageUnavailable

router = APIRouter(tags=["requirements"])


async def _require_owned_project(db: AsyncSession, project_id: UUID, user_id: UUID) -> None:
    project = await ProjectRepository(db).get_for_owner(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo = ProjectRepository(db)
    return await repo.create(payload.name, payload.description, user.id)


@router.get("/projects", response_model=List[ProjectOut])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo = ProjectRepository(db)
    return await repo.list_for_owner(user.id)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    """Rename/update a project. Project metadata changes are admin-only."""
    repo = ProjectRepository(db)
    project = await repo.get_for_owner(project_id, user.id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name cannot be empty")
    return await repo.update(project, name=name, description=payload.description)


@router.get("/requirements", response_model=List[RequirementOut])
async def list_requirements(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    await _require_owned_project(db, project_id, user.id)
    repo = RequirementRepository(db)
    return await repo.list_for_project(project_id)


@router.post("/upload", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
async def upload_requirement(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
):
    """Upload a BRD/Jira/Confluence export and retain its original file for reuse."""
    await _require_owned_project(db, project_id, user.id)
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in settings.allowed_upload_extensions_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    total_bytes = 0
    while chunk := await file.read(1024 * 1024):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    filename = Path(file.filename or "upload").name
    try:
        text = extract_text(filename, data)
    except UnsupportedDocumentTypeError:
        text = (
            f"Binary product input uploaded: {filename}.\n"
            f"File type: {extension or 'unknown'}\n"
            "Generate coverage from the accompanying user guidance and treat "
            "this asset as the product under test."
        )
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file contains no readable text")
    if len(text) > settings.MAX_REQUIREMENT_TEXT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Extracted requirement text is too large for a single generation run",
        )

    try:
        asset = await UploadRepositoryService.create_from_bytes(
            db,
            data,
            user.id,
            filename=filename,
            content_type=file.content_type,
            project_id=project_id,
            source_module="design",
            category="document",
            max_bytes=max_bytes,
            settings=settings,
        )
    except UploadRepositoryStorageUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is temporarily unavailable; check object-storage configuration and retry.",
        ) from exc

    source = (
        RequirementSource.JIRA_EXPORT
        if filename.lower().endswith((".json", ".csv"))
        else RequirementSource.BRD_UPLOAD
    )

    repo = RequirementRepository(db)
    return await repo.create(
        project_id=project_id,
        title=filename,
        source=source,
        raw_content=text,
        source_file_path=f"upload:{asset.id}",
    )


@router.post("/requirements/direct-prompt", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
async def submit_direct_prompt(
    payload: DirectPromptRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Method 5 (direct user prompt with a large text editor)."""
    await _require_owned_project(db, payload.project_id, user.id)
    if len(payload.content) > settings.MAX_REQUIREMENT_TEXT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Requirement text is too large for a single generation run",
        )
    repo = RequirementRepository(db)
    return await repo.create(
        project_id=payload.project_id,
        title=payload.title,
        source=RequirementSource.DIRECT_PROMPT,
        raw_content=payload.content,
    )
