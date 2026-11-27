"""Import and control versioned Test Design suites for execution."""
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth_deps import get_current_user
from app.api.routes.executions import _compile_mobile_steps, _compile_steps, _run_execution, _validate_execution_target
from app.config import Settings, get_settings
from app.database.models.autopilot_input import AutopilotInputRecord
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.document_intelligence import DocumentAnalysisRun
from app.database.models.execution import ExecutionResult, ExecutionRun, ResultStatus
from app.database.models.local_runner import LocalRunnerJob
from app.database.models.execution_plan import ExecutionPlan, ExecutionPlanCase
from app.database.models.generation_run import GenerationRun, RunStatus
from app.database.models.project import Project
from app.database.models.test_case import TestCase
from app.database.models.user import User
from app.database.session import get_db_session
from app.schemas.authored_execution import AuthoredAutomation, FixtureBinding, FixtureBindingsUpdate
from app.schemas.execution import (
    ExecutionPlanCasesUpdate,
    ExecutionPlanExecute,
    ExecutionPlanImport,
    ExecutionPlanInputsUpdate,
    ExecutionPlanOut,
    ExecutionPlanPreflight,
    ExecutionPlanRerun,
    ExecutionRunOut,
)
from app.services.authored_execution import allowed_fixture_parts, authored_url, fixture_keys, scoped_fixtures

router = APIRouter(tags=["execution-plans"])

