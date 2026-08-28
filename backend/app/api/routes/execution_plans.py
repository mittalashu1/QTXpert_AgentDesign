"""Import and control versioned Test Design suites for execution."""
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth_deps import get_current_user
from app.api.routes.executions import _compile_steps, _run_execution, _validated_target
from app.database.models.execution import ExecutionResult, ExecutionRun, ResultStatus
from app.database.models.execution_plan import ExecutionPlan, ExecutionPlanCase
from app.database.models.generation_run import GenerationRun, RunStatus
from app.database.models.project import Project
from app.database.models.test_case import TestCase
from app.database.models.user import User
from app.database.session import get_db_session
from app.schemas.execution import (
    ExecutionPlanCasesUpdate,
    ExecutionPlanExecute,
    ExecutionPlanImport,
    ExecutionPlanOut,
    ExecutionPlanPreflight,
    ExecutionPlanRerun,
    ExecutionRunOut,
)

router = APIRouter(tags=["execution-plans"])

_HIGH_IMPACT_STEP = re.compile(
    r"\b(delete|remove|withdraw|transfer|payment|pay|purchase|close account|send money|otp)\b",
    re.IGNORECASE,
)


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _source_title(run: GenerationRun) -> str:
    if run.title and run.title.strip():
        return run.title.strip()
    if run.requirement_summary and run.requirement_summary.strip():
        return run.requirement_summary.strip()[:500]
    return f"{run.generation_profile.replace('_', ' ').title()} test set"


async def _load_plan(db: AsyncSession, plan_id: UUID, user_id: UUID) -> ExecutionPlan:
    plan = await db.scalar(
        select(ExecutionPlan)
        .join(Project, ExecutionPlan.project_id == Project.id)
        .options(selectinload(ExecutionPlan.cases))
        .where(ExecutionPlan.id == plan_id, Project.owner_id == user_id)
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution plan not found")
    return plan


def _plan_payload(plan: ExecutionPlan) -> dict:
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "source_generation_run_id": plan.source_generation_run_id,
        "name": plan.name,
        "suite_type": plan.suite_type,
        "status": plan.status,
        "source_title": plan.source_title,
        "source_created_at": plan.source_created_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "total_cases": plan.total_cases,
        "selected_cases": plan.selected_cases,
        "selected_automated_cases": plan.selected_automated_cases,
        "ready_cases": plan.ready_cases,
        "blocked_cases": plan.blocked_cases,
        "cases": sorted(plan.cases, key=lambda item: item.selection_order),
    }


def _case_snapshot(test_case: TestCase, plan_id: UUID, index: int) -> ExecutionPlanCase:
    candidate = bool(test_case.is_automation_candidate)
    return ExecutionPlanCase(
        plan_id=plan_id,
        source_test_case_id=test_case.id,
        selection_order=index,
        selected=candidate,
        execution_mode="automated" if candidate else "manual",
        readiness="pending" if candidate else "manual_review",
        test_case_key=test_case.test_case_key,
        requirement_traceability=test_case.requirement_traceability,
        test_type=_value(test_case.test_type),
        scenario=test_case.scenario,
        objective=test_case.objective,
        priority=_value(test_case.priority),
        severity=_value(test_case.severity),
        preconditions=test_case.preconditions,
        test_data=test_case.test_data,
        steps=list(test_case.steps or []),
        expected_result=test_case.expected_result,
        post_conditions=test_case.post_conditions,
        is_automation_candidate=candidate,
        automation_type=test_case.automation_type,
        risk_level=_value(test_case.risk_level),
    )


