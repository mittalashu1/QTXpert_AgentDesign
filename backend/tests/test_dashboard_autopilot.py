"""Pure tests for project-scoped Autopilot dashboard activity."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.routes.executions import _autopilot_dashboard_summary


def test_dashboard_counts_generated_and_safe_suite_cases_separately():
    job = SimpleNamespace(
        status="analyzed",
        analysis={"tests": [{"test_id": "one"}, {"test_id": "two"}, {"test_id": "three"}]},
        suite_execution={
            "selected_count": 3,
            "executed_count": 2,
            "passed_count": 1,
            "failed_count": 1,
            "deferred_count": 1,
            "skipped_count": 1,
            "finished_at": "2026-09-05T10:00:00+00:00",
            "tests": [
                {"status": "passed"},
                {"status": "failed"},
                {"status": "blocked"},
            ],
        },
    )
    execution = SimpleNamespace(finished_at=datetime(2026, 9, 5, 10, 5, tzinfo=timezone.utc))

    summary = _autopilot_dashboard_summary([job], [execution])

    assert summary.report_tabs == 1
    assert summary.generated_test_cases == 3
    assert summary.suite_runs == 1
    assert summary.smoke_runs == 1
    assert summary.selected_tests == 3
    assert summary.executed_tests == 2
    assert summary.passed_tests == 1
    assert summary.failed_tests == 1
    assert summary.blocked_tests == 1
    assert summary.deferred_tests == 1
    assert summary.skipped_tests == 0
    assert summary.last_run_at == datetime(2026, 9, 5, 10, 5, tzinfo=timezone.utc)


def test_dashboard_marks_input_checkpoint_jobs_without_claiming_execution():
    job = SimpleNamespace(
        status="waiting_for_input",
        analysis={"tests": [{"test_id": "one"}]},
        suite_execution=None,
    )

    summary = _autopilot_dashboard_summary([job], [])

    assert summary.report_tabs == 1
    assert summary.waiting_for_input_jobs == 1
    assert summary.generated_test_cases == 1
    assert summary.suite_runs == 0
    assert summary.executed_tests == 0