_EXECUTION_PLAN_NAME_MAX_LENGTH = 255
_HIGH_IMPACT_STEP = re.compile(
    r"\b(delete|remove|withdraw|transfer|payment|pay|purchase|close account|send money|otp)\b",
    re.IGNORECASE,
)
_MONEY_JOURNEY = re.compile(r"\b(?:add|send)\s+(?:money|funds)\b", re.IGNORECASE)
_SUBMIT_MONEY = re.compile(r"\b(?:submit|confirm|post|pay now|send now|deposit now)\b", re.IGNORECASE)
_AUTHENTICATION_TEXT = re.compile(
    r"\b(log[ -]?in|sign[ -]?in|authenticate|authentication|credential|username|password|passcode|mfa|otp|one[- ]time)\b",
    re.IGNORECASE,
)
_AUTHENTICATION_SURFACE = re.compile(
    r"\b(?:log[ -]?in|sign[ -]?in)\s+(?:page|screen|form|button|link|dialog|prompt|heading)\b",
    re.IGNORECASE,
)
_TEST_DATA_TEXT = re.compile(
    r"\b(test data|seeded|synthetic|customer|account|portfolio|beneficiar(?:y|ies)|cart|order|email|phone|amount|balance|investment)\b",
    re.IGNORECASE,
)
_SYNTHETIC_APP_ARTIFACT = re.compile(
    r"\b(?:synthetic|seeded)(?:\s+(?:test|fixture)){0,2}\s+(?:apk|ipa|app|application|build)\b",
    re.IGNORECASE,
)
_ENVIRONMENT_TEXT = re.compile(
    r"\b(staging|sandbox|uat|non[- ]production|environment|reset|cleanup|seed)\b",
    re.IGNORECASE,
)
_SUPPORTED_STEP_PREFIXES = (
    "navigate ", "click ", "fill ", "assert-text ", "assert-url ",
    "tap ", "assert-visible ",
)
_SENSITIVE_INPUT = re.compile(
    r"\b(password|passcode|secret|token|otp|api[ _-]?key|access[ _-]?key)\b\s*[:=]",
    re.IGNORECASE,
)
_SENSITIVE_FIELD = re.compile(
    r"\b(password|passcode|secret|token|otp|api[ _-]?key|access[ _-]?key)\b",
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


def _compact_plan_name(value: str) -> str:
    """Keep the database-backed plan name within its 255-character contract."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    if len(normalized) <= _EXECUTION_PLAN_NAME_MAX_LENGTH:
        return normalized
    # Reserve one character for an ellipsis and prefer a word boundary so the
    # execution selector remains readable for legacy long Design titles.
    clipped = normalized[: _EXECUTION_PLAN_NAME_MAX_LENGTH - 1].rsplit(" ", 1)[0].rstrip()
    if not clipped:
        clipped = normalized[: _EXECUTION_PLAN_NAME_MAX_LENGTH - 1]
    return f"{clipped}…"


def _case_text(case: ExecutionPlanCase) -> str:
    """Return searchable case text without exposing or persisting secrets."""
    data = " ".join(f"{key} {value}" for key, value in (case.test_data or {}).items())
    return " ".join(
        str(value or "")
        for value in (case.scenario, case.objective, case.preconditions, case.expected_result, data, *(case.steps or []))
    )


def _has_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return bool(re.search(r"<[^>]+>|\[\s*(?:to be supplied|value|placeholder|todo)[^\]]*\]", value, re.IGNORECASE))
    if isinstance(value, dict):
        return any(_has_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(item) for item in value)
    return False


def _case_has_test_data(case: ExecutionPlanCase) -> bool:
    return bool(case.test_data) and not _has_placeholder(case.test_data)


def _case_requires_test_data(case: ExecutionPlanCase, text: str) -> bool:
    descriptions = _SYNTHETIC_APP_ARTIFACT.sub(" ", text)
    return not _case_has_test_data(case) and bool(_TEST_DATA_TEXT.search(descriptions))


def _case_requires_authentication(case: ExecutionPlanCase) -> bool:
    """Detect an authenticated journey without treating a sign-in button as a credential need.

    Generated journeys often contain a harmless ``tap ... Sign in`` or
    ``assert-visible ... login`` step.  Those controls do not prove that the
    run needs credentials, while narrative instructions (or a credential
    entry step) do.  Keeping this distinction makes guided setup actionable
    and avoids blocking deterministic smoke checks unnecessarily.
    """
    narrative = " ".join(
        str(value or "")
        for value in (
            case.scenario,
            case.objective,
            case.preconditions,
            case.expected_result,
            *(f"{key} {value}" for key, value in (case.test_data or {}).items()),
        )
    )
    if _AUTHENTICATION_TEXT.search(_AUTHENTICATION_SURFACE.sub(" ", narrative)):
        return True
    for raw in case.steps or []:
        step = str(raw or "").strip()
        lower = step.lower()
        if lower.startswith("fill ") and re.search(r"\b(user(?:name)?|email|pass(?:word|code)?|credential|mfa|otp)\b", lower):
            return True
        # Navigation, tap/click, and assertion labels may mention sign-in or
        # login without requiring an authenticated account.
        if lower.startswith(("navigate ", "tap ", "click ", "assert-text ", "assert-visible ", "assert-url ")):
            continue
        if _AUTHENTICATION_TEXT.search(step):
            return True
    return False


def _unsupported_step(case: ExecutionPlanCase) -> str | None:
    """Find generated prose that needs a user conversion before execution."""
    for raw in case.steps or []:
        step = str(raw).strip()
        lower = step.lower()
        if lower in {"launch", "launch app", "open app", "start app", "install and launch application", "back", "press back", "navigate back"}:
            continue
        if lower.startswith(_SUPPORTED_STEP_PREFIXES):
            # The compiler will provide the precise syntax error (for example,
            # a fill command missing its locator/value separator).
            try:
                _compile_steps([step], "https://example.invalid")
            except ValueError:
                try:
                    _compile_mobile_steps([step])
                except ValueError:
                    return step
            else:
                continue
            continue
        return step
    return None


def _needs_ledger_contract(case: ExecutionPlanCase) -> bool:
    steps = [*case.steps]
    steps.extend(
        step.get("locator", "") for step in (case.automation or {}).get("steps", [])
        if step.get("action") == "tap"
    )
    return bool(_MONEY_JOURNEY.search(_case_text(case))) and any(
        _SUBMIT_MONEY.search(str(step).replace("_", " ").replace("-", " "))
        for step in steps
    )


def _input_requirements(plan: ExecutionPlan) -> list[dict]:
    """Build deterministic, actionable setup questions for the selected cases."""
    references = plan.runtime_inputs or {}
    requirements: dict[str, dict] = {}

    def add(
        key: str,
        label: str,
        category: str,
        description: str,
        case: ExecutionPlanCase | None = None,
        *,
        provided: bool | None = None,
    ) -> None:
        item = requirements.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "category": category,
                "description": description,
                "case_ids": [],
                "case_keys": [],
                "required": True,
                "provided": bool(str(references.get(key, "")).strip()) if provided is None else provided,
            },
        )
        if case is not None:
            if case.id not in item["case_ids"]:
                item["case_ids"].append(case.id)
            if case.test_case_key not in item["case_keys"]:
                item["case_keys"].append(case.test_case_key)
        if provided is not None:
            item["provided"] = item["provided"] and provided

    selected = [
        case for case in plan.cases
        if case.selected and case.execution_mode == "automated"
    ]
    for case in selected:
        text = _case_text(case)
        authored = bool(case.automation)
        ledger = bool((case.automation or {}).get("outcome"))
        if not authored and _case_requires_authentication(case):
            add(
                "authentication_reference",
                "Authentication reference",
                "authentication",
                "Use a non-production vault or credential reference (for example vault://qa/investor). Never enter a password, token, or OTP.",
                case,
            )
        if not authored and _case_requires_test_data(case, text):
            add(
                "test_data_reference",
                "Synthetic test-data reference",
                "test_data",
                "Point to a seeded or synthetic account/data set for this case. Do not paste personal or production data.",
                case,
            )
        if not authored and _ENVIRONMENT_TEXT.search(text):
            add(
                "environment_reference",
                "Environment and reset reference",
                "environment",
                "Name the non-production environment and its reset/cleanup reference so the journey can be repeated safely.",
                case,
            )
        unsupported = None if authored else _unsupported_step(case)
        if not authored and not unsupported and case.blocker_reason and "unsupported" in case.blocker_reason.lower():
            # Target-specific compilers (web vs mobile) may reject a command
            # that is valid for the other surface. Keep that blocker visible
            # in the guided setup panel even though the generic union parser
            # cannot identify it before a target is selected.
            unsupported = next((str(step).strip() for step in case.steps if str(step).strip()), "the generated journey")
        if unsupported:
            add(
                f"case:{case.id}:automation_steps",
                "Convert automation steps",
                "automation",
                "Replace generated prose with explicit commands: navigate, click/tap, fill, assert-text, assert-url, or assert-visible on mobile.",
                case,
                provided=False,
            )
        impact = next((str(step).strip() for step in case.steps if _HIGH_IMPACT_STEP.search(str(step))), None)
        if impact and not ledger:
            add(
                "approval_reference",
                "Business-impact approval reference",
                "approval",
                "Provide an approved test-window or change record before payment, transfer, deletion, OTP, or other irreversible actions run.",
                case,
            )

    # Stable ordering keeps the UI and API response predictable for a guided
    # question-and-answer flow.
    return sorted(requirements.values(), key=lambda item: (item["category"], item["label"], item["key"]))


def _setup_blockers(plan: ExecutionPlan, case: ExecutionPlanCase, target_kind: str = "web") -> list[str]:
    refs = plan.runtime_inputs or {}
    text = _case_text(case)
    blockers: list[str] = []
    if _case_requires_authentication(case) and not str(refs.get("authentication_reference", "")).strip():
        blockers.append("Authentication setup is required; add a non-production credential reference in Guided setup")
    if _case_requires_test_data(case, text) and not str(refs.get("test_data_reference", "")).strip():
        blockers.append("Synthetic test data is required; add a dataset/account reference in Guided setup")
    if _ENVIRONMENT_TEXT.search(text) and not str(refs.get("environment_reference", "")).strip():
        blockers.append("Environment/reset details are required; add a non-production environment reference in Guided setup")
    if next((str(step).strip() for step in case.steps if _HIGH_IMPACT_STEP.search(str(step))), None) and not str(refs.get("approval_reference", "")).strip():
        blockers.append("Approval is required for business-impacting actions; add an approval reference in Guided setup")
    if _needs_ledger_contract(case):
        blockers.append("Define an authored UAT ledger outcome for this money movement")
    unsupported = _unsupported_step(case)
    if unsupported:
        label = "Unsupported mobile automation step" if target_kind in {"android", "ios"} else "Unsupported automation step"
        blockers.append(f"{label}: {unsupported!r}. Convert it to an explicit supported command")
    return blockers


def _reject_sensitive_reference(value: str) -> str:
    """Normalize a setup reference and reject accidental secret paste-ins."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    if len(normalized) > 500:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Setup references must be 500 characters or fewer.")
    if _SENSITIVE_INPUT.search(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a non-production vault/reference identifier. Raw passwords, tokens, API keys, and OTPs are never stored.",
        )
    return normalized


