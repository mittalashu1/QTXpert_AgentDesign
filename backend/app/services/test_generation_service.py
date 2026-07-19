"""Orchestrates a full test-design run: collects requirements, invokes the
LangGraph agent, and persists the structured results (steps 1-11 of the
spec's AI workflow)."""
import time
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.test_design_agent.graph import build_test_design_graph
from app.config import Settings
from app.database.models.generation_run import GenerationRun, RunStatus
from app.database.models.test_case import Priority, RiskLevel, Severity, TestCase, TestCaseType
from app.database.repositories.requirement_repository import RequirementRepository
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider


class TestGenerationService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings

    async def run(
        self,
        project_id: UUID,
        requested_by_id: UUID,
        requirement_ids: Optional[List[UUID]] = None,
        llm_provider_override: Optional[str] = None,
    ) -> GenerationRun:
        requirement_repo = RequirementRepository(self._db)
        requirements = (
            await requirement_repo.get_many(requirement_ids)
            if requirement_ids
            else await requirement_repo.list_for_project(project_id)
        )
        if not requirements:
            raise ValueError("No requirements found to generate test cases from.")

        provider = get_llm_provider(llm_provider_override)

        run = GenerationRun(
            project_id=project_id,
            requested_by_id=requested_by_id,
            status=RunStatus.NORMALIZING,
            llm_provider=provider.provider_name,
            llm_model=self._settings.LLM_MODEL,
        )
        self._db.add(run)
        await self._db.commit()
        await self._db.refresh(run)

        start = time.perf_counter()
        try:
            graph = build_test_design_graph(provider)
            result_state = await graph.ainvoke(
                {
                    "raw_documents": [r.raw_content for r in requirements],
                    "project_id": str(project_id),
                    "generation_run_id": str(run.id),
                }
            )

            run.status = RunStatus.COMPLETED
            run.requirement_summary = result_state.get("requirement_summary")
            run.business_rules = result_state.get("structure", {}).get("business_rules")
            run.functional_breakdown = result_state.get("functional_breakdown")
            run.test_scenarios = result_state.get("test_scenarios")
            run.risk_analysis = result_state.get("risk_analysis")
            run.processing_time_seconds = time.perf_counter() - start
            if result_state.get("errors"):
                run.error_message = "; ".join(result_state["errors"])

            for index, case in enumerate(result_state.get("test_cases", []), start=1):
                test_case = TestCase(
                    generation_run_id=run.id,
                    test_case_key=f"TC-{run.id.hex[:8].upper()}-{index:04d}",
                    requirement_traceability=case.get("requirement_traceability"),
                    test_type=TestCaseType(case.get("test_type", "functional").lower().replace(" ", "_")),
                    scenario=case.get("scenario", ""),
                    objective=case.get("objective", ""),
                    priority=Priority(case.get("priority", "medium").lower()),
                    severity=Severity(case.get("severity", "minor").lower()),
                    preconditions=case.get("preconditions"),
                    test_data=case.get("test_data"),
                    steps=case.get("steps", []),
                    expected_result=case.get("expected_result", ""),
                    post_conditions=case.get("post_conditions"),
                    is_automation_candidate=bool(case.get("is_automation_candidate", False)),
                    automation_type=case.get("automation_type"),
                    risk_level=RiskLevel(case.get("risk_level", "medium").lower()),
                )
                self._db.add(test_case)

            await self._db.commit()
            await self._db.refresh(run)
            return run

        except LLMProviderError as exc:
            run.status = RunStatus.FAILED
            run.error_message = str(exc)
            run.processing_time_seconds = time.perf_counter() - start
            await self._db.commit()
            raise
        except Exception as exc:  # noqa: BLE001
            run.status = RunStatus.FAILED
            run.error_message = f"Unexpected error: {exc}"
            run.processing_time_seconds = time.perf_counter() - start
            await self._db.commit()
            raise
