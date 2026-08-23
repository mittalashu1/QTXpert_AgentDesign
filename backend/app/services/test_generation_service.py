"""Orchestrates a full test-design run: collects requirements, invokes the
LangGraph agent, and persists the structured results (steps 1-11 of the
spec's AI workflow)."""
import logging
import time
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.test_design_agent.graph import build_test_design_graph
from app.agents.test_design_agent.nodes import _call_json
from app.config import Settings
from app.database.models.generation_run import GenerationRun, RunStatus
from app.database.models.test_case import Priority, RiskLevel, Severity, TestCase, TestCaseType
from app.database.repositories.requirement_repository import RequirementRepository
from app.database.repositories.requirement_repository import ProjectRepository
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


def _normalize_enum_token(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _coerce_enum(enum_cls, raw_value, default):
    """Best-effort mapping of an LLM-provided string onto a known enum."""
    if raw_value is None:
        return default
    token = _normalize_enum_token(str(raw_value))
    try:
        return enum_cls(token)
    except ValueError:
        return default


class TestGenerationService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings

    async def create_run(
        self,
        project_id: UUID,
        requested_by_id: UUID,
        requirement_ids: Optional[List[UUID]] = None,
        llm_provider_override: Optional[str] = None,
        generation_profile: str = "feature",
    ) -> GenerationRun:
        if await ProjectRepository(self._db).get_for_owner(project_id, requested_by_id) is None:
            raise ValueError("Project not found")
        if requirement_ids and len(requirement_ids) > self._settings.MAX_REQUIREMENTS_PER_GENERATION:
            raise ValueError(
                f"Select at most {self._settings.MAX_REQUIREMENTS_PER_GENERATION} requirements per generation."
            )
        requirement_repo = RequirementRepository(self._db)
        requirements = (
            await requirement_repo.get_many_for_project(requirement_ids, project_id)
            if requirement_ids
            else await requirement_repo.list_for_project(project_id)
        )
        if requirement_ids and len(requirements) != len(set(requirement_ids)):
            raise ValueError("One or more selected requirements do not belong to this project.")
        if not requirements:
            raise ValueError("No requirements found to generate test cases from.")

        provider = get_llm_provider(llm_provider_override)

        run = GenerationRun(
            project_id=project_id,
            requested_by_id=requested_by_id,
            status=RunStatus.NORMALIZING,
            llm_provider=provider.provider_name,
            llm_model=self._settings.LLM_MODEL,
            generation_profile=generation_profile,
        )
        self._db.add(run)
        await self._db.commit()
        # The immediate API response includes test_cases. Explicitly load the
        # empty relationship now so response serialization never triggers an
        # async lazy-load after the request session has finished.
        await self._db.refresh(run, attribute_names=["test_cases"])

        return run

    async def execute(
        self,
        run_id: UUID,
        project_id: UUID,
        requirement_ids: Optional[List[UUID]],
        requested_by_id: UUID,
        llm_provider_override: Optional[str] = None,
        generation_profile: str = "feature",
    ) -> GenerationRun:
        run = (
            await self._db.execute(
                select(GenerationRun).where(
                    GenerationRun.id == run_id,
                    GenerationRun.project_id == project_id,
                    GenerationRun.requested_by_id == requested_by_id,
                )
            )
        ).scalar_one()
        requirement_repo = RequirementRepository(self._db)
        requirements = (
            await requirement_repo.get_many_for_project(requirement_ids, project_id)
            if requirement_ids
            else await requirement_repo.list_for_project(project_id)
        )
        if requirement_ids and len(requirements) != len(set(requirement_ids)):
            raise ValueError("Selected requirements no longer belong to this project.")
        provider = get_llm_provider(llm_provider_override)
        start = time.perf_counter()
        case_build_warnings: List[str] = []
        logger.info("generation_started run_id=%s project_id=%s profile=%s requirements=%s", run_id, project_id, generation_profile, len(requirements))
        try:
            # Interactive runs do not need the graph's pre-flight count query.
            # Keep the count bookkeeping local so stale provider sessions cannot
            # block a new one-page generation.
            persisted_count = 0

            async def persist_batch(cases: list) -> None:
                nonlocal persisted_count
                run.status = RunStatus.GENERATING_TEST_CASES
                await self._persist_test_cases(
                    run, cases, case_build_warnings, start_index=persisted_count + 1
                )
                persisted_count += len(cases)
                await self._db.commit()
                logger.info("generation_batch_persisted run_id=%s batch_size=%s total=%s", run.id, len(cases), persisted_count)

            # Every profile runs through the provider-backed test-design graph.
            # The previous interactive shortcut inserted generic LOCAL cases, which
            # made uploaded APKs look like they had been analyzed even when the
            # model had not produced any output. Keep the run pending while the
            # graph analyzes the supplied requirements and persists real cases.

            persisted_count = (
                await self._db.scalar(
                    select(func.count()).select_from(TestCase).where(TestCase.generation_run_id == run.id)
                )
                or 0
            )
            graph = build_test_design_graph(
                provider,
                on_test_case_batch=persist_batch,
                max_scenarios={
                    "smoke": min(8, self._settings.MAX_SCENARIOS_PER_GENERATION),
                    # Feature runs are interactive; keep the first result bounded\n                    # so six requirements cannot exceed the stale-recovery window.\n                    "feature": min(2, self._settings.MAX_SCENARIOS_PER_GENERATION),
                    "regression": self._settings.MAX_SCENARIOS_PER_GENERATION,
                    "deep_regression": min(80, self._settings.MAX_SCENARIOS_PER_GENERATION * 2),
                }.get(generation_profile, min(20, self._settings.MAX_SCENARIOS_PER_GENERATION)),
            )
            input_state = {
                "raw_documents": [r.raw_content for r in requirements],
                "project_id": str(project_id), "generation_run_id": str(run.id),
            }
            result_state = None
            async for update in graph.astream(input_state, stream_mode="updates"):
                node_name, node_state = next(iter(update.items()))
                logger.info("generation_node_completed run_id=%s node=%s", run.id, node_name)
                # LangGraph yields an update after a node completes. Set the
                # status for the node that starts next so the UI is not one
                # generation phase behind the actual work.
                if node_name in {"normalize", "extract_structure", "summary"}:
                    run.status = RunStatus.ANALYZING
                elif node_name == "breakdown_step":
                    run.status = RunStatus.GENERATING_SCENARIOS
                elif node_name == "scenarios_step":
                    run.status = RunStatus.GENERATING_TEST_CASES
                elif node_name == "detailed_test_cases":
                    run.status = RunStatus.RISK_ANALYSIS
                elif node_name == "risk_analysis_step":
                    result_state = node_state
                await self._db.commit()

            if result_state is None:
                raise RuntimeError("Generation graph finished without risk analysis output")

            run.requirement_summary = result_state.get("requirement_summary")
            run.business_rules = result_state.get("structure", {}).get("business_rules")
            run.functional_breakdown = result_state.get("functional_breakdown")
            run.test_scenarios = result_state.get("test_scenarios")
            run.risk_analysis = result_state.get("risk_analysis")

            run.processing_time_seconds = time.perf_counter() - start

            existing_errors = result_state.get("errors", [])
            all_warnings = list(existing_errors) + case_build_warnings
            if persisted_count == 0:
                run.status = RunStatus.FAILED
                run.error_message = (
                    "No test cases could be persisted. "
                    + ("; ".join(all_warnings) if all_warnings else "The model returned no usable test cases.")
                )
            else:
                run.status = RunStatus.COMPLETED
                if all_warnings:
                    run.error_message = (
                        f"Completed with {len(all_warnings)} skipped/warning item(s): "
                        + "; ".join(all_warnings)
                    )

            await self._db.commit()
            await self._db.refresh(run)
            logger.info("generation_finished run_id=%s status=%s persisted_cases=%s", run.id, run.status.value, persisted_count)
            return run

        except LLMProviderError as exc:
            run.status = RunStatus.FAILED
            run.error_message = f"LLM provider error: {exc}"
            run.processing_time_seconds = time.perf_counter() - start
            await self._db.commit()
            logger.exception("generation_failed run_id=%s category=llm", run.id)
            raise
        except Exception as exc:  # noqa: BLE001
            run.status = RunStatus.FAILED
            run.error_message = f"Unexpected error: {type(exc).__name__}: {exc}"
            run.processing_time_seconds = time.perf_counter() - start
            await self._db.commit()
            logger.exception("generation_failed run_id=%s category=unexpected", run.id)
            raise

    async def _persist_test_cases(
        self, run: GenerationRun, raw_cases: list, warnings: List[str], start_index: int = 1
    ) -> None:
        """Save cases before the final risk step so the UI can render them early."""
        for index, case in enumerate(raw_cases, start=start_index):
            try:
                if not isinstance(case, dict):
                    raise ValueError("AI output was not a test-case object")
                objective = str(case.get("objective") or "").strip()
                expected_result = str(case.get("expected_result") or "").strip()
                steps = case.get("steps")
                if not objective or not expected_result or not isinstance(steps, list) or not steps:
                    raise ValueError("missing objective, expected result, or test steps")
                self._db.add(TestCase(
                    generation_run_id=run.id,
                    test_case_key=f"TC-{run.id.hex[:8].upper()}-{index:04d}",
                    requirement_traceability=case.get("requirement_traceability"),
                    test_type=_coerce_enum(TestCaseType, case.get("test_type"), TestCaseType.FUNCTIONAL),
                    scenario=str(case.get("scenario") or f"Untitled scenario {index}"),
                    objective=objective,
                    priority=_coerce_enum(Priority, case.get("priority"), Priority.MEDIUM),
                    severity=_coerce_enum(Severity, case.get("severity"), Severity.MINOR),
                    preconditions=case.get("preconditions"),
                    test_data=case.get("test_data") if isinstance(case.get("test_data"), dict) else None,
                    steps=steps,
                    expected_result=expected_result,
                    post_conditions=case.get("post_conditions"),
                    is_automation_candidate=bool(case.get("is_automation_candidate", False)),
                    automation_type=case.get("automation_type"),
                    risk_level=_coerce_enum(RiskLevel, case.get("risk_level"), RiskLevel.MEDIUM),
                ))
            except Exception as case_exc:  # noqa: BLE001
                warnings.append(f"Skipped test case #{index}: {case_exc}")