def _contains_sensitive_data(value: object) -> bool:
    """Reject credential-shaped JSON keys before case snapshots are saved."""
    if isinstance(value, dict):
        return any(_SENSITIVE_FIELD.search(str(key)) or _contains_sensitive_data(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_sensitive_data(item) for item in value)
    return False


async def _load_plan(db: AsyncSession, plan_id: UUID, user_id: UUID, *, lock: bool = False) -> ExecutionPlan:
    query = (
        select(ExecutionPlan)
        .join(Project, ExecutionPlan.project_id == Project.id)
        .options(selectinload(ExecutionPlan.cases))
        .where(ExecutionPlan.id == plan_id, Project.owner_id == user_id)
    )
    plan = await db.scalar(query.with_for_update(of=ExecutionPlan) if lock else query)
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
        "input_references": dict(plan.runtime_inputs or {}),
        "fixture_bindings": dict(plan.fixture_bindings or {}),
        "input_requirements": _input_requirements(plan),
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
        automation=test_case.automation,
        expected_result=test_case.expected_result,
        post_conditions=test_case.post_conditions,
        is_automation_candidate=candidate,
        automation_type=test_case.automation_type,
        risk_level=_value(test_case.risk_level),
    )


async def _authored_setup(
    db: AsyncSession, plan: ExecutionPlan, owner_id: UUID, target_kind: str,
    app_asset_id: UUID | None, base_url: str | None, settings: Settings,
) -> tuple[set[str], set[str], str | None]:
    bindings = {key: FixtureBinding.model_validate(value) for key, value in (plan.fixture_bindings or {}).items()}
    rows = await scoped_fixtures(
        db, owner_id=owner_id, project_id=plan.project_id, target_kind=target_kind,
        app_asset_id=app_asset_id, base_url=base_url,
        record_ids={item.record_id for item in bindings.values()},
    )
    by_id = {row.id: row for row in rows}
    valid = {
        key for key, binding in bindings.items()
        if binding.record_id in by_id and binding.part in allowed_fixture_parts(by_id[binding.record_id])
    }
    credential_keys = {key for key in valid if by_id[bindings[key].record_id].category == "credential"}
    identity = None
    if app_asset_id and any((case.automation or {}).get("outcome") for case in plan.cases):
        analyzed = await db.scalar(select(AutopilotJob.analysis).where(
            AutopilotJob.owner_id == owner_id, AutopilotJob.project_id == plan.project_id,
            AutopilotJob.target_kind == target_kind,
            AutopilotJob.repository_asset_id == app_asset_id,
            AutopilotJob.analysis.is_not(None),
        ).order_by(AutopilotJob.created_at.desc()).limit(1))
        if isinstance(analyzed, dict):
            candidate = analyzed.get("package_name")
            if settings.full_uat_target_is_allowed(target_kind, candidate, candidate):
                identity = candidate
    return valid, credential_keys, identity