async def _preflight_plan(
    plan: ExecutionPlan,
    base_url: str,
    *,
    case_ids: set[UUID] | None = None,
) -> None:
    """Compile selected cases without guessing unsupported actions."""
    for case in plan.cases:
        if case_ids is not None and case.id not in case_ids:
            continue
        if not case.selected and case_ids is None:
            case.readiness = "not_selected"
            case.blocker_reason = None
            continue
        if case.execution_mode != "automated":
            case.readiness = "manual_review"
            case.blocker_reason = "Imported for manual execution; select automated mode after converting the steps."
            continue
        if case.source_test_case_id is None:
            case.readiness = "blocked"
            case.blocker_reason = "The source Test Design case is no longer available. Re-import the Design run."
            continue
        impact = next((str(step).strip() for step in case.steps if _HIGH_IMPACT_STEP.search(str(step))), None)
        if impact:
            case.readiness = "approval_required"
            case.blocker_reason = f"Potentially business-impacting step requires approval: {impact}"
            continue
        try:
            _compile_steps(case.steps or [], base_url)
        except ValueError as exc:
            case.readiness = "blocked"
            case.blocker_reason = str(exc)
        else:
            case.readiness = "ready"
            case.blocker_reason = None

    considered = [
        case for case in plan.cases
        if (case_ids is None or case.id in case_ids)
        and (case.selected or case_ids is not None)
        and case.execution_mode == "automated"
    ]
    if not considered:
        plan.status = "draft"
    elif any(case.readiness == "ready" for case in considered):
        plan.status = "ready"
    else:
        plan.status = "blocked"


async def _queue_plan_execution(
    plan: ExecutionPlan,
    db: AsyncSession,
    background: BackgroundTasks,
    user: User,
    *,
    base_url: str,
    browser: str,
    name: str,
    case_ids: set[UUID] | None = None,
) -> ExecutionRun:
    await _preflight_plan(plan, base_url, case_ids=case_ids)
    automated = [
        case for case in plan.cases
        if (case_ids is None and case.selected or case_ids is not None and case.id in case_ids)
        and case.execution_mode == "automated"
    ]
    if not automated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one automated test case before running the plan.",
        )
    ready = [case for case in automated if case.readiness == "ready"]
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No selected test case is runnable. Resolve the preflight blockers or choose another case.",
        )
    missing_source = [case.test_case_key for case in automated if case.source_test_case_id is None]
    if missing_source:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"These imported cases no longer have a source Test Design record: {', '.join(missing_source)}",
        )

    plan.status = "queued"
    run = ExecutionRun(
        project_id=plan.project_id,
        requested_by_id=user.id,
        execution_plan_id=plan.id,
        name=name.strip() or plan.name,
        base_url=base_url,
        browser=browser,
        total_tests=len(automated),
    )
    db.add(run)
    await db.flush()
    for case in automated:
        blocked = case.readiness != "ready"
        db.add(
            ExecutionResult(
                execution_run_id=run.id,
                execution_plan_case_id=case.id,
                test_case_id=case.source_test_case_id,
                status=ResultStatus.BLOCKED if blocked else ResultStatus.PENDING,
                error_message=case.blocker_reason if blocked else None,
                evidence={"preflight": case.readiness} if blocked else None,
            )
        )
    await db.commit()
    persisted = await db.scalar(
        select(ExecutionRun)
        .options(
            selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
            selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
            selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
        )
        .where(ExecutionRun.id == run.id)
    )
    if persisted is None:  # pragma: no cover - the just-created row must exist
        raise HTTPException(status_code=500, detail="Execution run could not be loaded after creation")
    background.add_task(_run_execution, persisted.id)
    return persisted


