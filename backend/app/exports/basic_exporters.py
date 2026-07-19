"""JSON / CSV / Markdown exporters."""
import csv
import io
import json

from app.database.models.generation_run import GenerationRun
from app.exports.base import Exporter, ExportResult


def _test_case_dict(tc) -> dict:
    return {
        "test_case_id": tc.test_case_key,
        "requirement_id": tc.requirement_traceability,
        "scenario": tc.scenario,
        "objective": tc.objective,
        "priority": tc.priority.value,
        "severity": tc.severity.value,
        "preconditions": tc.preconditions,
        "test_data": tc.test_data,
        "steps": tc.steps,
        "expected_result": tc.expected_result,
        "post_conditions": tc.post_conditions,
        "automation_candidate": tc.is_automation_candidate,
        "automation_type": tc.automation_type,
        "risk_level": tc.risk_level.value,
        "test_type": tc.test_type.value,
    }


class JsonExporter(Exporter):
    format_name = "json"

    def export(self, run: GenerationRun) -> ExportResult:
        payload = {
            "generation_run_id": str(run.id),
            "requirement_summary": run.requirement_summary,
            "risk_analysis": run.risk_analysis,
            "test_cases": [_test_case_dict(tc) for tc in run.test_cases],
        }
        content = json.dumps(payload, indent=2, default=str).encode("utf-8")
        return ExportResult(
            filename=f"testcases_{run.id}.json", media_type="application/json", content=content
        )


class CsvExporter(Exporter):
    format_name = "csv"

    def export(self, run: GenerationRun) -> ExportResult:
        buffer = io.StringIO()
        fieldnames = list(_test_case_dict(run.test_cases[0]).keys()) if run.test_cases else []
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for tc in run.test_cases:
            row = _test_case_dict(tc)
            row["steps"] = " | ".join(row["steps"]) if row["steps"] else ""
            row["test_data"] = json.dumps(row["test_data"]) if row["test_data"] else ""
            writer.writerow(row)
        return ExportResult(
            filename=f"testcases_{run.id}.csv",
            media_type="text/csv",
            content=buffer.getvalue().encode("utf-8"),
        )


class MarkdownExporter(Exporter):
    format_name = "markdown"

    def export(self, run: GenerationRun) -> ExportResult:
        lines = [f"# Test Cases - Run {run.id}", "", f"**Summary:** {run.requirement_summary}", ""]
        for tc in run.test_cases:
            lines += [
                f"## {tc.test_case_key} - {tc.scenario}",
                f"- **Type:** {tc.test_type.value}",
                f"- **Priority:** {tc.priority.value} | **Severity:** {tc.severity.value}",
                f"- **Objective:** {tc.objective}",
                f"- **Preconditions:** {tc.preconditions or 'N/A'}",
                "- **Steps:**",
                *[f"  {i}. {step}" for i, step in enumerate(tc.steps, start=1)],
                f"- **Expected Result:** {tc.expected_result}",
                f"- **Automation Candidate:** {'Yes' if tc.is_automation_candidate else 'No'}",
                "",
            ]
        content = "\n".join(lines).encode("utf-8")
        return ExportResult(
            filename=f"testcases_{run.id}.md", media_type="text/markdown", content=content
        )
