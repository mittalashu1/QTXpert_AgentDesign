"""
Exporters producing JSON payloads shaped for each test management tool's
import/create API. These are ready to POST directly to the respective
tool's REST API (TestRail `add_case`, Zephyr Scale `testcase`, Xray
`import/test`, Azure DevOps Test Plans `testcases`) - only auth headers and
the target project/suite ID need to be supplied by the caller.
"""
import json

from app.database.models.generation_run import GenerationRun
from app.database.models.test_case import Priority, Severity
from app.exports.base import Exporter, ExportResult

_TESTRAIL_PRIORITY = {Priority.CRITICAL: 4, Priority.HIGH: 3, Priority.MEDIUM: 2, Priority.LOW: 1}
_XRAY_PRIORITY = {Priority.CRITICAL: "Highest", Priority.HIGH: "High", Priority.MEDIUM: "Medium", Priority.LOW: "Low"}
_ADO_SEVERITY = {
    Severity.BLOCKER: "1 - Critical", Severity.CRITICAL: "1 - Critical",
    Severity.MAJOR: "2 - High", Severity.MINOR: "3 - Medium", Severity.TRIVIAL: "4 - Low",
}


class TestRailExporter(Exporter):
    format_name = "testrail"

    def export(self, run: GenerationRun) -> ExportResult:
        cases = [
            {
                "title": tc.scenario,
                "type_id": 1,
                "priority_id": _TESTRAIL_PRIORITY.get(tc.priority, 2),
                "custom_preconds": tc.preconditions,
                "custom_steps": "\n".join(tc.steps),
                "custom_expected": tc.expected_result,
                "refs": tc.requirement_traceability,
                "custom_automation_type": tc.automation_type if tc.is_automation_candidate else None,
            }
            for tc in run.test_cases
        ]
        content = json.dumps({"cases": cases}, indent=2).encode("utf-8")
        return ExportResult(
            filename=f"testrail_import_{run.id}.json", media_type="application/json", content=content
        )


class ZephyrExporter(Exporter):
    format_name = "zephyr"

    def export(self, run: GenerationRun) -> ExportResult:
        cases = [
            {
                "name": tc.scenario,
                "objective": tc.objective,
                "precondition": tc.preconditions,
                "priority": tc.priority.value,
                "labels": [tc.test_type.value, tc.risk_level.value],
                "testScript": {
                    "type": "STEP_BY_STEP",
                    "steps": [{"description": s, "expectedResult": tc.expected_result} for s in tc.steps],
                },
                "customFields": {
                    "Requirement Traceability": tc.requirement_traceability,
                    "Automation Candidate": tc.is_automation_candidate,
                },
            }
            for tc in run.test_cases
        ]
        content = json.dumps({"testCases": cases}, indent=2).encode("utf-8")
        return ExportResult(
            filename=f"zephyr_import_{run.id}.json", media_type="application/json", content=content
        )


class XrayExporter(Exporter):
    format_name = "xray"

    def export(self, run: GenerationRun) -> ExportResult:
        tests = [
            {
                "testtype": "Manual",
                "fields": {
                    "summary": tc.scenario,
                    "description": tc.objective,
                    "priority": {"name": _XRAY_PRIORITY.get(tc.priority, "Medium")},
                    "labels": [tc.test_type.value],
                },
                "steps": [
                    {"action": s, "data": "", "result": tc.expected_result} for s in tc.steps
                ],
                "requirementKeys": [tc.requirement_traceability] if tc.requirement_traceability else [],
            }
            for tc in run.test_cases
        ]
        content = json.dumps({"tests": tests}, indent=2).encode("utf-8")
        return ExportResult(
            filename=f"xray_import_{run.id}.json", media_type="application/json", content=content
        )


class AzureDevOpsExporter(Exporter):
    format_name = "azure_devops"

    def export(self, run: GenerationRun) -> ExportResult:
        work_items = [
            {
                "op": "add",
                "workItemType": "Test Case",
                "fields": {
                    "System.Title": tc.scenario,
                    "Microsoft.VSTS.TCM.Steps": "".join(
                        f"<step id='{i}'><parameterizedString>{s}</parameterizedString>"
                        f"<parameterizedString>{tc.expected_result}</parameterizedString></step>"
                        for i, s in enumerate(tc.steps, start=1)
                    ),
                    "Microsoft.VSTS.Common.Priority": {
                        Priority.CRITICAL: 1, Priority.HIGH: 2, Priority.MEDIUM: 3, Priority.LOW: 4,
                    }.get(tc.priority, 3),
                    "Microsoft.VSTS.Common.Severity": _ADO_SEVERITY.get(tc.severity, "3 - Medium"),
                    "System.Tags": f"{tc.test_type.value}; {tc.risk_level.value}",
                },
            }
            for tc in run.test_cases
        ]
        content = json.dumps({"workItems": work_items}, indent=2).encode("utf-8")
        return ExportResult(
            filename=f"azure_devops_import_{run.id}.json",
            media_type="application/json",
            content=content,
        )
