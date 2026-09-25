import logging

from app.api.routes.autopilot import _log_checkpoint_submission_rejection
from app.services.autopilot_input_store import AutopilotInputStoreError


def test_checkpoint_rejection_log_is_actionable_but_never_logs_submitted_values(caplog):
    caplog.set_level(logging.WARNING, logger="app.api.routes.autopilot")
    secret_marker = "credential-value-must-not-be-logged"

    _log_checkpoint_submission_rejection(
        job_id="job-123",
        submitted_count=2,
        error=AutopilotInputStoreError(
            "One or more checkpoint inputs are no longer part of this analysis. "
            f"{secret_marker}"
        ),
    )

    assert "job_id=job-123" in caplog.text
    assert "submitted_count=2" in caplog.text
    assert "error_code=stale_input_key" in caplog.text
    assert secret_marker not in caplog.text