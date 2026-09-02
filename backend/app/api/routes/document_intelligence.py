"""Authenticated APIs for QTXpert AI Document Intelligence."""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import AsyncSessionLocal, get_db_session
from app.llm.base import LLMProviderError
from app.schemas.document_intelligence import (
    DocumentAnalysisRunOut,
    DocumentAnalyzeRequest,
    DocumentFindingOut,
    DocumentContextOut,
    DocumentTraceabilityOut,
    DocumentGenerateTestsRequest,
    DocumentGenerateTestsResponse,
    FindingReviewRequest,
    PublishIntelligenceResponse,
)
from app.services.document_intelligence import DocumentIntelligenceService
from app.services.test_generation_service import TestGenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/document-intelligence", tags=["document-intelligence"])


async def _continue_document_generation(
    generation_run_id: UUID,
    project_id: UUID,
    requirement_id: UUID,
    requested_by_id: UUID,
    generation_profile: str,
) -> None:
    """Execute a linked Test Design run outside the request lifecycle."""
    async with AsyncSessionLocal() as session:
        try:
            await TestGenerationService(session, get_settings()).execute(
                generation_run_id,
                project_id,
                [requirement_id],
                requested_by_id,
                generation_profile=generation_profile,
            )
            logger.info("document_linked_generation_finished run_id=%s", generation_run_id)
        except Exception:  # noqa: BLE001 - service persists the terminal failure
            logger.exception("document_linked_generation_failed run_id=%s", generation_run_id)


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
            additional_context=payload.additional_context,
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


@router.get("/runs/{run_id}/context", response_model=DocumentContextOut)
async def get_document_analysis_context(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Return the bounded evidence context used by Autopilot/Test Design."""
    try:
        return await DocumentIntelligenceService(db, settings).get_context(run_id, user.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document analysis run not found")


@router.get("/runs/{run_id}/traceability", response_model=DocumentTraceabilityOut)
async def get_document_analysis_traceability(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Show delivery from document findings through design and execution."""
    try:
        return await DocumentIntelligenceService(db, settings).get_traceability(run_id, user.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document analysis run not found")


@router.post("/runs/{run_id}/generate-tests", response_model=DocumentGenerateTestsResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_tests_from_document_analysis(
    run_id: UUID,
    payload: DocumentGenerateTestsRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Create a Test Design run with immutable Document Intelligence lineage."""
    service = DocumentIntelligenceService(db, settings)
    try:
        analysis_run, requirement, generation = await service.create_test_design_run(
            run_id,
            user.id,
            generation_profile=payload.generation_profile,
            test_set_title=payload.test_set_title,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document analysis run not found")
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    background_tasks.add_task(
        _continue_document_generation,
        generation.id,
        analysis_run.project_id,
        requirement.id,
        user.id,
        payload.generation_profile,
    )
    return DocumentGenerateTestsResponse(
        run_id=run_id,
        generation_run_id=generation.id,
        requirement_id=requirement.id,
        status=str(getattr(generation.status, "value", generation.status)),
        title=generation.title,
        message="Test Design generation started from the Document Intelligence baseline.",
    )


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
