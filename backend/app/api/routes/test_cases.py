from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.repositories.generation_run_repository import GenerationRunRepository
from app.database.session import AsyncSessionLocal, get_db_session
from app.llm.base import LLMProviderError
from app.schemas.test_case import GenerateTestCasesRequest, GenerationRunOut
from app.services.test_generation_service import TestGenerationService

router = APIRouter(tags=["test-cases"])


async def _continue_generation(
    run_id: UUID, project_id: UUID, requirement_ids: list[UUID] | None,
    requested_by_id: UUID, llm_provider_override: str | None,
) -> None:
    """Run independently of the HTTP response so the UI can poll progress."""
    async with AsyncSessionLocal() as session:
        service = TestGenerationService(session, get_settings())
        await service.execute(
            run_id, project_id, requirement_ids, requested_by_id, llm_provider_override
        )


@router.post("/generate-testcases", response_model=GenerationRunOut, status_code=status.HTTP_201_CREATED)
async def generate_testcases(
    payload: GenerateTestCasesRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Starts the AI workflow and immediately returns a run the UI can track."""
    service = TestGenerationService(db, settings)
    try:
        run = await service.create_run(
            project_id=payload.project_id,
            requested_by_id=user.id,
            requirement_ids=payload.requirement_ids or None,
            llm_provider_override=payload.llm_provider_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    background_tasks.add_task(
        _continue_generation, run.id, payload.project_id, payload.requirement_ids or None,
        user.id, payload.llm_provider_override,
    )
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

