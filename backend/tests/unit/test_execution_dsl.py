import pytest

from app.api.routes.executions import _compile_steps, _validated_target


def test_compile_supported_execution_steps():
    compiled = _compile_steps(
        [
            "navigate /login",
            "fill #email :: qa@example.com",
            "click button[type=submit]",
            "assert-text Dashboard",
            "assert-url /dashboard",
        ],
        "https://example.com",
    )
    assert compiled[0] == ("navigate", "https://example.com", None)
    assert compiled[1] == ("navigate", "https://example.com/login", None)
    assert compiled[-1] == ("assert-url", "/dashboard", None)


def test_unknown_natural_language_is_blocked():
    with pytest.raises(ValueError, match="Unsupported automation step"):
        _compile_steps(["Log in as a valid customer"], "https://example.com")


def test_private_target_is_rejected():
    with pytest.raises(ValueError, match="disabled"):
        _validated_target("http://127.0.0.1:8000")

