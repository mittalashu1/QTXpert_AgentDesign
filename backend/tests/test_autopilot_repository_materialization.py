from app.api.routes.autopilot import _repository_materialization_needs_initial_analysis


def test_repository_materialization_recovery_only_runs_during_initial_analysis():
    assert _repository_materialization_needs_initial_analysis({
        "status": "uploaded",
        "stage": "queued",
        "phase": "draft",
    })
    assert _repository_materialization_needs_initial_analysis({
        "status": "analyzing",
        "stage": "reading_mobile_artifact",
        "phase": "preflight",
    })


def test_repository_materialization_does_not_restart_a_partial_checkpoint():
    assert not _repository_materialization_needs_initial_analysis({
        "status": "analyzing",
        "stage": "validating_inputs",
        "phase": "partial",
    })
    assert not _repository_materialization_needs_initial_analysis({
        "status": "analyzing",
        "stage": "ready_for_discovery",
        "phase": "partial",
    })
    assert not _repository_materialization_needs_initial_analysis({
        "status": "analyzed",
        "stage": "ready_for_discovery",
        "phase": "partial",
    })