def _authored_blockers(
    plan: ExecutionPlan, case: ExecutionPlanCase, target_kind: str, base_url: str | None,
    bound_keys: set[str], credential_keys: set[str], ledger_identity: str | None, ledger_configured: bool,
) -> list[str]:
    automation = AuthoredAutomation.model_validate(case.automation)
    if automation.target_kind != target_kind:
        return [f"This case targets {automation.target_kind}. Select that platform to run it."]
    keys = fixture_keys(automation)
    blockers = [f"Bind saved Test Data for {key} on the selected target" for key in sorted(keys - bound_keys)]
    if _case_requires_authentication(case) and not (keys & credential_keys):
        blockers.append("Bind a saved credential for the authored sign-in steps")
    for step in automation.steps:
        if step.action == "navigate":
            try:
                authored_url(base_url or "", step.value or "")
            except ValueError as exc:
                blockers.append(str(exc))
                break
    references = plan.runtime_inputs or {}
    if automation.outcome:
        if not ledger_identity:
            blockers.append("Use an analyzed mobile build from the isolated UAT application allowlist")
        if not ledger_configured:
            blockers.append("Configure the signed UAT ledger export before running transaction cases")
        if not keys:
            blockers.append("Bind the transaction to saved Test Data for the isolated UAT account")
    elif _needs_ledger_contract(case):
        blockers.append("Define the UAT ledger outcome and exact receipt or attempt reference for this money movement")
    if (
        not automation.outcome and not references.get("approval_reference")
        and any(_HIGH_IMPACT_STEP.search(str(step)) for step in case.steps or [])
    ):
        blockers.append("Add the UAT approval reference in Guided setup")
    return blockers


