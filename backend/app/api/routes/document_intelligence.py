"""Authenticated APIs for QTXpert AI Document Intelligence."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import get_db_session
from app.schemas.document_intelligence import (
    DocumentAnalysisRunOut,
    DocumentAnalyzeRequest,
    DocumentFindingOut,
    FindingReviewRequest,
    PublishIntelligenceResponse,
)
from app.services.document_intelligence import DocumentIntelligenceService

router = APIRouter(prefix="/document-intelligence", tags=["document-intelligence"])


async def _require_owned_project(db: AsyncSession, project_id: UUID, user_id: UUID) -> None:
    if await ProjectRepository(db).get_for_owner(project_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post("/analyze", response_model=DocumentAnalysisRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_document_analysis(
    payload: DocumentAnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Create an AI documentation-quality review and return immediately for polling."""
    await _require_owned_project(db, payload.project_id, user.id)
    service = DocumentIntelligenceService(db, settings)
    try:
        run = await service.create_run(
            project_id=payload.project_id,
            requested_by_id=user.id,
            asset_ids=payload.asset_ids,
            profile=payload.profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    background_tasks.add_task(
        service.analyze_safely,
        run.id,
        payload.additional_context,
    )
    return run


@router.get("/runs/latest", response_model=DocumentAnalysisRunOut | None)
async def latest_document_analysis(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await _require_owned_project(db, project_id, user.id)
    return await DocumentIntelligenceService(db, settings).latest_run(project_id, user.id)


@router.get("/runs/{run_id}", response_model=DocumentAnalysisRunOut)
async def get_document_analysis(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        return await DocumentIntelligenceService(db, settings).get_run(run_id, user.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document analysis run not found")


@router.patch("/findings/{finding_id}", response_model=DocumentFindingOut)
async def review_document_finding(
    finding_id: UUID,
    payload: FindingReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        return await DocumentIntelligenceService(db, settings).review_finding(
            finding_id,
            user.id,
            status=payload.status,
            resolution_note=payload.resolution_note,
            suggested_refinement=payload.suggested_refinement,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document finding not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/runs/{run_id}/publish", response_model=PublishIntelligenceResponse)
async def publish_document_intelligence(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Publish reviewed intelligence as the canonical Test Design input for the project."""
    service = DocumentIntelligenceService(db, settings)
    try:
        requirement = await service.publish_to_test_design(run_id, user.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document analysis run not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PublishIntelligenceResponse(
        run_id=run_id,
        requirement_id=requirement.id,
        title=requirement.title,
        message="Document Intelligence baseline is now available to Test Design.",
    )
