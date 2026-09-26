"""Protocol-boundary tests for project-paired local device execution."""
import importlib.util
from pathlib import Path

import pytest

from app.api.routes.local_runners import _decode_evidence, _derived_lease_token, _digest


ROOT = Path(__file__).resolve().parents[2]
AGENT_PATH = ROOT / "tools" / "local_runner" / "agent.py"
spec = importlib.util.spec_from_file_location("qtxpert_local_runner_agent", AGENT_PATH)
agent = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(agent)


def test_lease_secret_is_deterministic_per_runner_run_and_attempt():
    secret = "qtxrunner_test-secret"
    run_id = "25d3ce5f-22b9-4bc1-a842-0d2a300675a1"
    token = _derived_lease_token(secret, run_id, 1)
    assert token == _derived_lease_token(secret, run_id, 1)
    assert token != _derived_lease_token(secret, run_id, 2)
    assert token != _derived_lease_token(secret + "x", run_id, 1)
    assert _digest(token) != token


def test_runner_requires_https_for_cloud_but_allows_local_api_for_tests():
    assert agent.normalize_api_url("https://design.example/api/v1") == "https://design.example/api/v1"
    assert agent.normalize_api_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/api/v1"
    with pytest.raises(ValueError, match="HTTPS"):
        agent.normalize_api_url("http://design.example")


def test_mobile_dsl_accepts_only_explicit_supported_actions():
    compiled = agent.compile_mobile_steps([
        "launch app",
        "tap accessibility_id :: Sign in",
        "fill id :: account-name :: qa-user",
        "assert-text Home",
        "assert-visible xpath :: //android.widget.Button[@text='Continue']",
        "back",
    ])
    assert [action for action, _, _ in compiled] == ["tap", "fill", "assert-text", "assert-visible", "back"]
    assert compiled[0] == ("tap", "accessibility_id", "Sign in")
    assert compiled[1] == ("fill", "id", "account-name :: qa-user")
    with pytest.raises(ValueError, match="Unsupported mobile automation step"):
        agent.compile_mobile_steps(["explore the investment page and choose something suitable"])


def test_mobile_locator_parser_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategy"):
        agent.compile_mobile_steps(["tap css :: .submit"])


def test_evidence_upload_is_bounded_and_validated():
    assert _decode_evidence("aGVsbG8=", 5, "Screenshot") == b"hello"
    with pytest.raises(Exception, match="base64"):
        _decode_evidence("not base64!", 1024, "Screenshot")
    with pytest.raises(Exception, match="limit"):
        _decode_evidence("YWJjZGVm", 3, "Screenshot")
