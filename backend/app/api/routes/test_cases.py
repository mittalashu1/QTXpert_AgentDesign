from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.repositories.generation_run_repository import GenerationRunRepository
from app.database.session import get_db_session
from app.llm.base import LLMProviderError
from app.schemas.test_case import GenerateTestCasesRequest, GenerationRunOut
from app.services.test_generation_service import TestGenerationService

router = APIRouter(tags=["test-cases"])


@router.post("/generate-testcases", response_model=GenerationRunOut, status_code=status.HTTP_201_CREATED)
async def generate_testcases(
    payload: GenerateTestCasesRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Runs the full Step 1-11 AI workflow and persists the generated test cases."""
    service = TestGenerationService(db, settings)
    try:
        run = await service.run(
            project_id=payload.project_id,
            requested_by_id=user.id,
            requirement_ids=payload.requirement_ids or None,
            llm_provider_override=payload.llm_provider_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return run


@router.get("/history", response_model=List[GenerationRunOut])
async def history(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo = GenerationRunRepository(db)
    return await repo.list_for_project(project_id)


@router.get("/history/{run_id}", response_model=GenerationRunOut)
async def get_run(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo = GenerationRunRepository(db)
    run = await repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")
    return run
