import logging
from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.execution import ExecutionResult
from app.database.models.generation_run import RunStatus
from app.database.models.user import User
from app.database.repositories.generation_run_repository import GenerationRunRepository
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import AsyncSessionLocal, get_db_session
from app.llm.base import LLMProviderError
from app.schemas.test_case import (
    GenerateTestCasesRequest,
    GenerationRunOut,
    GenerationRunSummaryOut,
    GenerationRunTitleUpdate,
    UpdateGenerationRunRequest,
)
from app.services.test_generation_service import TestGenerationService

router = APIRouter(tags=["test-cases"])
logger = logging.getLogger(__name__)


async def _require_owned_project(db: AsyncSession, project_id: UUID, user_id: UUID) -> None:
    if await ProjectRepository(db).get_for_owner(project_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


async def _continue_generation(
    run_id: UUID, project_id: UUID, requirement_ids: list[UUID] | None,
    requested_by_id: UUID, llm_provider_override: str | None, generation_profile: str,
) -> None:
    """Run independently of the HTTP response so the UI can poll progress."""
    async with AsyncSessionLocal() as session:
        service = TestGenerationService(session, get_settings())
        await service.execute(
            run_id, project_id, requirement_ids, requested_by_id, llm_provider_override,
            generation_profile,
        )
        logger.info("background_generation_finished run_id=%s", run_id)


@router.post("/generate-testcases", response_model=GenerationRunOut, status_code=status.HTTP_201_CREATED)
async def generate_testcases(
    payload: GenerateTestCasesRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Starts the AI workflow and immediately returns a run the UI can track."""
    await _require_owned_project(db, payload.project_id, user.id)
    service = TestGenerationService(db, settings)
    try:
        run = await service.create_run(
            project_id=payload.project_id,
            requested_by_id=user.id,
            requirement_ids=payload.requirement_ids or None,
            llm_provider_override=payload.llm_provider_override,
            generation_profile=payload.generation_profile,
            test_set_title=payload.test_set_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    background_tasks.add_task(
        _continue_generation, run.id, payload.project_id, payload.requirement_ids or None,
        user.id, payload.llm_provider_override, payload.generation_profile,
    )
    return run


@router.get("/history", response_model=List[GenerationRunOut])
async def history(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await _require_owned_project(db, project_id, user.id)
    repo = GenerationRunRepository(db)
    await repo.fail_stale_for_project(project_id, settings.GENERATION_STALE_AFTER_SECONDS)
    return await repo.list_for_project(project_id)


@router.get("/history-summaries", response_model=List[GenerationRunSummaryOut])
async def history_summaries(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Return lightweight project history for rails without hydrating test cases."""
    await _require_owned_project(db, project_id, user.id)
    repo = GenerationRunRepository(db)
    await repo.fail_stale_for_project(project_id, settings.GENERATION_STALE_AFTER_SECONDS)
    return await repo.list_summaries_for_project(project_id, limit=limit, offset=offset)


@router.get("/history/{run_id}", response_model=GenerationRunOut)
async def get_run(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    repo = GenerationRunRepository(db)
    run = await repo.get_for_owner(run_id, user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")
    await repo.fail_stale_for_project(run.project_id, settings.GENERATION_STALE_AFTER_SECONDS)
    run = await repo.get_for_owner(run_id, user.id)
    return run


@router.delete("/history/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Delete a saved test set while preserving execution evidence.

    A generation that is still running must not be removed because the
    background worker may still be writing to it. Likewise, a suite that has
    execution results is retained as audit evidence; its execution plans keep
    their snapshots even when a suite has no execution history.
    """
    repo = GenerationRunRepository(db)
    run = await repo.get_for_owner(run_id, user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")
    active_statuses = {
        RunStatus.PENDING,
        RunStatus.NORMALIZING,
        RunStatus.ANALYZING,
        RunStatus.GENERATING_SCENARIOS,
        RunStatus.GENERATING_TEST_CASES,
        RunStatus.RISK_ANALYSIS,
    }
    if run.status in active_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for generation to finish before deleting this test set.",
        )
    test_case_ids = [test_case.id for test_case in run.test_cases]
    if test_case_ids:
        linked_results = await db.scalar(
            select(func.count(ExecutionResult.id)).where(ExecutionResult.test_case_id.in_(test_case_ids))
        )
        if linked_results:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This test set has recorded execution results and cannot be deleted. Keep it for audit history.",
            )
    await db.delete(run)
    await db.commit()


@router.patch("/history/{run_id}/title", response_model=GenerationRunOut)
async def update_run_title(
    run_id: UUID,
    payload: GenerationRunTitleUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Rename a Test Design run without regenerating or changing its test cases."""
    repo = GenerationRunRepository(db)
    run = await repo.get_for_owner(run_id, user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Test run name cannot be empty")
    run.title = title
    await db.commit()
    await db.refresh(run, attribute_names=["test_cases"])
    return run


@router.patch("/history/{run_id}", response_model=GenerationRunOut)
async def update_run(
    run_id: UUID,
    payload: UpdateGenerationRunRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Persist inline Design Agent edits on the current run.

    The editor sends the existing test-case IDs. Updating those rows in place
    is intentional: editing a suite must never start another generation run or
    duplicate the suite in the run rail.
    """
    repo = GenerationRunRepository(db)
    run = await repo.get_for_owner(run_id, user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")
    if run.status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for generation to finish before saving test-case edits.",
        )

    existing = {test_case.id: test_case for test_case in run.test_cases}
    submitted_ids = [item.id for item in payload.test_cases]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate test-case IDs are not allowed")
    unknown_ids = [test_case_id for test_case_id in submitted_ids if test_case_id not in existing]
    if unknown_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more test cases do not belong to this run")
    missing_ids = set(existing).difference(submitted_ids)
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Send every test case in the suite when saving edits.",
        )

    for item in payload.test_cases:
        test_case = existing[item.id]
        scenario = item.scenario.strip()
        objective = item.objective.strip()
        expected_result = item.expected_result.strip()
        cleaned_steps = [step.strip() for step in item.steps if step.strip()]
        if not scenario or not objective or not expected_result or not cleaned_steps:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each test case needs a scenario, objective, expected result, and at least one step",
            )
        test_case.scenario = scenario
        test_case.objective = objective
        test_case.preconditions = (item.preconditions.strip() or None) if item.preconditions else None
        test_case.steps = cleaned_steps
        test_case.expected_result = expected_result

    await db.commit()
    await db.refresh(run, attribute_names=["test_cases"])
    return run

