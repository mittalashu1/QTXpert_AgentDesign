"""Playwright-first execution, reporting, and embedded defect logging."""
import ipaddress
import socket
import time
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urljoin, urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth_deps import get_current_user
from app.database.models.execution import Defect, DefectStatus, ExecutionResult, ExecutionRun, ExecutionStatus, ResultStatus
from app.database.models.generation_run import GenerationRun
from app.database.models.project import Project
from app.database.models.requirement import Requirement
from app.database.models.test_case import TestCase
from app.database.models.user import User
from app.database.session import AsyncSessionLocal, get_db_session
from app.schemas.execution import DashboardSummary, DefectCreate, DefectOut, ExecutionCreate, ExecutionRunOut

router = APIRouter(tags=["execution"])


async def _owned_project(db: AsyncSession, project_id: UUID, user_id: UUID) -> Project:
    project = await db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _validated_target(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Execution target must be an HTTP(S) URL")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("Local execution targets are disabled")
    for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(item[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Private-network execution targets are disabled")
    return value


def _compile_steps(steps: list, base_url: str) -> list[tuple[str, str, str | None]]:
    """Compile the deliberately small M4 DSL. Unknown prose is blocked, never guessed."""
    compiled: list[tuple[str, str, str | None]] = [("navigate", base_url, None)]
    for raw in steps:
        step = str(raw).strip()
        lower = step.lower()
        if lower.startswith("navigate "):
            compiled.append(("navigate", urljoin(base_url, step[9:].strip()), None))
        elif lower.startswith("click "):
            compiled.append(("click", step[6:].strip(), None))
        elif lower.startswith("fill ") and " :: " in step:
            locator, value = step[5:].split(" :: ", 1)
            compiled.append(("fill", locator.strip(), value))
        elif lower.startswith("assert-text "):
            compiled.append(("assert-text", step[12:].strip(), None))
        elif lower.startswith("assert-url "):
            compiled.append(("assert-url", step[11:].strip(), None))
        else:
            raise ValueError(
                f"Unsupported automation step: {step!r}. Convert it to navigate, click, "
                "fill <locator> :: <value>, assert-text, or assert-url."
            )
    return compiled


async def _run_execution(run_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.scalar(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
                selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
                selectinload(ExecutionRun.execution_plan),
            )
            .where(ExecutionRun.id == run_id)
        )
        if run is None:
            return
        run.status = ExecutionStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        if run.execution_plan is not None:
            run.execution_plan.status = "running"
        await db.commit()
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as manager:
                browser_type = getattr(manager, run.browser)
                browser = await browser_type.launch(headless=True)
                context = await browser.new_context(ignore_https_errors=False)
                for result in run.results:
                    if result.status != ResultStatus.PENDING:
                        continue
                    started = time.perf_counter()
                    try:
                        source_steps = (
                            result.execution_plan_case.steps
                            if result.execution_plan_case is not None
                            else result.test_case.steps
                        )
                        steps = _compile_steps(source_steps or [], run.base_url)
                    except ValueError as exc:
                        result.status = ResultStatus.BLOCKED
                        result.error_message = str(exc)
                        result.duration_ms = 0
                        continue
                    page = await context.new_page()
                    try:
                        for action, target, value in steps:
                            if action == "navigate":
                                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                            elif action == "click":
                                await page.locator(target).click(timeout=10_000)
                            elif action == "fill":
                                await page.locator(target).fill(value or "", timeout=10_000)
                            elif action == "assert-text":
                                await page.get_by_text(target, exact=False).wait_for(state="visible", timeout=10_000)
                            elif action == "assert-url" and target not in page.url:
                                raise AssertionError(f"Expected URL to contain {target!r}, got {page.url!r}")
                        result.status = ResultStatus.PASSED
                        result.evidence = {"final_url": page.url, "title": await page.title(), "dsl_version": "1.0"}
                    except Exception as exc:
                        result.status = ResultStatus.FAILED
                        result.error_message = str(exc)[:4000]
                        result.evidence = {"final_url": page.url, "dsl_version": "1.0"}
                    finally:
                        result.duration_ms = int((time.perf_counter() - started) * 1000)
                        await page.close()
                await browser.close()
            run.passed_tests = sum(x.status == ResultStatus.PASSED for x in run.results)
            run.failed_tests = sum(x.status == ResultStatus.FAILED for x in run.results)
            run.blocked_tests = sum(x.status == ResultStatus.BLOCKED for x in run.results)
            run.status = ExecutionStatus.COMPLETED
        except Exception as exc:
            run.status = ExecutionStatus.FAILED
            for result in run.results:
                if result.status == ResultStatus.PENDING:
                    result.status = ResultStatus.BLOCKED
                    result.error_message = f"Execution worker unavailable: {str(exc)[:1000]}"
            run.blocked_tests = sum(x.status == ResultStatus.BLOCKED for x in run.results)
        finally:
            run.completed_at = datetime.now(timezone.utc)
            if run.execution_plan is not None:
                run.execution_plan.status = "completed" if run.status == ExecutionStatus.COMPLETED else "failed"
            await db.commit()


@router.post("/executions", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def create_execution(payload: ExecutionCreate, background: BackgroundTasks, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    await _owned_project(db, payload.project_id, user.id)
    try:
        base_url = _validated_target(str(payload.base_url))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cases = (await db.scalars(
        select(TestCase).join(GenerationRun).where(
            GenerationRun.project_id == payload.project_id,
            TestCase.id.in_(payload.test_case_ids),
            TestCase.is_automation_candidate.is_(True),
        )
    )).unique().all()
    if len(cases) != len(set(payload.test_case_ids)):
        raise HTTPException(status_code=400, detail="One or more test cases are unavailable or not automation candidates")
    run = ExecutionRun(project_id=payload.project_id, requested_by_id=user.id, name=payload.name, base_url=base_url, browser=payload.browser, total_tests=len(cases))
    db.add(run)
    await db.flush()
    for case in cases:
        db.add(ExecutionResult(execution_run_id=run.id, test_case_id=case.id))
    await db.commit()
    run = await db.scalar(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.id == run.id))
    background.add_task(_run_execution, run.id)
    return run


@router.get("/executions", response_model=list[ExecutionRunOut])
async def list_executions(project_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    await _owned_project(db, project_id, user.id)
    return (await db.scalars(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc()).limit(50))).unique().all()


@router.get("/executions/{run_id}", response_model=ExecutionRunOut)
async def get_execution(run_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    run = await db.scalar(select(ExecutionRun).join(Project).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.id == run_id, Project.owner_id == user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Execution run not found")
    return run


@router.post("/execution-results/{result_id}/defects", response_model=DefectOut, status_code=status.HTTP_201_CREATED)
async def create_defect(result_id: UUID, payload: DefectCreate, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    result = await db.scalar(select(ExecutionResult).join(ExecutionRun).join(Project).where(ExecutionResult.id == result_id, Project.owner_id == user.id))
    if result is None:
        raise HTTPException(status_code=404, detail="Execution result not found")
    if result.status != ResultStatus.FAILED:
        raise HTTPException(status_code=400, detail="Defects can only be logged from failed execution results")
    sequence = (await db.scalar(select(func.count(Defect.id)))) or 0
    defect = Defect(execution_result_id=result.id, defect_key=f"QTX-{sequence + 1:05d}", title=payload.title, description=payload.description, severity=payload.severity, logged_by_id=user.id)
    db.add(defect)
    await db.commit()
    await db.refresh(defect)
    return defect


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(project_id: UUID, db: Annotated[AsyncSession, Depends(get_db_session)], user: Annotated[User, Depends(get_current_user)]):
    await _owned_project(db, project_id, user.id)
    requirements = await db.scalar(select(func.count(Requirement.id)).where(Requirement.project_id == project_id)) or 0
    test_cases = await db.scalar(select(func.count(TestCase.id)).join(GenerationRun).where(GenerationRun.project_id == project_id)) or 0
    automation = await db.scalar(select(func.count(TestCase.id)).join(GenerationRun).where(GenerationRun.project_id == project_id, TestCase.is_automation_candidate.is_(True))) or 0
    run_count = await db.scalar(select(func.count(ExecutionRun.id)).where(ExecutionRun.project_id == project_id)) or 0
    passed = await db.scalar(select(func.coalesce(func.sum(ExecutionRun.passed_tests), 0)).where(ExecutionRun.project_id == project_id)) or 0
    failed = await db.scalar(select(func.coalesce(func.sum(ExecutionRun.failed_tests), 0)).where(ExecutionRun.project_id == project_id)) or 0
    open_defects = await db.scalar(select(func.count(Defect.id)).join(ExecutionResult).join(ExecutionRun).where(ExecutionRun.project_id == project_id, Defect.status.in_([DefectStatus.OPEN, DefectStatus.IN_PROGRESS]))) or 0
    recent = (await db.scalars(select(ExecutionRun).options(
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
        selectinload(ExecutionRun.results).selectinload(ExecutionResult.defects),
    ).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc()).limit(5))).unique().all()
    denominator = int(passed) + int(failed)
    return DashboardSummary(requirements=requirements, test_cases=test_cases, execution_runs=run_count, pass_rate=round(int(passed) * 100 / denominator, 1) if denominator else 0, open_defects=open_defects, automation_candidates=automation, recent_runs=recent)