async def _preflight_plan(
    plan: ExecutionPlan,
    base_url: str | None,
    *,
    case_ids: set[UUID] | None = None,
    target_kind: str = "web",
    bound_keys: set[str] | None = None,
    credential_keys: set[str] | None = None,
    ledger_identity: str | None = None,
    ledger_configured: bool = False,
) -> None:
    """Compile selected cases and surface every setup action explicitly."""
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
        if case.automation:
            blockers = _authored_blockers(
                plan, case, target_kind, base_url, bound_keys or set(), credential_keys or set(),
                ledger_identity, ledger_configured,
            )
            case.readiness = "blocked" if blockers else "ready"
            case.blocker_reason = "; ".join(blockers) if blockers else None
            continue
        setup_blockers = _setup_blockers(plan, case, target_kind)
        impact = next((str(step).strip() for step in case.steps if _HIGH_IMPACT_STEP.search(str(step))), None)
        if setup_blockers:
            # Keep the explicit approval state for a sole approval blocker so
            # downstream reporting can distinguish it from missing data or
            # unsupported generated prose.
            case.readiness = "approval_required" if impact and len(setup_blockers) == 1 else "blocked"
            case.blocker_reason = "; ".join(setup_blockers)
            continue
        if target_kind in {"android", "ios"}:
            try:
                _compile_mobile_steps(case.steps or [])
            except ValueError as exc:
                case.readiness = "blocked"
                case.blocker_reason = str(exc)
            else:
                case.readiness = "ready"
                case.blocker_reason = None
        else:
            try:
                _compile_steps(case.steps or [], base_url or "")
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
    base_url: str | None,
    browser: str,
    name: str,
    case_ids: set[UUID] | None = None,
    target_kind: str = "web",
    provider: str = "playwright",
    app_asset_id: UUID | None = None,
    device_name: str | None = None,
    platform_version: str | None = None,
    appium_url: str | None = None,
    appium_app: str | None = None,
    target_metadata: dict | None = None,
    settings: Settings | None = None,
) -> ExecutionRun:
    settings = settings or get_settings()
    bound_keys, credential_keys, ledger_identity = await _authored_setup(
        db, plan, user.id, target_kind, app_asset_id, base_url, settings,
    )
    await _preflight_plan(
        plan, base_url, case_ids=case_ids, target_kind=target_kind, bound_keys=bound_keys,
        credential_keys=credential_keys, ledger_identity=ledger_identity,
        ledger_configured=len((settings.UAT_LEDGER_VERIFICATION_KEY or "").strip()) >= 32,
    )
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
    unready = [case for case in automated if case.readiness != "ready"]
    if unready:
        names = ", ".join(case.test_case_key for case in unready[:12])
        suffix = " …" if len(unready) > 12 else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Resolve setup or conversion blockers before running all selected cases: {names}{suffix}",
        )
    missing_source = [case.test_case_key for case in automated if case.source_test_case_id is None]
    if missing_source:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"These imported cases no longer have a source Test Design record: {', '.join(missing_source)}",
        )

    plan.status = "queued"
    source = None
    if plan.source_generation_run_id:
        source = (await db.execute(
            select(GenerationRun.source_document_analysis_id, DocumentAnalysisRun.published_requirement_id)
            .outerjoin(DocumentAnalysisRun, DocumentAnalysisRun.id == GenerationRun.source_document_analysis_id)
            .where(GenerationRun.id == plan.source_generation_run_id, GenerationRun.project_id == plan.project_id)
        )).one_or_none()
    run = ExecutionRun(
        project_id=plan.project_id,
        requested_by_id=user.id,
        execution_plan_id=plan.id,
        name=name.strip() or plan.name,
        base_url=base_url,
        browser=browser,
        target_kind=target_kind,
        provider=provider,
        app_asset_id=app_asset_id,
        device_name=device_name,
        platform_version=platform_version,
        appium_url=appium_url,
        appium_app=appium_app,
        target_metadata=target_metadata,
        total_tests=len(automated),
    )
    db.add(run)
    await db.flush()
    for case in automated:
        blocked = case.readiness != "ready"
        automation = AuthoredAutomation.model_validate(case.automation) if case.automation else None
        bindings = {
            key: plan.fixture_bindings[key] for key in fixture_keys(automation)
            if key in (plan.fixture_bindings or {})
        } if automation else {}
        metadata = target_metadata or {}
        traceability = {
            "requirement_ref": case.requirement_traceability,
            "requirement_id": str(source.published_requirement_id) if source and source.published_requirement_id else None,
            "document_analysis_id": str(source.source_document_analysis_id) if source and source.source_document_analysis_id else None,
            "design_run_id": str(plan.source_generation_run_id) if plan.source_generation_run_id else None,
            "design_case_id": str(case.source_test_case_id),
            "plan_case_id": str(case.id),
            "case_key": case.test_case_key,
            "app_asset_id": str(app_asset_id) if app_asset_id else None,
            "app_sha256": metadata.get("asset_sha256"),
            "target_kind": target_kind,
            "target_url": base_url,
            "provider": provider,
            "device_name": device_name,
            "platform_version": platform_version,
            "fixture_bindings": bindings,
        }
        db.add(
            ExecutionResult(
                execution_run_id=run.id,
                execution_plan_case_id=case.id,
                test_case_id=case.source_test_case_id,
                status=ResultStatus.BLOCKED if blocked else ResultStatus.PENDING,
                error_message=case.blocker_reason if blocked else None,
                evidence={"preflight": case.readiness} if blocked else None,
                execution_spec={
                    "automation": case.automation,
                    "bindings": bindings,
                    "ledger_identity": ledger_identity if automation and automation.outcome else None,
                    "legacy_steps": list(case.steps or []) if automation is None else [],
                    "traceability": traceability,
                },
            )
        )
    if provider == "local_runner":
        db.add(LocalRunnerJob(execution_run_id=run.id, status="queued"))
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
    if provider != "local_runner":
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

    source_title = _source_title(run)
    title = _compact_plan_name((payload.name or "").strip() or source_title)
    plan = ExecutionPlan(
        project_id=run.project_id,
        source_generation_run_id=run.id,
        created_by_id=user.id,
        name=title,
        suite_type=payload.suite_type,
        status="draft",
        source_title=source_title,
        source_created_at=run.created_at,
    )
    db.add(plan)
    await db.flush()
    # The relationship collection is select-in loaded and is not safe to
    # lazy-load from an async endpoint after ``flush``. Persist the immutable
    # snapshot rows directly instead of appending to an unloaded collection;
    # the subsequent owned reload returns the cases in selection order.
    db.add_all(
        _case_snapshot(test_case, plan.id, index)
        for index, test_case in enumerate(sorted(run.test_cases, key=lambda item: item.created_at))
    )
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
    plan = await _load_plan(db, plan_id, user.id, lock=True)
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
        if update.steps is not None:
            normalized_steps = [str(step).strip() for step in update.steps]
            if any(not step for step in normalized_steps):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{case.test_case_key} contains an empty automation step")
            case.steps = normalized_steps
            if "automation" not in update.model_fields_set:
                case.automation = None
        if "automation" in update.model_fields_set:
            case.automation = update.automation.model_dump(mode="json") if update.automation else None
        if update.expected_result is not None:
            normalized_expected = update.expected_result.strip()
            if not normalized_expected:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{case.test_case_key} needs an expected result")
            case.expected_result = normalized_expected
        if "test_data" in update.model_fields_set:
            # Test data is deliberately limited to references/synthetic values;
            # reject fields that look like credentials before they reach JSON.
            serialized = repr(update.test_data)
            if update.test_data is not None and len(update.test_data) > 50:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Test data may contain at most 50 fields")
            if update.test_data is not None and len(serialized) > 20000:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Test data is too large; use a repository or dataset reference")
            if update.test_data is not None and (_contains_sensitive_data(update.test_data) or _SENSITIVE_INPUT.search(serialized)):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Do not store passwords, tokens, or OTPs in test data. Use a non-production reference instead.",
                )
            case.test_data = update.test_data
        case.selected = update.selected
        case.execution_mode = update.execution_mode
        case.readiness = "pending" if update.selected and update.execution_mode == "automated" else (
            "manual_review" if update.selected else "not_selected"
        )
        case.blocker_reason = None
    plan.status = "draft"
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.patch("/execution-plans/{plan_id}/inputs", response_model=ExecutionPlanOut)
async def update_execution_plan_inputs(
    plan_id: UUID,
    payload: ExecutionPlanInputsUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Save non-secret setup references and let preflight re-evaluate cases."""
    plan = await _load_plan(db, plan_id, user.id, lock=True)
    if plan.status not in {"draft", "ready", "blocked"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup inputs cannot be changed after execution is queued. Import a new snapshot instead.",
        )
    existing_references = dict(plan.runtime_inputs or {})
    if len(payload.inputs) > 20:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At most 20 setup references may be supplied")
    requirements = {
        item["key"] for item in _input_requirements(plan)
        if not item["key"].startswith("case:")
    } | set(existing_references)
    unknown = sorted(set(payload.inputs) - requirements)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown setup input(s): {', '.join(unknown)}. Run preflight to refresh the required questions.",
        )
    references = existing_references
    for key, value in payload.inputs.items():
        normalized = _reject_sensitive_reference(value)
        if normalized:
            references[key] = normalized
        else:
            references.pop(key, None)
    plan.runtime_inputs = references or None
    # Changing setup data invalidates the previous readiness decision. The
    # next preflight is the single source of truth for executable cases.
    for case in plan.cases:
        if case.selected and case.execution_mode == "automated":
            case.readiness = "pending"
            case.blocker_reason = None
    plan.status = "draft"
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.get("/execution-plans/{plan_id}/fixtures")
async def list_execution_fixtures(
    plan_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    target_kind: str = "web",
    app_asset_id: UUID | None = None,
    base_url: str | None = None,
):
    plan = await _load_plan(db, plan_id, user.id)
    rows = await scoped_fixtures(
        db, owner_id=user.id, project_id=plan.project_id, target_kind=target_kind,
        app_asset_id=app_asset_id, base_url=base_url,
    )
    return [
        {"id": row.id, "label": row.label, "category": row.category, "parts": allowed_fixture_parts(row), "updated_at": row.updated_at}
        for row in rows
    ]


@router.patch("/execution-plans/{plan_id}/fixtures", response_model=ExecutionPlanOut)
async def bind_execution_fixtures(
    plan_id: UUID,
    payload: FixtureBindingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    plan = await _load_plan(db, plan_id, user.id, lock=True)
    if plan.status not in {"draft", "ready", "blocked"}:
        raise HTTPException(status_code=409, detail="This plan's Test Data bindings are frozen after it is queued.")
    ids = {binding.record_id for binding in payload.bindings.values()}
    rows = await db.scalars(select(AutopilotInputRecord).where(
        AutopilotInputRecord.id.in_(ids), AutopilotInputRecord.owner_id == user.id,
        AutopilotInputRecord.project_id == plan.project_id, AutopilotInputRecord.save_for_reuse.is_(True),
        AutopilotInputRecord.encrypted_value.is_not(None),
        AutopilotInputRecord.category.in_(("credential", "test_data")),
    )) if ids else []
    by_id = {row.id: row for row in rows}
    if any(binding.record_id not in by_id or binding.part not in allowed_fixture_parts(by_id[binding.record_id]) for binding in payload.bindings.values()):
        raise HTTPException(status_code=400, detail="Select reusable Test Data from this project.")
    plan.fixture_bindings = {key: binding.model_dump(mode="json") for key, binding in payload.bindings.items()}
    plan.status = "draft"
    for case in plan.cases:
        if case.selected and case.execution_mode == "automated":
            case.readiness = "pending"
            case.blocker_reason = None
    await db.commit()
    return _plan_payload(plan)


@router.post("/execution-plans/{plan_id}/preflight", response_model=ExecutionPlanOut)
async def preflight_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanPreflight,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    plan = await _load_plan(db, plan_id, user.id, lock=True)
    prior_status = plan.status
    if prior_status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Wait for the active execution before running preflight again.")
    target = await _validate_execution_target(
        db,
        user,
        plan.project_id,
        target_kind=payload.target_kind,
        provider=payload.provider,
        base_url=str(payload.base_url) if payload.base_url else None,
        app_asset_id=payload.app_asset_id,
        device_name=payload.device_name,
        platform_version=payload.platform_version,
        appium_url=payload.appium_url,
        appium_app=payload.appium_app,
        no_reset=payload.no_reset,
        auto_grant_permissions=payload.auto_grant_permissions,
        settings=settings,
        local_runner_id=payload.local_runner_id,
    )
    bound_keys, credential_keys, ledger_identity = await _authored_setup(
        db, plan, user.id, target["target_kind"], target["app_asset_id"], target["base_url"], settings,
    )
    await _preflight_plan(
        plan, target["base_url"], target_kind=target["target_kind"], bound_keys=bound_keys,
        credential_keys=credential_keys, ledger_identity=ledger_identity,
        ledger_configured=len((settings.UAT_LEDGER_VERIFICATION_KEY or "").strip()) >= 32,
    )
    if prior_status in {"completed", "failed"}:
        plan.status = prior_status
    await db.commit()
    return _plan_payload(await _load_plan(db, plan.id, user.id))


@router.post("/execution-plans/{plan_id}/execute", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def execute_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanExecute,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    plan = await _load_plan(db, plan_id, user.id, lock=True)
    if plan.status in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This execution plan is already running")
    target = await _validate_execution_target(
        db,
        user,
        plan.project_id,
        target_kind=payload.target_kind,
        provider=payload.provider,
        base_url=str(payload.base_url) if payload.base_url else None,
        app_asset_id=payload.app_asset_id,
        device_name=payload.device_name,
        platform_version=payload.platform_version,
        appium_url=payload.appium_url,
        appium_app=payload.appium_app,
        no_reset=payload.no_reset,
        auto_grant_permissions=payload.auto_grant_permissions,
        settings=settings,
        local_runner_id=payload.local_runner_id,
    )
    return await _queue_plan_execution(
        plan,
        db,
        background,
        user,
        base_url=target["base_url"],
        browser=payload.browser if target["target_kind"] == "web" else target["provider"],
        name=(payload.name or plan.name),
        target_kind=target["target_kind"],
        provider=target["provider"],
        app_asset_id=target["app_asset_id"],
        device_name=target["device_name"],
        platform_version=target["platform_version"],
        appium_url=target["appium_url"],
        appium_app=target["appium_app"],
        target_metadata={
            **target["target_metadata"],
            "input_references": dict(plan.runtime_inputs or {}),
        },
        settings=settings,
    )


@router.post("/execution-plans/{plan_id}/rerun", response_model=ExecutionRunOut, status_code=status.HTTP_201_CREATED)
async def rerun_execution_plan(
    plan_id: UUID,
    payload: ExecutionPlanRerun,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    plan = await _load_plan(db, plan_id, user.id, lock=True)
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
    target = await _validate_execution_target(
        db,
        user,
        plan.project_id,
        target_kind=source.target_kind,
        provider=source.provider,
        base_url=source.base_url,
        app_asset_id=source.app_asset_id,
        device_name=source.device_name,
        platform_version=source.platform_version,
        appium_url=source.appium_url,
        appium_app=source.appium_app,
        no_reset=bool((source.target_metadata or {}).get("no_reset", False)),
        auto_grant_permissions=bool((source.target_metadata or {}).get("auto_grant_permissions", True)),
        settings=settings,
        local_runner_id=UUID((source.target_metadata or {})["selected_runner_id"]) if (source.target_metadata or {}).get("selected_runner_id") else None,
    )
    return await _queue_plan_execution(
        plan,
        db,
        background,
        user,
        base_url=target["base_url"],
        browser=source.browser,
        name=(payload.name or f"Rerun · {source.name}"),
        case_ids=case_ids,
        target_kind=target["target_kind"],
        provider=target["provider"],
        app_asset_id=target["app_asset_id"],
        device_name=target["device_name"],
        platform_version=target["platform_version"],
        appium_url=target["appium_url"],
        appium_app=target["appium_app"],
        target_metadata={
            **(source.target_metadata or {}),
            **target["target_metadata"],
            "input_references": dict(plan.runtime_inputs or {}),
        },
        settings=settings,
    )

