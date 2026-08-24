"""Orchestrates a full test-design run: collects requirements, invokes the
LangGraph agent, and persists the structured results (steps 1-11 of the
spec's AI workflow)."""
import asyncio
import json
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


def _stringify_optional(value, max_length: int | None = None) -> str | None:
    """Normalize flexible model output for columns that store plain text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, list):
        parts = [_stringify_optional(item) for item in value]
        text = "; ".join(part for part in parts if part)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value).strip()
    if not text:
        return None
    return text[:max_length] if max_length else text


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _derive_test_set_title(requirements: list, requested_title: str | None = None) -> str | None:
    """Choose a stable, human-readable heading before generation starts."""
    explicit = _stringify_optional(requested_title, 500)
    if explicit:
        return explicit

    titles = []
    for requirement in requirements:
        title = _stringify_optional(getattr(requirement, "title", None), 180)
        if title and title not in titles:
            titles.append(title)
    if not titles:
        return "Test design"
    if len(titles) == 1:
        return titles[0]
    remaining = len(titles) - 1
    return f"{titles[0]} + {remaining} more" if remaining == 1 else f"{titles[0]} + {remaining} more sources"


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
        test_set_title: Optional[str] = None,
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
            title=_derive_test_set_title(requirements, test_set_title),
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
            next_case_index = 1

            async def persist_batch(cases: list) -> None:
                nonlocal persisted_count, next_case_index
                run.status = RunStatus.GENERATING_TEST_CASES
                warnings_before = len(case_build_warnings)
                logger.info(
                    "generation_batch_persisting run_id=%s raw_size=%s start_index=%s",
                    run.id, len(cases), next_case_index,
                )
                await self._persist_test_cases(
                    run, cases, case_build_warnings, start_index=next_case_index
                )
                next_case_index += len(cases)
                skipped = len(case_build_warnings) - warnings_before
                persisted_count += max(0, len(cases) - skipped)
                await self._db.flush()
                await self._db.commit()
                logger.info(
                    "generation_batch_persisted run_id=%s batch_size=%s total=%s",
                    run.id, len(cases) - skipped, persisted_count,
                )

            # Interactive profiles use a small number of concurrent, provider-backed
            # batches. This keeps the first real cases under a minute and makes them
            # visible while later coverage batches are still being generated.
            batch_specs_by_profile = {
                "smoke": [
                    ("critical happy paths, startup, authentication, and release-blocking failures", 6),
                ],
                "feature": [
                    ("primary user journeys and business-rule validation", 5),
                    ("negative paths, permissions, security, accessibility, and recovery", 5),
                ],
                "regression": [
                    ("primary workflows and state transitions", 6),
                    ("negative, boundary, validation, permissions, and error-handling paths", 6),
                    ("integration, compatibility, accessibility, performance, and recovery risks", 6),
                ],
                "deep_regression": [
                    ("primary workflows and business rules", 6),
                    ("negative, boundary, abuse, and authorization paths", 6),
                    ("integration, data integrity, recovery, and performance risks", 6),
                    ("accessibility, localization, compatibility, and long-session behavior", 6),
                ],
            }
            batch_specs = batch_specs_by_profile.get(generation_profile)
            if batch_specs:
                source_text = "\n\n".join(
                    f"Source: {requirement.title}\n{requirement.raw_content or ''}"
                    for requirement in requirements
                )[:24000]
                system_prompt = (
                    "You are a senior software test architect. Analyze only the supplied product "
                    "context and return a non-empty JSON object with keys summary and test_cases. "
                    "Each test case must contain scenario, objective, preconditions, steps, "
                    "expected_result, test_type, priority, severity, risk_level, and "
                    "is_automation_candidate. steps must be an array of concise action strings. "
                    "Use observable, product-specific behavior. Never emit placeholders, generic "
                    "templates, or repeat the user's instruction as the scenario."
                )
                semaphore = asyncio.Semaphore(3)

                async def generate_interactive_batch(focus: str, case_count: int) -> dict:
                    user_prompt = (
                        f"Product context:\n{source_text}\n\n"
                        f"Coverage focus: {focus}.\n"
                        f"Generate up to {case_count} distinct, execution-ready test cases. "
                        "Prefer fewer high-quality cases over vague coverage."
                    )
                    async with semaphore:
                        batch_started = time.perf_counter()
                        logger.info(
                            "interactive_batch_started run_id=%s focus=%s requested_cases=%s",
                            run.id, focus, case_count,
                        )
                        result = await _call_json(
                            provider, system_prompt, user_prompt,
                            timeout_seconds=45, max_retries=0, max_tokens=2200,
                        )
                        logger.info(
                            "interactive_batch_completed run_id=%s focus=%s duration_seconds=%.2f",
                            run.id, focus, time.perf_counter() - batch_started,
                        )
                        return result

                run.status = RunStatus.ANALYZING
                await self._db.commit()
                tasks = [
                    asyncio.create_task(generate_interactive_batch(focus, case_count))
                    for focus, case_count in batch_specs
                ]
                summaries: list[str] = []
                generated_cases: list[dict] = []
                for task in asyncio.as_completed(tasks):
                    try:
                        batch_result = await task
                    except Exception as batch_exc:  # noqa: BLE001
                        warning = f"Coverage batch failed: {batch_exc}"
                        case_build_warnings.append(warning)
                        logger.warning(
                            "interactive_batch_failed run_id=%s error=%s", run.id, batch_exc
                        )
                        continue
                    batch_cases = batch_result.get("test_cases", [])
                    if not isinstance(batch_cases, list):
                        case_build_warnings.append("Coverage batch returned a non-list test_cases value.")
                        continue
                    summary = str(batch_result.get("summary") or "").strip()
                    if summary:
                        summaries.append(summary)
                    if batch_cases:
                        await persist_batch(batch_cases)
                        generated_cases.extend(batch_cases)

                run.requirement_summary = summaries[0] if summaries else None
                run.test_scenarios = [
                    {
                        "scenario_id": f"interactive-{index + 1}",
                        "title": str(case.get("scenario") or f"Test case {index + 1}"),
                    }
                    for index, case in enumerate(generated_cases)
                ]
                run.risk_analysis = {
                    "generated_case_count": persisted_count,
                    "profile": generation_profile,
                    "streamed_batches": len(batch_specs),
                }
                run.processing_time_seconds = time.perf_counter() - start
                run.status = RunStatus.COMPLETED if persisted_count else RunStatus.FAILED
                if case_build_warnings:
                    run.error_message = "; ".join(case_build_warnings)
                if not persisted_count and not run.error_message:
                    run.error_message = "The AI returned no usable test cases."
                await self._db.commit()
                await self._db.refresh(run, attribute_names=["test_cases"])
                logger.info(
                    "generation_finished run_id=%s status=%s persisted_cases=%s duration_seconds=%.2f",
                    run.id, run.status.value, persisted_count, run.processing_time_seconds,
                )
                return run

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
            await self._db.rollback()
            run = await self._db.get(GenerationRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.error_message = f"LLM provider error: {exc}"
                run.processing_time_seconds = time.perf_counter() - start
                await self._db.commit()
            logger.exception("generation_failed run_id=%s category=llm", run_id)
            raise
        except Exception as exc:  # noqa: BLE001
            await self._db.rollback()
            run = await self._db.get(GenerationRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.error_message = f"Unexpected error: {type(exc).__name__}: {exc}"
                run.processing_time_seconds = time.perf_counter() - start
                await self._db.commit()
            logger.exception("generation_failed run_id=%s category=unexpected", run_id)
            raise

    async def _persist_test_cases(
        self, run: GenerationRun, raw_cases: list, warnings: List[str], start_index: int = 1
    ) -> None:
        """Save cases before the final risk step so the UI can render them early."""
        for index, case in enumerate(raw_cases, start=start_index):
            try:
                if not isinstance(case, dict):
                    raise ValueError("AI output was not a test-case object")
                objective = _stringify_optional(case.get("objective"))
                expected_result = _stringify_optional(case.get("expected_result"))
                steps = case.get("steps")
                if not objective or not expected_result or not isinstance(steps, list) or not steps:
                    raise ValueError("missing objective, expected result, or test steps")
                normalized_steps = []
                for step in steps:
                    if isinstance(step, str) and step.strip():
                        normalized_steps.append(step.strip())
                    elif isinstance(step, dict):
                        action = step.get("action") or step.get("description") or step.get("step")
                        action_text = _stringify_optional(action)
                        if action_text:
                            normalized_steps.append(action_text)
                if not normalized_steps:
                    raise ValueError("test steps contained no usable actions")
                self._db.add(TestCase(
                    generation_run_id=run.id,
                    test_case_key=f"TC-{run.id.hex[:8].upper()}-{index:04d}",
                    requirement_traceability=_stringify_optional(
                        case.get("requirement_traceability"), 255
                    ),
                    test_type=_coerce_enum(TestCaseType, case.get("test_type"), TestCaseType.FUNCTIONAL),
                    scenario=_stringify_optional(case.get("scenario"), 500)
                    or f"Untitled scenario {index}",
                    objective=objective,
                    priority=_coerce_enum(Priority, case.get("priority"), Priority.MEDIUM),
                    severity=_coerce_enum(Severity, case.get("severity"), Severity.MINOR),
                    preconditions=_stringify_optional(case.get("preconditions")),
                    test_data=case.get("test_data") if isinstance(case.get("test_data"), dict) else None,
                    steps=normalized_steps,
                    expected_result=expected_result,
                    post_conditions=_stringify_optional(case.get("post_conditions")),
                    is_automation_candidate=_coerce_bool(case.get("is_automation_candidate")),
                    automation_type=_stringify_optional(case.get("automation_type"), 100),
                    risk_level=_coerce_enum(RiskLevel, case.get("risk_level"), RiskLevel.MEDIUM),
                ))
            except Exception as case_exc:  # noqa: BLE001
                warnings.append(f"Skipped test case #{index}: {case_exc}")