@router.get("/execution-plans", response_model=list[ExecutionPlanOut])
async def list_execution_plans(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user.id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    plans = (
        await db.scalars(
            select(ExecutionPlan)
            .options(selectinload(ExecutionPlan.cases))
            .where(ExecutionPlan.project_id == project_id)
            .order_by(ExecutionPlan.created_at.desc())
        )
    ).unique().all()
    return [_plan_payload(plan) for plan in plans]


@router.post("/execution-plans/import", response_model=ExecutionPlanOut, status_code=status.HTTP_201_CREATED)
async def import_execution_plan(
    payload: ExecutionPlanImport,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    run = await db.scalar(
        select(GenerationRun)
        .join(Project, GenerationRun.project_id == Project.id)
        .options(selectinload(GenerationRun.test_cases))
        .where(
            GenerationRun.id == payload.generation_run_id,
            GenerationRun.project_id == payload.project_id,
            Project.owner_id == user.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test Design run not found")
    if run.status != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a completed Test Design run can be imported into execution.",
        )
    if not run.test_cases:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The selected Test Design run has no test cases")

    title = (payload.name or "").strip() or _source_title(run)
    plan = ExecutionPlan(
        project_id=run.project_id,
        source_generation_run_id=run.id,
        created_by_id=user.id,
        name=title,
        suite_type=payload.suite_type,
        status="draft",
        source_title=_source_title(run),
        source_created_at=run.created_at,
    )
    db.add(plan)
    await db.flush()
    for index, test_case in enumerate(sorted(run.test_cases, key=lambda item: item.created_at)):
        plan.cases.append(_case_snapshot(test_case, plan.id, index))
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.get("/execution-plans/{plan_id}", response_model=ExecutionPlanOut)
async def get_execution_plan(
    plan_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    return _plan_payload(await _load_plan(db, plan_id, user.id))


@router.patch("/execution-plans/{plan_id}/cases", response_model=ExecutionPlanOut)
async def update_execution_plan_cases(
    plan_id: UUID,
    payload: ExecutionPlanCasesUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    plan = await _load_plan(db, plan_id, user.id)
    if plan.status not in {"draft", "ready", "blocked"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A plan cannot be edited after execution has been queued. Import a new snapshot instead.",
        )
    updates = {item.id: item for item in payload.cases}
    if len(updates) != len(payload.cases):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate execution plan case IDs are not allowed")
    known = {case.id: case for case in plan.cases}
    unknown = [case_id for case_id in updates if case_id not in known]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more cases do not belong to this execution plan")
    for case_id, update in updates.items():
        case = known[case_id]
        case.selected = update.selected
        case.execution_mode = update.execution_mode
        case.readiness = "pending" if update.selected and update.execution_mode == "automated" else (
            "manual_review" if update.selected else "not_selected"
        )
        case.blocker_reason = None
    plan.status = "draft"
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.post("/execution-plans/{plan_id}/preflight", response_model=ExecutionPlanOut)
async def preflight_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanPreflight,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    plan = await _load_plan(db, plan_id, user.id)
    try:
        base_url = _validated_target(str(payload.base_url))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await _preflight_plan(plan, base_url)
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.post("/execution-plans/{plan_id}/execute", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def execute_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanExecute,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    plan = await _load_plan(db, plan_id, user.id)
    if plan.status in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This execution plan is already running")
    try:
        base_url = _validated_target(str(payload.base_url))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _queue_plan_execution(
        plan,
        db,
        background,
        user,
        base_url=base_url,
        browser=payload.browser,
        name=(payload.name or plan.name),
    )


@router.post("/execution-plans/{plan_id}/rerun", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def rerun_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanRerun,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    plan = await _load_plan(db, plan_id, user.id)
    source = await db.scalar(
        select(ExecutionRun)
        .join(Project, ExecutionRun.project_id == Project.id)
        .options(selectinload(ExecutionRun.results))
        .where(
            ExecutionRun.id == payload.source_execution_id,
            ExecutionRun.execution_plan_id == plan.id,
            Project.owner_id == user.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source execution run not found for this plan")
    case_ids = {result.execution_plan_case_id for result in source.results if result.execution_plan_case_id is not None}
    if not case_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The source run has no imported plan cases to rerun")
    return await _queue_plan_execution(
        plan,
        db,
        background,
        user,
        base_url=source.base_url,
        browser=source.browser,
        name=(payload.name or f"Rerun · {source.name}"),
        case_ids=case_ids,
    )

